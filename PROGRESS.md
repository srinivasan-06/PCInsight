# Progress
- [x] Module 1: UI shell (confirmed on Windows)
- [x] Module 2: System overview (confirmed on Windows)
- [x] Module 3: CPU, motherboard, BIOS (confirmed on Windows)
- [x] Module 4: Memory, GPU, storage (confirmed on Windows)
- [x] Module 5: Network configuration (v2 confirmed on Windows)
- [x] Module 6: Local listening-port analyzer - code complete; 255 tests pass on Python 3.10, 3.11 and 3.12 (11 Windows-only tests skipped on Linux)
- [ ] Module 6: confirmed on your Windows PC  <-- awaiting user
- [ ] Modules 7-10

## Module 6 decisions
- Source: psutil socket table only (no admin needed, no traffic sent, no subprocess, no firewall/process changes; a test guards this).
- Four exact statuses: "Listening locally", "No local listener detected", "Process details unavailable", "UDP endpoint detected; remote reachability not verified".
- TCP and UDP are separate sections; UDP is never open/closed; wildcard/specific bindings say reachability is "not tested"; loopback says only local programs can connect.
- Process lookup failures are shown per row with the reason (access denied / exited / no PID / lookup failed) and counted in the overview; they never hide the row or crash the scan.
- Service names are labelled as convention, not proof; dynamic range 49152+ is explained.
- Important ports are configurable in code (collect_ports(important_ports=...)); UI in Module 8.
- Port-to-process mapping is verified with REAL sockets opened by the test itself (TCP + UDP, on any OS).
- Process: suite now runs on Python 3.10, 3.11 and 3.12 before every delivery.

## Known limitations
- Real-PC behaviour is only proven where you run the integration tests.
- Only IPv4/IPv6 TCP listeners and UDP sockets bound locally; connected (established) sockets are intentionally ignored.
- No remote reachability testing by design.
- Service names come from a built-in table plus the system services file; they are hints only.
- Sidebar icons, persisted theme and editable important-port list (Module 8).
