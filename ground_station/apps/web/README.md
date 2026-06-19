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
- The shell status panel shows the current runtime, companion target, and whether the shell is running in web, desktop, or mobile mode

## Companion API integration

Set `COMPANION_BASE_URL` in the runtime environment when you want the app to
talk to a live companion instance.

Example:

```bash
COMPANION_BASE_URL=http://192.168.1.20:8000
```

The Docker image reads that value at startup and writes `/runtime-config.json`,
so the UI can be moved to a different host without rebuilding.

The app will try the companion first and fall back to the bundled mock snapshot if the API is unavailable.

## Local Development

```bash
npm install
export COMPANION_BASE_URL=http://192.168.1.20:8000
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
