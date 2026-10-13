# Progress
- [x] Module 1: UI shell (confirmed on Windows)
- [x] Module 2: System overview (confirmed on Windows)
- [x] Module 3: CPU, motherboard, BIOS (confirmed on Windows)
- [x] Module 4: Memory, GPU, storage (confirmed on Windows)
- [x] Module 5: Network configuration - code complete; 207 mocked/UI tests pass on Linux (10 Windows-only tests skipped there)
- [x] Module 5 v1 reported two problems by the user (see below); v2 fixes both
- [ ] Module 5 v2: confirmed on your Windows PC  <-- awaiting user
- [ ] Modules 6-10

## Module 5 decisions
- Base data (names, status, IPs, MAC, mask) from psutil; ONE read-only PowerShell call adds adapter type, link speed, gateway, DNS, DHCP and lease. If PowerShell fails the base data still shows and the rest is "Unavailable" with the reason.
- Connectivity tests are separate and on demand (button on the Network page) with their own timestamp; a scan never sends probes. "No reply" is reported as a result, with a note that some routers ignore ping.
- Bluetooth/Wi-Fi/Ethernet detection uses PhysicalMediaType first (a test caught Bluetooth being misread as Ethernet).
- Loopback interfaces hidden; self-assigned 169.254.x.x addresses flagged; on-link routes are not treated as gateways.
- SSID/signal not collected (privacy and locale-dependent parsing). Addresses never logged (tested).
- Test-suite fix: leaked windows slowed tests 10x; fixture now destroys them.

## Module 5 problems found on the user's PC (fixed in v2)
1. App would not start on Python 3.11: an f-string with a backslash (valid on 3.12, a SyntaxError on 3.10/3.11). Tests had only been run on 3.12. Fix: code corrected; the suite is now run on Python 3.10, 3.11 AND 3.12 before every delivery; tests/test_source_compat.py guards it.
2. Wi-Fi showed "no default gateway / no DNS" while connected. Cause: the PowerShell script used -ErrorAction Stop, so Windows' harmless "IPv6 route not found" notice discarded the real IPv4 gateway. Fix: errors are captured, not fatal; a section fails only if it returned no data AND had a real error. Reproduced and verified with PowerShell 7 using stand-in cmdlets (tests/test_network_script.py, also runs on Windows PowerShell).
3. Smaller: DHCP rows said "not using DHCP" for an adapter with DHCP enabled but no lease; hidden adapters (Wi-Fi Direct etc.) are now described via Get-NetAdapter -IncludeHidden (psutil stays the only source of the adapter list so hidden Windows miniports do not appear).

## Known limitations
- Real-PC behaviour is only proven where you run the integration tests. The network script is tested with stand-in cmdlets on PowerShell 7 (Linux); Windows PowerShell 5.1 behaviour is confirmed only by your run.
- Gateway ping covers IPv4 gateways only (first two).
- Wi-Fi details beyond connection type and link speed are not collected.
- Connectivity targets are fixed constants until Settings (Module 8).
- Sidebar icons, persisted theme (Module 8).
