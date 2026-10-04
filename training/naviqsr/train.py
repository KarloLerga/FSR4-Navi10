"""Train the dense/analytic NaviQSR network on temporal sequences."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

try:
    from .analytic_reconstruction import analytic_reconstruct
    from .datasets.procedural import generate_dataset
    from .losses import total_loss
    from .model import NaviQSRNetwork
except ImportError:  # Support direct execution from the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from training.naviqsr.analytic_reconstruction import analytic_reconstruct
    from training.naviqsr.datasets.procedural import generate_dataset
    from training.naviqsr.losses import total_loss
    from training.naviqsr.model import NaviQSRNetwork


def select_device(requested: str) -> tuple[torch.device, str]:
    if requested == "cpu":
        return torch.device("cpu"), "cpu"
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was explicitly requested but is unavailable")
        return torch.device("cuda"), "cuda"
    if requested == "directml":
        import torch_directml
        device = torch_directml.device()
        return device, "directml"
    if requested != "auto":
        raise ValueError(f"unknown backend: {requested}")
    if torch.cuda.is_available():
        return torch.device("cuda"), "cuda"
    try:
        import torch_directml
        device = torch_directml.device()
        # Exercise the operators used by the model before selecting DirectML.
        x = torch.zeros((1, 4, 8, 8), device=device)
        y = F.grid_sample(x, torch.zeros((1, 4, 4, 2), device=device),
                          align_corners=False)
        if y.shape != (1, 4, 4, 4):
            raise RuntimeError("DirectML grid_sample smoke returned an unexpected shape")
        return device, "directml"
    except Exception as exc:
        return torch.device("cpu"), f"cpu (DirectML unavailable: {type(exc).__name__})"


def _load_sequences(dataset_root: Path) -> list[dict[str, np.ndarray]]:
    index_path = dataset_root / "index.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"dataset manifest is missing: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    sequences = []
    for entry in index["sequences"]:
        with np.load(dataset_root / entry["file"], allow_pickle=False) as archive:
            sequences.append({key: archive[key].copy() for key in archive.files})
    return sequences


def _frame_tensor(array: np.ndarray, device: torch.device) -> torch.Tensor:
    return torch.from_numpy(np.asarray(array, dtype=np.float32)).permute(2, 0, 1)[None].to(device)


def _features(sequence: dict[str, np.ndarray], frame: int,
              device: torch.device) -> torch.Tensor:
    rgb = _frame_tensor(sequence["lr_rgb"][frame], device)
    depth = _frame_tensor(sequence["depth"][frame], device)
    motion = _frame_tensor(sequence["motion"][frame], device)
    reactive = _frame_tensor(sequence["reactive"][frame], device)
    transparency = _frame_tensor(sequence["transparency"][frame], device)
    exposure = torch.full_like(depth, float(sequence["exposure"][frame]))
    jitter = torch.as_tensor(sequence["jitter"][frame], device=device,
                             dtype=torch.float32).view(1, 2, 1, 1)
    jitter = jitter.expand(1, 2, *depth.shape[-2:])
    return torch.cat((rgb, depth, motion, reactive, transparency, exposure, jitter), dim=1)


def train(args: argparse.Namespace) -> dict[str, object]:
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    if args.cpu_threads > 0:
        torch.set_num_threads(args.cpu_threads)
    device, backend = select_device(args.backend)
    dataset_root = args.dataset
    if not (dataset_root / "index.json").is_file():
        generate_dataset(dataset_root, args.sequences, args.frames,
                         args.width, args.height, args.scale, args.seed)
    sequences = _load_sequences(dataset_root)
    if not sequences:
        raise RuntimeError("dataset contains no sequences")

    model = NaviQSRNetwork(input_channels=11, width=args.width_channels,
                           blocks=args.blocks, hf_width=args.hf_width,
                           polyphase_mode=args.polyphase).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate,
                                  weight_decay=1.0e-5)
    output_root = args.output
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "train_log.jsonl"
    started = time.perf_counter()
    model.train()
    updates = 0
    loss_history: list[float] = []
    log_header = {"event": "start", "backend": backend, "device": str(device),
                  "torch": torch.__version__, "seed": args.seed,
                  "dataset": str(dataset_root), "sequences": len(sequences),
                  "model": model.config()}
    with log_path.open("w", encoding="utf-8") as log:
        log.write(json.dumps(log_header) + "\n")
        log.flush()
        while updates < args.steps:
            for seq_index, sequence in enumerate(sequences):
                previous_output = None
                previous_target = None
                previous_jitter = None
                for frame in range(sequence["lr_rgb"].shape[0]):
                    features = _features(sequence, frame, device)
                    target = _frame_tensor(sequence["hr_rgb"][frame], device)
                    motion = _frame_tensor(sequence["motion"][frame], device)
                    reactive = _frame_tensor(sequence["reactive"][frame], device)
                    transparency = _frame_tensor(sequence["transparency"][frame], device)
                    jitter = torch.as_tensor(sequence["jitter"][frame], device=device,
                                             dtype=torch.float32).view(1, 2)
                    reset = bool(sequence["reset"][frame])
                    valid = torch.full_like(reactive, 0.0 if reset else 1.0)
                    history = (torch.zeros_like(target) if reset or previous_output is None
                               else previous_output.detach())
                    prior_jitter = jitter if reset or previous_jitter is None else previous_jitter

                    prediction = model(features)
                    result = analytic_reconstruct(
                        features[:, :3], prediction["controls"], prediction["residual"],
                        int(sequence["scale"]), history_hr=history, motion_lr=motion,
                        current_jitter=jitter, previous_jitter=prior_jitter,
                        history_valid=valid, reactive_lr=reactive,
                        transparency_lr=transparency, taps=args.taps)
                    temporal_valid = (valid * (1.0 - reactive).clamp(0.0, 1.0)
                                     * (1.0 - transparency).clamp(0.0, 1.0))
                    loss, components = total_loss(
                        result["output"], target,
                        None if reset else history,
                        None if reset else previous_target,
                        None if reset else motion,
                        int(sequence["scale"]), jitter, prior_jitter,
                        None if reset else temporal_valid,
                        teacher_target=(_frame_tensor(sequence["teacher_hr"][frame], device)
                                        if "teacher_hr" in sequence else None))
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    previous_output = result["output"].detach()
                    previous_target = target.detach()
                    previous_jitter = jitter.detach()
                    updates += 1
                    loss_history.append(float(loss.detach()))
                    if updates == 1 or updates % args.log_every == 0 or updates == args.steps:
                        record = {"event": "step", "step": updates,
                                  "sequence": seq_index, "frame": frame,
                                  "elapsed_s": time.perf_counter() - started,
                                  "backend": backend, **components}
                        log.write(json.dumps(record) + "\n")
                        log.flush()
                        print(json.dumps(record), flush=True)
                    if updates >= args.steps:
                        break
                if updates >= args.steps:
                    break

    model = model.to("cpu").eval()
    checkpoint = {
        "format": "naviqsr-checkpoint-v1",
        "model_config": model.config(),
        "model_state": model.state_dict(),
        "training": {"backend": backend, "torch": str(torch.__version__),
                     "seed": args.seed, "updates": updates,
                     "mean_last_10_loss": float(np.mean(loss_history[-10:])),
                     "dataset_index": str(dataset_root / "index.json"),
                     "scale": args.scale, "taps": args.taps},
    }
    checkpoint_path = output_root / "naviqsr_checkpoint.pt"
    torch.save(checkpoint, checkpoint_path)
    summary = {"backend": backend, "updates": updates,
               "mean_last_10_loss": checkpoint["training"]["mean_last_10_loss"],
               "checkpoint": str(checkpoint_path), "log": str(log_path),
               "elapsed_s": time.perf_counter() - started}
    (output_root / "training_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("build/naviqsr/procedural"))
    parser.add_argument("--output", type=Path, default=Path("build/naviqsr/training"))
    parser.add_argument("--backend", choices=("auto", "cpu", "cuda", "directml"), default="auto")
    parser.add_argument("--sequences", type=int, default=4)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--width", type=int, default=64, help="procedural LR width")
    parser.add_argument("--height", type=int, default=36, help="procedural LR height")
    parser.add_argument("--scale", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--width-channels", type=int, default=16)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--hf-width", type=int, default=6)
    parser.add_argument("--polyphase", choices=("raw", "haar", "learned1x1"), default="raw")
    parser.add_argument("--taps", type=int, choices=(4, 5, 8), default=5)
    parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1.0e-3)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--log-every", type=int, default=10)
    args = parser.parse_args()
    if args.steps < 1 or args.log_every < 1:
        parser.error("--steps and --log-every must be positive")
    print(json.dumps(train(args), indent=2))


if __name__ == "__main__":
    main()
