# Ground Station Web

This folder contains the first UI foundation for the companion ground station.

For OS-specific install steps and Docker usage, see
[../../docs/INSTALLATION.md](../../docs/INSTALLATION.md).

## What is included

- Responsive cockpit-style dashboard layout
- Local mock snapshot so the UI renders without a live companion
- Typed companion API client for health, vehicle, readiness, safety, mission, navigation, and telemetry data
- Real map, telemetry, mission, calibration history, farm timeline, and swarm configuration panels
- Shared mission, telemetry, and companion API helpers live in `ground_station/shared/` so desktop and mobile shells can reuse the same logic
- Shared status and metric widgets live in `ground_station/packages/ui/`
- Mission drafts can be saved locally, exported as JSON, loaded from the companion, and uploaded back through the shared mission API helpers
- Fleet markers are driven from the shared fleet model so multiple drones can appear on the same map
- Weather briefing status and obstacle-scan status panels are wired into the operator dashboard
- Prescription and variable-rate task state are shown alongside the mission view
- RTK/PPK calibration, farm export/report, flight-log replay, and swarm coordination workflows are wired into the operator dashboard
- The shell status panel shows the current runtime and whether the shell is running in web, desktop, or mobile mode
- Signed-in users can store runtime profiles in SQLite-backed settings, including per-drone companion endpoints, transport types, alternate endpoints, and API keys
- The selected drone's API key is sent on companion requests as both the `x-api-key` header and `api_key` query parameter, which makes the auth path visible in browser devtools and compatible with the companion server

## Companion API integration

Set `COMPANION_BASE_URL` in the runtime environment when you want the app to
talk to a live companion instance. Set `API_KEY` to the same key configured on
the companion machine.

Example:

```bash
COMPANION_BASE_URL=http://192.168.1.20:8000
API_KEY=replace-with-companion-api-key
```

The Docker image reads that value at startup and serves `/runtime-config.json`,
so the UI can be moved to a different host without rebuilding. The same server
also persists user settings in SQLite so each operator can keep their own
runtime profiles. On first startup, the default `admin` user uses `API_KEY` as
its password and the default admin drone connection stores that same API key.

The app will try the companion first and fall back to the bundled mock snapshot if the API is unavailable.

After signing in, use the user settings panel to edit:

- the active profile
- the per-drone transport type
- the per-drone companion endpoint and alternate endpoint list
- the per-drone API key
- the active drone inside the current profile

The selected drone drives the live telemetry, REST, and map-highlighted fleet focus in all shells that share this web UI.

### URL examples for settings

Every connection value should include its protocol. Use these examples when
configuring the ground station, a user profile, or a drone:

| Field | Example |
| --- | --- |
| `COMPANION_BASE_URL` | `http://192.168.1.50:8000` |
| Local `COMPANION_BASE_URL` | `http://localhost:8000` |
| Drone `Companion endpoint` | `http://192.168.1.50:8000` |
| Drone telemetry alternate endpoint | `ws://192.168.1.50:8000/ws/telemetry` |
| Drone events alternate endpoint | `ws://192.168.1.50:8000/ws/events` |
| Secure companion endpoint | `https://companion.example.com` |
| Secure telemetry endpoint | `wss://companion.example.com/ws/telemetry` |
| UDP bridge endpoint | `udp://192.168.1.51:14550` |

The `Api Key` field is only the key value copied from the companion install.
Do not enter `?api_key=...` in endpoint URLs.

## Local Development

```bash
npm install
export COMPANION_BASE_URL=http://192.168.1.20:8000
export API_KEY=replace-with-companion-api-key
npm run dev -- --host 0.0.0.0
```

The `npm run build` and `npm run preview` scripts use the same runtime config
contract as Docker, which makes it easy to validate a release build before
publishing it.

## Next expansion points

- Offline/reconnect behavior
- Touch-first map editing polish
- Browser smoke tests against a live companion
- Calibration history reruns and farm timeline regressions
- Desktop and mobile release packaging
- Camera and payload control refinements
