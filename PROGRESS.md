# Progress
- [x] Module 1: UI shell (confirmed on Windows)
- [x] Module 2: System overview (confirmed on Windows)
- [x] Module 3: CPU, motherboard, BIOS (confirmed on Windows)
- [x] Module 4: Memory, GPU, storage (confirmed on Windows)
- [x] Module 5: Network configuration (v2 confirmed on Windows)
- [x] Module 6: Local listening-port analyzer - delivered; user reported bugs, DEFERRED to the final debug pass (details not yet received)
- [x] Module 7: PDF reports - delivered; user wants bugs batched into the final debug pass
- [x] Module 8: Settings and scan history - code complete; 429 tests pass on Python 3.10, 3.11 and 3.12
- [ ] Module 8: tried on your Windows PC  <-- awaiting user
- [x] Module 9: tests and reliability - 603 mocked tests pass (95% line+branch coverage); 17 new real-hardware integration tests written but NOT yet run on Windows
- [ ] Module 9: integration tests run on your Windows PC  <-- awaiting user (test.bat part 2, normal and as administrator)
- [ ] Module 10, then the final debug pass for everything (Modules 6, 7, 8 findings)

## Module 8 decisions
- Settings: JSON in %APPDATA%\PCInsight, saved atomically on every change; invalid values are replaced one by one; a damaged file is renamed and defaults used (user is told). A save failure keeps the change active for the session and says so.
- History: SQLite (standard library), one compressed JSON snapshot per scan, secure_delete on, VACUUM after "delete all". Retention by age and count, applied after every scan, at startup and when the limits change. Default ON (local only, easy to turn off and delete). A damaged database is set aside; a newer-version database is refused without being touched; a damaged single scan can be deleted without affecting the others; a locked/failed history never spoils a scan.
- A reopened scan is marked "not live", is not re-saved, and can be used for a report.
- Important ports come from Settings at the moment a scan starts. Report defaults come from Settings; Reports page choices apply to one report only.
- Diagnostic log: off by default, rotating file, can be opened/deleted from Settings, released before deletion (Windows file locks). Tested that scan failures do not put addresses in the log.
- Tests are isolated: PCINSIGHT_DATA_DIR points every test at a temporary folder, so no test can touch real settings/history.
- UI polish found while checking screenshots: saved-scan list column cut-off and missing dark-theme styling (both fixed).

## Ideas parked for later
- Compare two saved scans (what changed).
- Optional redaction of IP/MAC addresses in reports.
- PyInstaller must bundle assets/fonts (package-data already declared).

## Known limitations
- Real-PC behaviour is only proven where you run the tests.
- Connectivity results are not stored in the history (only scans).
- Settings changed in two PCInsight windows at once: the last write wins.
- Report text uses DejaVu Sans: no CJK/Indic scripts (replaced with "?").
- Sidebar icons.
