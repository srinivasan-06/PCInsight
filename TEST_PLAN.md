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
