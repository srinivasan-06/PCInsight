# Testing PCInsight (Module 9)

## The one rule
**A passing mocked test is never proof that hardware detection works on a PC.**
A mocked test shows how PCInsight reacts when Windows gives a particular answer. Only the *integration* tests ask a
real Windows PC, and they prove things about **that PC, that Windows install, that user's permissions, that run** -
nothing more.

The test run says this itself: the summary at the end of every `pytest` run states whether the real-hardware tests ran.

## Two kinds of tests
| | Unit / workflow tests | Integration tests |
|---|---|---|
| Files | everything in `tests/` except the next column | `tests/test_integration_windows.py`, `tests/test_system_integration.py` |
| Data | mocked system data (registry, PowerShell/CIM, psutil, file system) | the real PC |
| Runs on | any OS (Windows, Linux, macOS) | Windows only (skipped elsewhere, with the reason printed) |
| Command | `python -m pytest -m "not integration"` | `python -m pytest -m integration -s -rs` |
| Proves | PCInsight handles missing, partial, empty, odd, slow or failing answers without crashing or inventing data | PCInsight agrees with independent Windows sources on this PC |

`test.bat` runs both, in that order, and saves `test-output.txt` and `integration-output.txt`.

## Scenario matrix (Module 9)
"Mocked" = automated on any OS. "Real PC" = `test_integration_windows.py` on Windows. "By hand" = cannot be automated safely.

| Scenario | Mocked tests | Real-PC check | By hand on a real PC |
|---|---|---|---|
| Missing / unavailable hardware information | `test_reliability_collectors.py`: every collector with every system call failing (11 error types), CIM rows with missing columns, odd registry value types; per-collector tests from Modules 2-6 | contract (no invented values) holds on real data | run on a VM, a locked-down PC, a PC without a dedicated GPU |
| Multiple network adapters | `test_reliability_workflows.py::test_many_adapters...` (7 adapters, virtual, APIPA, loopback), `test_network_info.py` | adapters compared with `ipconfig /all` | PC with Wi-Fi + Ethernet + VPN + Hyper-V/WSL |
| Disconnected adapters | same test (Wi-Fi and Bluetooth down: no address, no gateway invented) | adapters that are down must not report a gateway | unplug the cable / switch Wi-Fi off, rescan, compare with `ipconfig` |
| Permission restrictions | `PermissionError`/access-denied for every collector; registry reader error translation; PowerShell blocked | a protected folder is refused cleanly (standard user); contract holds for standard user and administrator | run `test.bat` once normally and once "as administrator"; compare the two outputs |
| Empty results | no GPU / no memory modules / no disks / no adapters / no ports; whole scan empty; UI + PDF | - | PC with no network at all |
| Long device names | 300/5000-character names, many words, non-Latin text: UI never truncates, PDF never truncates up to 2,000 characters and shortens beyond that with a visible notice | - | - |
| PDF save failures | access denied, disk full, I/O error, locked file, `fsync` failure, write that dies halfway, invalid/too-long names, build failure: clear message, old report untouched, no temp file, retry works | file held open by another program (real exclusive handle); protected folder; very long path | save onto a USB stick and pull it out; save onto a full drive |
| Unsupported Windows data | no `winreg`, no PowerShell, Windows 7/Server/future builds, garbage build numbers, unknown architectures | chipset reported as "not exposed", never guessed | Windows Server, Windows 10 LTSC, ARM PC |
| Repeated scans | 20 scans: no thread/widget growth; alternating fail/success; rapid clicking runs one scan; data that disappears between scans disappears from the screens; history grows correctly | 3 real scans in a row: same sections, no leftover threads or PowerShell processes | leave the app open for an hour, scan every few minutes |
| Shutdown during / after a scan | close at 6 different moments of a scan; close with scan + connectivity test + report all running; close twice; close before any scan; stuck scan hits the shutdown time limit; result arriving after close is dropped and not saved to history | closing the window during a real scan leaves no PowerShell process behind | end the task from Task Manager mid-scan, then start again |

## What the Module 9 tests found (and fixed)
1. **Port Analyzer showed stale data.** If a later scan's port collector failed, the page kept showing the *previous* scan's ports. It now says "No port data was collected in the scan from ..." and lists the problem.
2. **One unexpected error removed a whole section.** Memory, graphics and storage only handled their own error type, so any other exception from the system dropped the entire section. They now report the affected values as unavailable and keep going (`common.as_collection_error`; the exception text is never shown).
3. **A report could not be saved when the name contained a null character.** Now a clear "file name is not valid" message.
4. **A single absurdly long value (thousands of characters) made the whole PDF fail to lay out.** Values over 2,000 characters are shortened with a visible notice; realistic names are never cut.

## Running
```powershell
python -m pytest                           # everything (integration tests are skipped off Windows)
python -m pytest -m "not integration"      # mocked tests only
python -m pytest -m integration -s -rs     # real PC only (Windows)
python -m pytest --cov=pcinsight --cov-branch --cov-report=term-missing   # coverage (pip install pytest-cov)
```

## Reading integration results
* A **failure** means PCInsight disagreed with an independent source on this PC: send `integration-output.txt`.
* A line starting `!! CROSS-CHECK MISMATCH` is a *warning*: two routes to the same firmware text differed. Look at it; it may be legitimate formatting.
* A **skip** is not a pass. Read the reason (`-rs`): for example "running as administrator" means the standard-user check did not run.
* Repeat on every hardware / Windows edition / permission level you intend to support. Passing on one PC says nothing about another.

## Adding tests
* Use the factories in `tests/helpers.py` (`make_sources`, `make_device_sources`, `make_net_sources`, ...).
* New collectors must be added to `COLLECTORS` in `tests/test_reliability_collectors.py` - that single list applies the full failure contract to them.
* UI tests that run a scan should use the `no_uncaught` fixture (`test_reliability_workflows.py`) so an exception inside a Qt slot fails the test instead of only printing.
