# Progress
- [x] Module 1: UI shell (confirmed on Windows)
- [x] Module 2: System overview (confirmed on Windows)
- [x] Module 3: CPU, motherboard, BIOS (confirmed on Windows)
- [x] Module 4: Memory, GPU, storage (confirmed on Windows)
- [x] Module 5: Network configuration - code complete; 207 mocked/UI tests pass on Linux (10 Windows-only tests skipped there)
- [ ] Module 5: confirmed on your Windows PC  <-- awaiting user
- [ ] Modules 6-10

## Module 5 decisions
- Base data (names, status, IPs, MAC, mask) from psutil; ONE read-only PowerShell call adds adapter type, link speed, gateway, DNS, DHCP and lease. If PowerShell fails the base data still shows and the rest is "Unavailable" with the reason.
- Connectivity tests are separate and on demand (button on the Network page) with their own timestamp; a scan never sends probes. "No reply" is reported as a result, with a note that some routers ignore ping.
- Bluetooth/Wi-Fi/Ethernet detection uses PhysicalMediaType first (a test caught Bluetooth being misread as Ethernet).
- Loopback interfaces hidden; self-assigned 169.254.x.x addresses flagged; on-link routes are not treated as gateways.
- SSID/signal not collected (privacy and locale-dependent parsing). Addresses never logged (tested).
- Test-suite fix: leaked windows slowed tests 10x; fixture now destroys them.

## Known limitations
- Real-PC behaviour is only proven where you run the integration tests. The PowerShell script could not be executed in the Linux build environment; it is parsed defensively and covered by mocked tests only.
- Gateway ping covers IPv4 gateways only (first two).
- Wi-Fi details beyond connection type and link speed are not collected.
- Connectivity targets are fixed constants until Settings (Module 8).
- Sidebar icons, persisted theme (Module 8).
