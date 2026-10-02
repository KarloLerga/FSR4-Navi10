# FSR API compatibility adapter

## Goal
Expose the project's core through an API shape compatible with public AMD FSR API usage so later integration work does not require redesigning the engine.

## ABI
Use public `ffx_api.h` / DX12 backend descriptors from the pinned/current AMD SDK. Export C ABI names:
- `ffxCreateContext`
- `ffxDestroyContext`
- `ffxDispatch`
- `ffxQuery`
- `ffxConfigure`

Do not export random extra functions under AMD names. Project-specific controls can use a separate `fsr4n10_*` API or configuration file.

## Context mapping
For an upscale context, store an opaque wrapper containing:
- validated D3D12 device
- `fsr4n10::Context`
- chosen model/preset capabilities
- backend selection policy
- debug callback/config state

## Dispatch mapping
Translate public descriptors to internal resources without copying image contents. Wrap/borrow `ID3D12Resource*` and command list. Validate dimensions/formats/states according to API contract.

The adapter must not own externally provided resources. It may own internal history/scratch/model buffers.

## Query behavior
Support at minimum queries needed for:
- provider/version/capability identification where API allows
- quality-mode upscale ratios
- resource requirements/memory usage if practical

For unsupported queries, return the documented API error code. Never return success with uninitialized data.

## Loader/signing limitation
AMD current documentation states signed binary distribution is required for official FSR4 integration. This custom DLL is not AMD-signed. Therefore:
- default output name is `fsr4n10_ffxapi.dll`
- documentation calls it an experimental compatibility adapter
- no signature spoofing
- later game integration may need a separate loader/shim and is out of scope here
