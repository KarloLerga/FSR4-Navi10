# QRISP import

Qualcomm describes QRISP as research-use data containing sequences with color, depth, motion vectors, jitter/camera metadata, and enhanced high-resolution targets. The published format includes RGBA PNG color, a 4-channel depth PNG encoding, and 16-bit EXR motion vectors; the EXR stores vertical velocity in the first channel and horizontal velocity in the second. This importer applies those conversions and records source hashes. See [Qualcomm's dataset page](https://www.qualcomm.com/developer/software/qualcomm-rasterized-images-dataset) and the [ICCV 2023 dataset supplement](https://openaccess.thecvf.com/content/ICCV2023/supplemental/Mercier_Efficient_Neural_Supersampling_ICCV_2023_supplemental.pdf).

The importer does not fetch the dataset, open an account, or accept terms. First obtain QRISP through Qualcomm's own flow and review its research-use license yourself. Then provide a JSON mapping manifest to the extracted files. This explicit mapping avoids guessing scene-specific naming conventions or modality variants.

Install the optional EXR decoder in the project's isolated environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r training/naviqsr/requirements-qrisp.txt
```

Minimal manifest shape:

```json
{
  "source_root": "C:/datasets/QRISP",
  "segments": [
    {
      "name": "scene_segment_000",
      "scale": 2,
      "motion_channels": {"vertical": "R", "horizontal": "G"},
      "motion_y_sign": -1,
      "camera_json": "scene/segment/camera.json",
      "jitter_path": "frames.{frame}.jitterOffset",
      "frames": [
        {
          "lr_color": "scene/segment/native/frame_000.png",
          "hr_target": "scene/segment/enhanced/frame_000.png",
          "depth_png": "scene/segment/depth/frame_000.png",
          "motion_exr": "scene/segment/motion/frame_000.exr",
          "exposure": 0.0
        }
      ]
    }
  ]
}
```

Include all consecutive frames in a segment. Jitter values are expected in LR-pixel units. QRISP's normalized motion channels are scaled by the selected LR width/height; the default vertical sign converts Unity's Y-up convention to image coordinates. Confirm channel order and sign against the chosen modality before training. The importer sets reactive/transparency masks to zero because QRISP does not provide them in the required schema; MCLD reuse must stay conservative when those signals are absent.

Only after reviewing the applicable license, run:

```powershell
.\.venv\Scripts\python.exe -m training.naviqsr.datasets.qrisp --manifest build/naviqsr/qrisp_manifest.json --output build/naviqsr/qrisp --license-confirmed
```

The flag is an explicit user assertion; the tool does not interpret or accept legal text. Imported data remains under ignored `build/` by default and must not be committed or redistributed based only on this code.
