# Results

## Environment

| Item | Observed value |
|---|---|
| OS | Windows 11 Pro, build 26200 |
| GPU | AMD Radeon RX 5700 XT, PCI vendor/device `1002:731F` |
| Driver | `32.0.21045.1000`, dated 2026-07-23 |
| Git | 2.51.2.windows.1 |
| CMake | 4.3.3 |
| Python | 3.11.9 |
| Visual Studio C++ tools | Visual Studio 18 Community present |
| DXC | Not installed at initial inspection; bootstrap pending |
| Ninja | Not installed at initial inspection; bootstrap pending |
| AMD FSR4 source | `01446e6a74888bf349652fcf2cbf5f642d30c2bf` |
| Current FidelityFX SDK | v2.3.0, `60f4ea81909200d8542eca14dccb2628b763a9a3` |

## Build, shader, quality and performance

No build, shader compile, FSR4 frame, image-quality comparison, stability run or GPU timing has been completed. No performance or quality claim is made.

## Limitations

AMD's published FSR 4.0.2 support is RX 9000 Series and above, with signed DLL integration. This project targets RX 5700 XT with a custom unsigned implementation; hardware execution and later game-loader integration remain unvalidated.
