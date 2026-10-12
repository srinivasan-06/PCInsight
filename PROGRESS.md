# Progress
- [x] Module 1: UI shell (confirmed working on Windows by user)
- [x] Module 2: System overview - code complete; 51 mocked/UI tests pass on Linux (2 Windows-only tests skipped there)
- [ ] Module 2: confirmed on your Windows PC (run tests + integration test + manual checks)  <-- awaiting user
- [ ] Modules 3-10

## Module 2 decisions
- Username is NOT collected (privacy; not needed for the overview).
- Registry is the primary source (fast, no subprocess); PowerShell CIM is a fallback for manufacturer/model only.
- Scans run on a background thread; the window waits for a running scan when closing.
- No auto-scan at startup; the user presses "Scan now".

## Known limitations
- Real Windows detection verified only on the developer's PC after you run the integration test; mocked tests do not prove every PC works.
- Windows registry labels Windows 11 as "Windows 10"; corrected using build >= 22000.
- Firmware may report placeholders ("To Be Filled By O.E.M."); shown with a note.
- Uptime may be inflated by Windows Fast Startup.
- No sidebar icons yet; theme choice not persisted (Module 8).
