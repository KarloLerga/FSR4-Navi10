# Decision log

| Date | Decision | Evidence / impact |
|---|---|---|
| 2026-10-02 | Renamed the fetch function's `$Args` parameter to `$GitArgs`. | In PowerShell `$Args` is automatic; Git was invoked without the requested arguments. The corrected script fetched the pinned source successfully. |
| 2026-10-02 | Fixed bootstrap `$Repo:` interpolation, preserved the elevated child's exit code, renamed the winget argument array, and fixed the verifier's `$Args` parameter. | Bootstrap first failed to parse; after the fix, the environment verifier had reported command usage/error text instead of version values. A corrected run confirms Ninja 1.13.2 and DXC 1.9.2602.17. |
| 2026-10-02 | Derive the neural pass interval from the upstream provider and validate it against model shader entry points. | The provider schedules passes 1–12; pass 0 is its model pre stage, pass 13 its model post stage, with padding-reset entry points 0–12. |
| 2026-10-02 | Kept upstream checkout and model assets local and ignored them in Git; retain `third_party/LOCK.json`. | The lock gives exact provenance without uploading SDK trees or model blobs in the initial project push. |
| 2026-10-02 | Create `KarloLerga/FSR4-Navi10` as a private repository. | User selected private visibility. |
| 2026-10-02 | Describe the FSR API DLL as unsigned and experimental. | AMD's current documentation says FSR 4.0.2 uses signed DLL distribution and supports RX 9000+; no signature is forged and no compatibility claim is made before validation. |
| 2026-10-02 | Add NaviQSR as a second architecture family while retaining the full dense FSR4 FP16 implementation as teacher, reference, dense fallback, and benchmark. | The user supplied the QSSR addendum and asked to continue. This supersedes the earlier no-new-network/no-topology-reduction constraints only for this separately named network path; acceptance still depends on measured temporal quality and RX 5700 XT timing. |
| 2026-10-02 | Keep Sony QSSR facts, secondary reporting, and NaviQSR proposals distinct. | Sony's official post states a streamlined neural architecture and hand-tuned PS5 implementation; implementation details in the addendum are not asserted by Sony and remain project hypotheses. |
| 2026-10-04 | Add NaviPRISM as an independent filter/SAD reconstruction family and preserve FSR4 plus NaviQSR. | The supplied addendum defines separate `naviprism_filter`, `naviprism_sadnet`, `naviprism_phase`, and measured `auto` paths. |
| 2026-10-04 | Use NaviQSR network and NaviPRISM naming throughout project artifacts and history. | The user explicitly requested the terminology change in source, comments, and commit history. |
