# DraftEdge v3 — iPhone + Computer Access

DraftEdge is a Streamlit web application. The same app can be used from Safari/Chrome on an iPhone and from a desktop browser.

## Option A — Recommended: Streamlit Community Cloud

This is the easiest way to use DraftEdge from anywhere without keeping your computer running.

1. Put the contents of this folder in a GitHub repository.
2. Sign in to Streamlit Community Cloud with GitHub.
3. Choose **Deploy an app**.
4. Select the repository and use `app.py` as the entrypoint.
5. Deploy. The app receives an address similar to `your-name.streamlit.app`.
6. Open that URL on your iPhone or computer.

All Python dependencies are already listed in `requirements.txt`, and `.streamlit/config.toml` is included for cloud/headless operation.

### Add to the iPhone Home Screen

In Safari:

1. Open the deployed DraftEdge URL.
2. Tap **Share**.
3. Tap **Add to Home Screen**.
4. Name it **DraftEdge** and tap **Add**.

This gives you a Home Screen icon that launches the web app directly.

## Option B — Same Wi-Fi, no cloud deployment

Your computer acts as the server. It must remain on and connected to the same network as the iPhone.

### macOS / Linux

```bash
./run_draftedge_network.sh
```

The script prints both:

- `http://localhost:8501` for the computer
- a LAN URL such as `http://192.168.1.50:8501` for the iPhone

Open the LAN URL in Safari on the iPhone.

### Windows

Double-click:

```text
run_draftedge_windows.bat
```

Then run `ipconfig`, find the computer's IPv4 address, and open:

```text
http://YOUR-IPV4:8501
```

If Windows Firewall asks whether Python/Streamlit may accept connections on a private network, allow **Private networks** if you want iPhone LAN access.

## Option C — Docker / other cloud hosts

A `Dockerfile` and `start_cloud.sh` are included. Any service that can run a Docker container or a Python web service can host the app. The service must expose the port passed through `$PORT` or port `8501`.

## Cross-device draft state

### Sleeper draft

If the draft is connected to Sleeper, the completed picks can be re-synced from Sleeper when you open DraftEdge on another device.

### Manual/offline draft

Use:

**League & Draft → Download draft state (.json)**

Then load that JSON on the other device. This prevents losing the board when moving between an iPhone and computer.

## Mobile UI

v3 adds phone-specific layout adjustments:

- touch-sized buttons
- horizontally scrollable tabs
- tighter phone margins and headings
- stacked recommendation/pick controls on narrow screens
- responsive tables with horizontal scrolling for large draft boards
