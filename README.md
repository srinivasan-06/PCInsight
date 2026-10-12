# PCInsight

Windows desktop app to inspect hardware, OS, network configuration and local listening ports, and export a PDF report. Everything stays local; no internet is needed for scanning.

**Status:** Module 2 (System overview) implemented. Press "Scan now" to read computer name, Windows edition/version/build, architecture, manufacturer/model and uptime. CPU, memory, GPU, storage, network and ports arrive in later modules.

## Requirements
- Windows 10/11, Python 3.10-3.13 (64-bit) from https://www.python.org/downloads/ (tick "Add python.exe to PATH")

## Setup (PowerShell, inside the project folder)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```
If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (asks to change a setting; only run if you agree).

## Run
```powershell
python -m pcinsight
```

## Test
```powershell
python -m pytest
```

## Quick data check without the UI
```powershell
python -m pcinsight.core.system_info
python -m pytest tests/test_system_integration.py -s
```
