# PCInsight

Windows desktop app to inspect hardware, OS, network configuration and local listening ports, and export a PDF report. Everything stays local; no internet is needed for scanning.

**Status:** Modules 1-7 implemented. Press "Scan now" to read computer name, Windows edition/version/build, architecture, manufacturer/model, uptime, plus CPU, motherboard, BIOS, memory, graphics, storage and network configuration. Network connectivity tests are optional and start only when you press a button. Listening and ports arrive in later modules.

## Requirements
- Windows 10/11, Python 3.10, 3.11 or 3.12 (64-bit; all three are tested) from https://www.python.org/downloads/ (tick "Add python.exe to PATH")

## Quick start (three double-clicks)
1. **setup.bat** - creates the environment and installs everything (run once, and again after each update).
2. **run.bat** - starts PCInsight.
3. **test.bat** - runs all tests and saves `test-output.txt` and `integration-output.txt` (send these if something fails).

The scripts avoid PowerShell's script-permission prompt. If you prefer typing the commands yourself (PowerShell, inside the project folder):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
pip install -e ".[dev]"
python -m pcinsight
python -m pytest
```

## Quick data check without the UI
```powershell
python -m pcinsight.core.system_info
python -m pcinsight.core.cpu_board_info
python -m pcinsight.core.memory_info
python -m pcinsight.core.gpu_info
python -m pcinsight.core.storage_info
python -m pcinsight.core.network_info
python -m pcinsight.core.ports_info
python -m pytest tests/test_system_integration.py -s
```

## Network privacy
- Scanning only *reads* local network settings; it sends no traffic.
- The optional "Run connectivity tests" button sends: one ping to your default gateway, a TCP connection attempt to 1.1.1.1:443 (then 8.8.8.8:443 if that fails; no data is sent) and a DNS lookup of example.com through your normal resolver.
- Wi-Fi network names (SSIDs) and signal strength are not collected. Addresses are never written to logs.

## Port Analyzer: what it does and does not tell you
- It reads only this computer's own socket table. It sends nothing, scans no other computer, and never changes firewall rules or stops programs.
- "Listening locally" means a program here is waiting for connections. It does NOT mean other computers can reach the port; your firewall, router and network decide that, and PCInsight does not test it.
- "No local listener detected" does not prove a port is closed from outside.
- UDP endpoints are listed separately and are never called open or closed (UDP has no connection state).
- Process names can be refused by Windows for system or other users' programs ("Process details unavailable"). Running as administrator may reveal more; it is not required.
- The list of important ports is a constant (`DEFAULT_IMPORTANT_PORTS` in `core/ports_info.py`) until the Settings page arrives in Module 8.

## PDF reports
Reports page -> choose what to include and the paper size -> "Save PDF report...". The PDF has the product name, scan time, system, hardware, network and port results, a warnings/unavailable table, and a limitations section, with a header, footer and "Page X of Y" on every page. It is built offline, saved only where you choose (written to a temporary file first, so a failure never damages an existing report), and never uploaded. Only values from the scan appear: anything missing is stated as missing.
