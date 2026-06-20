# Ground Station

Shared client workspace for the drone ground station application.

Invariant:

- Companion and Ground Station are separate installs and separate runtime targets.
- Ground Station depends on at least one Companion being available.
- Any install, config, docs, or code changes for Ground Station assume the Companion exists on another machine or service, not bundled inside it.

This layout is designed for one codebase that can target:

- Web
- Desktop
- Mobile

It is also designed to support:

- Multiple runtime transports, not just browser HTTP
- Multiple drones in a single swarm or fleet view
- Per-drone connection profiles, capabilities, and health state
- Platform-specific shells that stay thin while shared logic stays reusable
- Companion runtime discovery so the UI can target a reachable Companion without a rebuild

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
- The desktop shell lives in `apps/desktop/` and serves the built web bundle in an Electron wrapper.
- The mobile shell lives in `apps/mobile/` and wraps the same web bundle through Capacitor.
- Shared mission planning, telemetry parsing, and companion API helpers live under `shared/` so desktop and mobile shells can reuse the same behavior without duplicate logic.
- Shared UI atoms and reusable panels live under `packages/ui/`; platform shells should compose those instead of re-implementing common status/metric widgets.
- Runtime companion discovery is shared across shells so web, desktop, and mobile can point at the same reachable Companion without rebuilding.
- Route save/load/upload should be implemented against the shared mission helpers first, then consumed by web, desktop, and mobile shells from the same code path.
- Shell parity is a first-class goal: the same runtime status, map, and workflow panels should be reachable from web, desktop, and mobile.
- Calibration history, farm report timelines, and flight-log replay history should stay visible in the operator dashboard for quick validation.
- Live workflow regression coverage should exercise calibration, farm, swarm, and GeoTIFF flows against a running Companion instance.

The current UI surfaces:

- multi-drone fleet state
- mission and navigation status
- weather briefing and go/no-go results
- obstacle scan results from the companion
- prescription and variable-rate application state
- RTK/PPK and calibration workflow status
- farm integration exports and report generation
- swarm configuration and coordination status
- flight-log sync status and replay history

## Docker

Build the web image from the repository root:

```bash
docker build -f ground_station/apps/web/Dockerfile -t ground-station-web .
```

Run the web UI with a runtime `.env` file instead of baking the companion URL
or API key into the image:

```bash
cp ground_station/apps/web/.env.example ground_station/apps/web/.env
docker run --rm -p 8080:80 --env-file ground_station/apps/web/.env ground-station-web
```

If the companion lives on another host, set `COMPANION_BASE_URL` to that host's
reachable address, for example `http://192.168.1.140:8000`. Copy the companion
`API_KEY` into the ground-station `.env`; it becomes the default `admin`
password and is copied into the default admin drone connection settings.

To run the web UI with Docker Compose:

```bash
docker compose --profile ground-station up -d
```

The same Compose file can run the companion profile on one machine and the
ground-station profile on another. Treat them as separate installs: the
ground-station profile reads `ground_station/apps/web/.env`, so copy that file
from the example and set `COMPANION_BASE_URL` to the reachable Companion on
another machine or service, plus `API_KEY`, before first startup.

## Connection URL Examples

Use full URLs in the ground-station user and drone settings. Do not enter a
bare IP address.

| Setting | Example | Notes |
| --- | --- | --- |
| Ground-station `COMPANION_BASE_URL` | `http://192.168.1.140:8000` | Companion REST/API base URL. Use the companion machine IP and API port. |
| Local development `COMPANION_BASE_URL` | `http://localhost:8000` | Use only when the companion API is running on the same machine. |
| Drone `Companion endpoint` | `http://192.168.1.140:8000` | Recommended primary endpoint for a drone connection. REST calls and telemetry discovery use this base URL. |
| Drone alternate telemetry endpoint | `ws://192.168.1.140:8000/ws/telemetry` | Optional explicit WebSocket telemetry URL. `wss://` is the secure form when the companion is behind HTTPS. |
| Drone alternate events endpoint | `ws://192.168.1.140:8000/ws/events` | Optional WebSocket event stream URL for tooling or future event panels. |
| Drone MAVLink UDP bridge | `udp://192.168.1.51:14550` | Use for a drone or bridge that is reachable over UDP instead of the companion REST API. |

Use `https://companion-host:port` and `wss://companion-host:port/...` when the
companion is served through TLS. The `Api Key` field should contain only the key
value copied from the companion install, not a URL query string.

## Desktop

The desktop shell lives in `apps/desktop/` and reuses the built web bundle.
See [apps/desktop/README.md](apps/desktop/README.md) for the Electron launch
steps.

## Mobile

The mobile shell lives in `apps/mobile/` and reuses the same shared web build.
See [apps/mobile/README.md](apps/mobile/README.md) for Capacitor build steps.

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
