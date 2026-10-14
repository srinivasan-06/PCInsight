# Test Plan
## Module 1 automated (tests/test_ui_shell.py)
Nav labels/order, each nav opens its page, resize reflow, theme toggle, no fabricated data, About runtime info.
## Module 1 manual on Windows
Launch; click all 7 items; resize/maximize; toggle theme; confirm no console errors.

## Module 2 automated
- tests/test_system_info.py: all fields OK, Win11 label fix, registry failure, empty vs unavailable, placeholders, CIM fallback and its error cases, injection rejection, boot-time errors, architecture mapping, unexpected exceptions contained.
- tests/test_scan_controller.py: background thread, failure + retry, concurrent start refused, repeated scans, shutdown during scan.
- tests/test_ui_scan.py: dashboard/hardware population, honest unavailable/empty display, copy, long names, failure recovery, repeated rescans, close during scan.
## Module 2 real-machine (Windows)
- `python -m pytest tests/test_system_integration.py -s` and `python -m pcinsight.core.system_info`: compare output with Settings > System > About and Task Manager.

## Module 3 automated
- tests/test_cpu_board_info.py: all fields, vendor mapping, registry+CIM fallback per class, unavailable vs empty, placeholders, psutil failures, long names, BIOS date formats, chipset never invented.
- tests/test_scan.py: collector isolation. tests/test_ui_scan.py: sections, CPU card, status-bar problems, repeated rescans.
## Module 3 real-machine (Windows)
- `python -m pytest tests/test_system_integration.py -s` and `python -m pcinsight.core.cpu_board_info`; compare with Task Manager (CPU tab) and `msinfo32` (BaseBoard, BIOS Version/Date).

## Module 4 automated
- test_common.py: byte formatting, int parsing, PowerShell JSON variants/UTF-8/BOM, CIM name validation.
- test_memory_info.py, test_gpu_info.py, test_storage_info.py: full reports, CIM/registry failures, fallbacks, empty results, placeholder values, 4 GB legacy cap, identical GPUs, volume errors, serial numbers never requested.
- test_scan.py: ordering, prefix matching, isolation, concurrency. test_ui_scan.py: new cards/sections, filter.
## Module 4 real-machine (Windows)
- `python -m pytest tests/test_system_integration.py -s`; compare RAM with Task Manager > Memory (slots used, speed, form factor), GPU with Task Manager > GPU (dedicated memory), storage with Task Manager > Performance and Disk Management.

## Module 5 automated
- test_network_info.py: full adapter, connection-type detection, disconnected/APIPA, virtual, multiple adapters and ordering, loopback hidden, PowerShell failure and partial failure, bad PowerShell shapes, PowerShell-only adapters, DHCP off, malformed addresses, listing failure, no address logging, script is read-only.
- test_connectivity.py: all-pass, no reply, ping unavailable, no gateway, gateway limit, TCP fallback, failure reasons, DNS failure, contained exceptions, ping output parsing (incl. localized), argument-list (no shell) and input validation, DNS timeout.
- test_ui_scan.py: network page, local vs connectivity separation, on-demand only, failure recovery, filter, close during tests.
## Module 5 real-machine (Windows)
- `python -m pytest tests/test_system_integration.py -s`; compare with `ipconfig /all` (IPv4, mask, gateway, DNS, DHCP, MAC) and Settings > Network & internet.

## Cross-version rule (added after a Python 3.11 failure)
- Before every delivery the full suite runs on Python 3.10, 3.11 and 3.12.
- tests/test_source_compat.py rejects f-string syntax that only 3.12 accepts.
- tests/test_network_script.py runs the real network PowerShell script against stand-in cmdlets (skipped if no PowerShell is installed).

## Module 6 automated
- test_ports_info.py: exact status wording, all listeners (not only important ones), port->process mapping, one lookup per PID, IPv4/IPv6 rows, binding classification, no remote-reachability claims, important ports (listening/absent/UDP too), UDP never open/closed, every process-lookup failure type, configurable/invalid port lists, service names, TCP/UDP table failures isolated, empty results, duplicates, 800 endpoints, read-only guard, no address logging, REAL TCP/UDP sockets mapped to this process, a real closed port.
- test_ui_scan.py: ports page, dashboard card, other pages exclude port sections, filter, empty state wording.
## Module 6 real-machine (Windows)
- `python -m pytest tests/test_system_integration.py -s`; compare with `netstat -ano -p tcp | findstr LISTENING` and `Get-NetTCPConnection -State Listen` (PIDs) plus Task Manager > Details (PID -> name).

## Module 7 automated
- test_report_pdf.py: required content, metadata, limitations text, unavailable table, header/footer/"Page X of Y" on every page, repeating table headers, long names never truncated, A4/Letter, section options, connectivity run/not-run/left-out, nothing fabricated for a minimal scan, no None/null/nan, scan errors listed, special characters literal, unsupported characters replaced with a warning, 800-row report time, every status combination.
- test_report_writer.py: valid PDF, extension added, unicode paths, atomic overwrite, no path, folder chosen, missing folder, permission denied / file open in viewer, disk full, other OS errors, too-long name, build failure keeps the old file, no personal data in the default file name.
- test_ui_reports.py: disabled before a scan, save, default name, cancel, errors explained + retry, crash contained, options reach the PDF, connectivity included only if run, repeated saves, Open buttons, newest scan used, close while saving, no double start, privacy text.
- test_report_end_to_end.py: real scan -> real PDF (any OS).
## Module 7 on your PC
- test.bat, then Reports page: save a report, open it, compare with the Hardware/Network/Port pages; try cancelling, saving to a read-only folder, and overwriting a report that is open in a PDF viewer.
