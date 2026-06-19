# Ground Station

Shared client workspace for the drone ground station application.

This layout is designed for one codebase that can target:

- Web
- Desktop
- Mobile

It is also designed to support:

- Multiple runtime transports, not just browser HTTP
- Multiple drones in a single swarm or fleet view
- Per-drone connection profiles, capabilities, and health state
- Platform-specific shells that stay thin while shared logic stays reusable
- Companion runtime discovery so the UI can move between hosts without a rebuild

## Installation

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for Linux, macOS, Windows,
Docker, Docker Compose, and Capacitor install instructions.

## Structure

```text
ground_station/
├── app/                  # Shared product UI and app logic
├── apps/                 # Thin platform shells
├── shared/               # Platform-agnostic domain logic
├── platform/             # Small adapters for platform-specific behavior
├── packages/             # Reusable libraries and UI building blocks
├── tests/                # Unit, integration, and end-to-end tests
├── docs/                 # Design and implementation notes
└── scripts/              # Local automation helpers
```

## Notes

- Keep business logic in `shared/`.
- Keep UI and feature composition in `app/`.
- Keep platform-specific wrappers thin in `apps/` and `platform/`.
- Reuse the same feature modules across web, desktop, and mobile.
- Model drones as a fleet with stable IDs, roles, and transport metadata.
- Treat transport as an adapter layer so web, desktop, and mobile can each use the best available channel.
- Avoid hard-coding `http` as the only control path; the app should tolerate WebSocket, local IPC, UDP/MAVLink bridge, or other device-appropriate links.
- The first working web shell now lives in `apps/web/` and is wired for map, telemetry, and mission drafting.
- Shared mission planning, telemetry parsing, and companion API helpers live under `shared/` so desktop and mobile shells can reuse the same behavior without duplicate logic.
- Shared UI atoms and reusable panels live under `packages/ui/`; platform shells should compose those instead of re-implementing common status/metric widgets.
- Route save/load/upload should be implemented against the shared mission helpers first, then consumed by web, desktop, and mobile shells from the same code path.

The current UI surfaces:

- multi-drone fleet state
- mission and navigation status
- weather briefing and go/no-go results
- obstacle scan results from the companion
- prescription and variable-rate application state
- RTK/PPK and calibration workflow status
- farm integration exports and report generation

## Docker

Build the web image from the repository root:

```bash
docker build -f ground_station/apps/web/Dockerfile -t ground-station-web .
```

Run the web UI with a runtime `.env` file instead of baking the companion URL
into the image:

```bash
cp ground_station/apps/web/.env.example ground_station/apps/web/.env
docker run --rm -p 8080:80 --env-file ground_station/apps/web/.env ground-station-web
```

If the companion lives on another host, set `COMPANION_BASE_URL` to that host's
reachable address, for example `http://192.168.1.50:8000`.

To run the web UI with Docker Compose:

```bash
docker compose --profile ground-station up -d
```

The same Compose file can run the companion on a Pi and the web UI on a
separate workstation. Set `COMPANION_BASE_URL` in the host environment or a
Compose `.env` file so the ground station reaches the other machine at runtime.

## Recommended Ground Station Contract

The client should be organized around three layers:

1. Device shell
1. Transport adapter
1. Fleet and mission domain

That separation lets a tablet app, a desktop app, and a browser app all share the same drone control logic while choosing different transport implementations.

## Fleet Model

Each drone entry should include:

- `drone_id`
- `callsign`
- `role` or mission assignment
- `transport`
- `endpoints` or connection hints
- `capabilities`
- `status`
- `last_heartbeat`

This prevents the app from assuming there is only one active vehicle and makes swarm operations first-class.
