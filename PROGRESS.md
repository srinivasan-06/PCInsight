# Progress
- [x] Module 1: UI shell (confirmed on Windows)
- [x] Module 2: System overview (confirmed on Windows)
- [x] Module 3: CPU, motherboard, BIOS (confirmed on Windows)
- [x] Module 4: Memory, GPU, storage - code complete; 149 mocked/UI tests pass on Linux (8 Windows-only tests skipped there)
- [ ] Module 4: confirmed on your Windows PC  <-- awaiting user
- [ ] Modules 5-10

## Module 4 decisions
- Memory: total/available from psutil (physical memory vs free memory kept separate); modules, type, speed, slots from CIM. Serial numbers deliberately NOT collected (privacy).
- GPU: VRAM read from the display-driver registry key (accurate); legacy AdapterRAM only as fallback and shown as "4 GB or more" when capped (value 0xFFF00000 found by a failing test).
- Storage: physical disks via Get-PhysicalDisk (type, bus, Windows health summary) with Win32_DiskDrive fallback; drive free space via psutil in a separate "volumes" section. Health is labelled as Windows' summary, not SMART; Unspecified/Unknown values are shown as unavailable, never guessed.
- Network drives and optical drives are skipped (network drives can hang).
- Collectors run in parallel threads and are isolated; PowerShell output forced to UTF-8 with BOM stripping.
- Hardware page now has a filter box.

## Known limitations
- Real-PC behaviour is only proven where you run the integration tests.
- Memory speed is reported by Windows in MHz (usually equals MT/s for DDR).
- Integrated GPUs share system memory; their VRAM figure can be small.
- Disk health is Windows' summary only; no SMART details (would need admin rights / vendor tools).
- Multi-socket CPUs: only processor 0 name/vendor.
- Sidebar icons, persisted theme (Module 8).
