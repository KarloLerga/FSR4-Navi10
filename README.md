# FSR4-Navi10

An experimental Windows / DirectX 12 project targeting AMD Radeon RX 5700 XT (Navi10 / gfx1010), based on the FSR 4.0.2 source and model contract.

The requested endpoint is a deterministic standalone harness, a full FP16 Navi10 backend, an optional per-pass measured selector, and a separately named unsigned FSR API-compatible adapter. This checkout is still being implemented; `RESULTS.md` lists what has and has not been built or measured.

AMD currently documents FSR 4.0.2 for RX 9000 Series and above and distributes official integration as signed DLLs. This project is custom, unsigned, and not an AMD-supported game integration. It does not modify AMD drivers or signed binaries.

## Source and model inputs

Run `./scripts/fetch-upstreams.ps1` to fetch the pinned source and current API-reference SDK and create `third_party/LOCK.json`. The fetched checkouts and weights are ignored by Git. The project preserves their hashes and license provenance, and does not include them in its initial repository push.

## Build status

Bootstrap the Windows toolchain with `./scripts/bootstrap.ps1`, then use the configure/build scripts. See `docs/BUILD_AND_BOOTSTRAP.md` and `.agent/EXEC_PLAN.md` for the milestone contract. Build, validation and release instructions will be completed alongside the implementation.

## Project documents

- `docs/MASTER_SPEC.md` — scope and engineering requirements
- `docs/ACCEPTANCE_CRITERIA.md` — definition of done
- `PROGRESS.md`, `RESULTS.md` — current implementation and measurements
- `THIRD_PARTY_NOTICES.md` — upstream license/provenance
