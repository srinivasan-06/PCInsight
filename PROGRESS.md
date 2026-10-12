# Progress
- [x] Module 1: UI shell (confirmed on Windows)
- [x] Module 2: System overview (confirmed on Windows)
- [x] Module 3: CPU, motherboard, BIOS - code complete; 79 mocked/UI tests pass on Linux (5 Windows-only tests skipped there)
- [ ] Module 3: confirmed on your Windows PC  <-- awaiting user
- [ ] Modules 4-10

## Module 3 decisions
- Chipset is reported as "Not exposed by Windows" (new Status.UNSUPPORTED). Windows has no supported, reliable interface; guessing from PnP device names was rejected as unreliable.
- Shared helpers moved to core/common.py (Module 2 behaviour unchanged; its tests re-run and pass).
- Core counts/frequency from psutil; names/firmware data from registry with CIM fallback.
- Scan collectors are isolated: a failure in one is reported in the status bar and does not block others.
- Copy button hidden on rows without a value.

## Known limitations
- Real-PC behaviour is only proven on machines where you run the integration tests.
- Current CPU frequency is a snapshot; Windows may report base clock instead of live boost.
- Only CPU 0 name/vendor is read from the registry (multi-socket systems show the first processor).
- Firmware may report placeholders ("Default string"); shown with a note.
- Sidebar icons, persisted theme (Module 8), Hardware page search/filter (revisit after Module 4).
