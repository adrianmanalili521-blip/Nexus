# NEXUS — Game Route Lab

**NEXUS** is a Windows desktop application for inspecting network latency and comparing candidate endpoints for online gaming. It is an early-stage project focused on diagnostics and route-testing foundations for a future game network optimizer.

> **Project status:** Preview / work in progress. NEXUS does not currently route game traffic through relay servers and is not yet an ExitLag replacement.

## Features

- **Live ping monitor** — monitor a hostname or IP address and view latency samples over time.
- **Network metrics** — review average latency, a jitter estimate, and packet loss.
- **Traceroute diagnostics** — use Windows `tracert` to inspect the path toward a target.
- **Route Lab** — compare up to 12 endpoint addresses using multiple ping attempts.
- **Offline self-test** — run basic checks of input validation and synthetic route-ranking logic without launching a game.
- **CSV export** — save diagnostic results for later review.
- **Desktop interface** — built with Python and PySide6.

## Screenshots
<img width="1363" height="713" alt="image" src="https://github.com/user-attachments/assets/c739783d-0dea-4c87-868c-2dc459076bd3" />

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer (Python 3.12 is recommended for broad package compatibility)
- An internet connection for live network tests

## Installation

1. Install Python from [python.org](https://www.python.org/downloads/). During setup, enable **Add Python to PATH** if that option is offered.
2. Clone this repository or download the source ZIP.

   ```powershell
   git clone https://github.com/YOUR-USERNAME/NEXUS.git
   cd NEXUS
   ```

   Replace the repository URL with your own GitHub repository URL. If you downloaded the ZIP instead, extract it and open PowerShell in the project folder.

3. Install the dependency:

   ```powershell
   py -m pip install -r requirements.txt
   ```

4. Start NEXUS:

   ```powershell
   py main.py
   ```

On Windows, you can also double-click `run.bat` from the project folder.

## How to use

### 1. Run the offline self-test

Open **Route Lab** and select **RUN OFFLINE SELF-TEST**. This checks basic application logic using synthetic test data; it does not prove that a game connection can be optimized.

### 2. Monitor a network target

Enter a hostname or IP address that you want to test, then start monitoring. A public endpoint such as `1.1.1.1` can be used for a general connectivity baseline, but it is **not** your game's server and does not represent the latency to your game lobby.

### 3. Compare candidate endpoints

Use **Route Lab** to compare reachable hostnames or IP addresses. Results help compare connectivity to those endpoints. A low-latency endpoint is not automatically a better relay: the complete path from your PC through a relay to the actual game server must be measured before a route can be recommended.

### 4. Export results

Use the CSV export feature to save available diagnostic results for further analysis.

## Current limitations

NEXUS is currently a **network diagnostics and route-comparison preview**. It does not yet:

- Create, host, or manage relay servers.
- Tunnel or reroute game packets through an alternate route.
- Automatically identify every installed game, lobby, or game server.
- Automatically select a game-specific route or modify Windows routing.
- Guarantee lower ping, reduced packet loss, or improved FPS.

Actual route optimization requires relay infrastructure, safe traffic-routing integration, and testing with real game traffic. Some games also restrict or complicate traffic interception, so compatibility must be evaluated per game.

## Security notes

- NEXUS uses Windows network diagnostic commands such as `ping` and `tracert` for its current tests.
- Do not disable Windows Defender, Smart App Control, or other Windows security protections just to run the project.
- Review source code before running it, and only install Python packages from sources you trust.
- Use network tests only on systems and networks you are authorized to test.

## Technology stack

- Python
- PySide6 / Qt for the desktop UI
- Windows `ping` and `tracert` utilities

## Roadmap

- [x] Desktop diagnostics interface
- [x] Live latency monitoring
- [x] Latency, jitter estimate, and packet-loss metrics
- [x] Traceroute diagnostics
- [x] Candidate endpoint comparison
- [x] Offline self-test
- [x] CSV export
- [ ] Save and manage game profiles
- [ ] Add configurable game and region profiles
- [ ] Integrate relay-server health checks
- [ ] Measure end-to-end routes through relays
- [ ] Add safe, opt-in game traffic routing
- [ ] Validate improvements using real game sessions

## Contributing

Issues, bug reports, and suggestions are welcome. Please include your Windows version, Python version, steps to reproduce the issue, and any relevant error messages. Avoid posting private IP addresses, authentication tokens, or other sensitive information.

## License

No license has been selected yet. Until a license is added to this repository, all rights are reserved by the copyright holder. Add a `LICENSE` file before inviting others to reuse, modify, or distribute the project.

