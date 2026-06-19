# Ground Station Desktop

Electron wrapper for the shared ground station web app.

This shell serves the built web bundle locally and injects the runtime
`COMPANION_BASE_URL` value into `/runtime-config.json`, so the desktop app can
point at a Pi companion or a LAN-hosted companion without rebuilding. The
desktop shell also runs the shared settings server with a local SQLite
database, which lets each signed-in user keep their own runtime profiles and
drone connection endpoints.

## Local Development

1. Install dependencies in `../web` and `./`.
2. Build the web app.
3. Launch the Electron shell.

Example:

```bash
cd ../web
npm install
npm run build

cd ../desktop
npm install
npm run dev
```

If you want the desktop shell to reach a live companion instance, set:

```bash
COMPANION_BASE_URL=http://192.168.1.20:8000
```

You can also change the port used by the local desktop server:

```bash
GROUND_STATION_DESKTOP_PORT=4173
```

Settings are stored under the Electron user-data directory by default. Set
`GROUND_STATION_DATA_DIRECTORY` if you want to move the SQLite file elsewhere.

The shell keeps the UI stack aligned with the web app so the same shared
mission, swarm, calibration, farm, and flight-log workflows stay in one codepath.

The desktop shell should render the same shell status card as the web app so
operators can confirm the runtime mode and Companion endpoint from either
surface. After signing in, use the user settings panel to edit per-profile
companion URLs, per-drone transport endpoints, and the active drone selector.
