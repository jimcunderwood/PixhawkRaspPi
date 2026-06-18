# Ground Station Web

This folder contains the first UI foundation for the companion ground station.

## What is included

- Responsive cockpit-style dashboard layout
- Local mock snapshot so the UI renders without a live companion
- Typed companion API client for health, vehicle, readiness, safety, mission, navigation, and telemetry data
- Strong visual shell for future mission planning and map interaction
- Shared mission, telemetry, and companion API helpers live in `ground_station/shared/` so desktop and mobile shells can reuse the same logic
- Shared status and metric widgets live in `ground_station/packages/ui/`
- Mission drafts can be saved locally, exported as JSON, loaded from the companion, and uploaded back through the shared mission API helpers
- Fleet markers are driven from the shared fleet model so multiple drones can appear on the same map

## Companion API integration

Set `VITE_COMPANION_BASE_URL` when you want the app to talk to a live companion instance.

Example:

```bash
VITE_COMPANION_BASE_URL=http://192.168.1.20:8000
```

The app will try the companion first and fall back to the bundled mock snapshot if the API is unavailable.

## Next expansion points

- Map tiles and field overlays
- Mission editor and boundary drawing
- Live telemetry charts and event feed
- Multi-drone fleet panel
- Camera and payload controls
