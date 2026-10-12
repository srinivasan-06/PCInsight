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
