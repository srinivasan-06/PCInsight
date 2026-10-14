# Progress
- [x] Module 1: UI shell (confirmed on Windows)
- [x] Module 2: System overview (confirmed on Windows)
- [x] Module 3: CPU, motherboard, BIOS (confirmed on Windows)
- [x] Module 4: Memory, GPU, storage (confirmed on Windows)
- [x] Module 5: Network configuration (v2 confirmed on Windows)
- [x] Module 6: Local listening-port analyzer - delivered; user reported bugs, DEFERRED to the final debug pass (details not yet received)
- [x] Module 7: Professional PDF reports - code complete; 302+ tests pass on Python 3.10, 3.11 and 3.12
- [ ] Module 7: tried on your Windows PC  <-- awaiting user (bugs may be batched into the final debug pass)
- [ ] Modules 8-10, then the final debug pass for everything

## Module 7 decisions
- ReportLab (BSD) + bundled DejaVu Sans (licence allows sale inside a larger package). Characters the font lacks (CJK, Kannada...) become "?" and the report says how many were replaced.
- Report engine is separate from scanning (report/ package knows only a finished ScanResult).
- Sections: cover + at-a-glance, system, hardware, network (+ separate connectivity block), ports, warnings/unavailable table, limitations. Header, footer and "Page X of Y" on every page; tables wrap (long unbroken names split), header rows repeat across pages.
- Never fabricated: missing sections say "was not collected"; missing values say Unavailable / Reported as empty / Not exposed by Windows; scan errors and replaced characters are listed in the warnings table.
- Saving: user picks the path (Qt save dialog); written to a temp file then moved into place; cancelled dialog = calm message; permission/locked file, missing folder, folder-as-file, invalid/too-long name, disk full, build failure are all explained; existing files are never damaged.
- Report options (paper size, include network/ports/connectivity) are on the Reports page now; Module 8 will persist them as report preferences.
- Setup scripts added: setup.bat, run.bat, test.bat (test.bat saves test-output.txt and integration-output.txt).
- Test fixes found along the way: end-to-end test was wrongly inside the Windows-only file (moved); writer did not handle a folder chosen as a file name or a too-long name (fixed).

## Ideas parked for later
- Optional redaction of IP/MAC addresses in reports.
- PyInstaller must bundle assets/fonts (package-data is already declared).

## Known limitations
- Real-PC behaviour is only proven where you run the tests.
- Report text uses DejaVu Sans: no CJK/Indic scripts (replaced with "?").
- Reports are not encrypted or password-protected.
- Sidebar icons, persisted theme / important-port list / report preferences (Module 8).
