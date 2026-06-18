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
