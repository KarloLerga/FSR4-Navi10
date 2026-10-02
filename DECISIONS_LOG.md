# Decision log

| Date | Decision | Evidence / impact |
|---|---|---|
| 2026-10-02 | Renamed the fetch function's `$Args` parameter to `$GitArgs`. | In PowerShell `$Args` is automatic; Git was invoked without the requested arguments. The corrected script fetched the pinned source successfully. |
| 2026-10-02 | Kept upstream checkout and model assets local and ignored them in Git; retain `third_party/LOCK.json`. | The lock gives exact provenance without uploading SDK trees or model blobs in the initial project push. |
| 2026-10-02 | Create `KarloLerga/FSR4-Navi10` as a private repository. | User selected private visibility. |
| 2026-10-02 | Describe the FSR API DLL as unsigned and experimental. | AMD's current documentation says FSR 4.0.2 uses signed DLL distribution and supports RX 9000+; no signature is forged and no compatibility claim is made before validation. |
