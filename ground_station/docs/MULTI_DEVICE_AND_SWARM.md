# Multi-Device and Swarm Support

This document defines the client-side assumptions for the ground station so the app can work across different device classes and control more than one drone.

## Goals

- Run on web, desktop, and mobile shells
- Support transports beyond browser HTTP
- Control a single drone or a swarm with the same UI and domain model
- Keep connection details isolated from mission and telemetry logic
- Surface fleet, weather, obstacle, prescription, and calibration state in one dashboard

## Core Design Rules

### 1. Device shells stay thin

Each platform shell should only provide:

- Windowing and navigation
- Platform permissions
- Native APIs such as file access or background tasks
- A transport bootstrap

### 2. Transport is abstracted

The app should not assume every command goes over HTTP. A transport adapter may be:

- HTTP/REST
- WebSocket
- Local IPC
- UDP or MAVLink bridge
- Native device bridge

The fleet and mission layers should talk to an interface such as `DroneTransport`, not a concrete protocol.

### 3. Fleet is first-class

The client should maintain a registry of drones instead of a single active vehicle. Each drone needs:

- Stable identity
- Optional callsign or display name
- Role in a swarm
- Connection status
- Active transport
- Capability flags
- Last known telemetry

## Suggested Data Model

```json
{
  "fleet_id": "field-alpha",
  "drones": [
    {
      "drone_id": "drone-01",
      "callsign": "Alpha",
      "role": "leader",
      "transport": {
        "type": "websocket",
        "endpoint": "ws://192.168.1.50:9001"
      },
      "capabilities": ["arm", "takeoff", "mission", "telemetry"]
    },
    {
      "drone_id": "drone-02",
      "callsign": "Bravo",
      "role": "follower",
      "transport": {
        "type": "udp",
        "endpoint": "udp://192.168.1.51:14550"
      },
      "capabilities": ["telemetry", "mission"]
    }
  ]
}
```

## Swarm Behavior

- Commands should be targetable to one drone, a subset, or the whole fleet.
- Mission planning should support per-drone routing and assignment.
- Telemetry should be aggregated by drone ID so the UI can compare units.
- If one transport drops, the fleet should degrade gracefully instead of failing the entire session.
- The operator dashboard should show leader-follower roles, nearest-peer separation, and collision warnings.
- The companion fleet API should be the source of truth for live drone metadata and health.

## Operator Panels

The web shell should expose these companion-backed panels:

- fleet map and drone selector
- weather briefing and go/no-go result
- obstacle scan and edge-AI status
- prescription map and variable-rate application status
- RTK/PPK calibration workflow status
- farm integration export and reporting status

## Configuration Guidance

- Store connection profiles separately from user session state.
- Allow multiple named endpoints per drone for failover or environment-specific routing.
- Keep device-specific configuration in platform storage, but fleet definitions in shared domain storage when possible.
- Validate that every drone has a unique `drone_id`.

## Implementation Order

1. Build the fleet registry and transport interface.
2. Add per-drone connection state and telemetry aggregation.
3. Layer mission assignment and command fan-out on top.
4. Add platform-specific bridge support where needed.
5. Wire the live dashboard panels into the shared API client.

The important rule is to avoid a single hard-coded `BASE_URL` or `currentDrone` assumption anywhere in shared code.
