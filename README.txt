NEXUS - GAME ROUTE LAB PREVIEW

Requirements:
- Windows 10/11
- Python 3.10 or newer (Python 3.12 is recommended for widest package compatibility)
- Internet connection for real ping comparisons

Install:
1. Extract this ZIP to a normal folder, such as Documents\NEXUS.
2. Open the folder in File Explorer.
3. Double-click run.bat.

If dependencies are missing, open PowerShell in this folder and run:
  py -m pip install -r requirements.txt
  py main.py

What's included:
- Live ICMP ping monitor with latency graph, average, jitter estimate and packet loss
- Windows tracert diagnostics
- Route Lab to compare up to 12 endpoint addresses using four pings each
- Offline self-test for basic validation and synthetic route-ranking logic
- CSV export

Important limitations:
This is a diagnostics and route-lab preview, NOT yet a full ExitLag replacement. It does not create relay servers, tunnel game packets, automatically detect every game's lobby/server, or change Windows routing. A low ping to a relay endpoint alone does not mean the complete path to a game server will be better. Real route optimization requires relay infrastructure and safe traffic-routing integration, followed by tests against actual game traffic.

Windows security:
Do not disable Windows security features just to run this. If Windows blocks a file, check the warning and verify where the file came from. You can run the Python source from a folder after installing the dependency rather than downloading an unknown executable.
