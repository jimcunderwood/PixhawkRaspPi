# Swarm Architecture

This document defines a concrete companion-side swarm design that lets one drone share navigation state with nearby drones and let the ground station consume the result.

## Goals

- Maintain a shared swarm model across multiple drones.
- Use peer telemetry for separation, deconfliction, and relative-position estimation.
- Keep the primary flight position source on the local drone.
- Expose a simple API surface the ground station can consume directly.

## Design Principle

Peer telemetry should improve:

- separation awareness
- collision avoidance
- relative pose estimation
- confidence scoring
- resilience when one drone has a poor fix

Peer telemetry should not replace:

- local GNSS/RTK as the primary absolute position source
- Pixhawk inertial/navigation state
- safety gates and local flight rules

In other words, swarm data is a fusion input, not the sole source of truth.

## Configuration Schema

The companion should load a swarm config with these sections:

- `swarm_id`: logical swarm or field identifier
- `enabled`: on/off switch for swarm behavior
- `self_drone_id`: the local drone identity
- `role`: `leader`, `follower`, `relay`, `observer`, or `anchor`
- `transport`: local outbound transport for broadcast/ingest
- `peers`: peer registry with per-drone trust and freshness constraints
- `broadcast`: telemetry publish policy
- `fusion`: how peer data influences the estimated state
- `safety`: separation thresholds and loss-of-link behavior

Recommended defaults:

- `broadcast.rate_hz`: 2
- `fusion.mode`: `weighted_gnss`
- `fusion.require_reference_node`: true
- `fusion.max_peer_age_seconds`: 2
- `safety.min_horizontal_separation_m`: 8
- `safety.min_vertical_separation_m`: 3
- `safety.warn_distance_m`: 15
- `safety.critical_distance_m`: 8
- `safety.hold_on_loss`: true

The shared schema and example config live in:

- `ground_station/shared/types/swarm-config.schema.json`
- `ground_station/shared/types/swarm-config.example.json`

## Telemetry Message Shape

Each drone should publish a swarm telemetry message with:

- identity: `swarm_id`, `source_drone_id`, `sample_id`, `sequence`, `timestamp`, `received_at`
- local state: `role`, `vehicle`, `link`
- position: `location`
- motion: `velocity`
- quality: `quality`

Recommended message fields:

```json
{
  "swarm_id": "field-alpha-swarm",
  "source_drone_id": "drone-02",
  "sample_id": "swarm-1700000000-00017",
  "sequence": 17,
  "timestamp": 1700000000.125,
  "received_at": 1700000000.321,
  "role": "follower",
  "location": {
    "latitude": 40.11231,
    "longitude": -74.21291,
    "altitude": 51.8,
    "source": "rtk",
    "accuracy_m": 0.35,
    "covariance_m": [0.25, 0.25, 0.5]
  },
  "velocity": {
    "north_mps": 1.1,
    "east_mps": 0.2,
    "down_mps": -0.1,
    "ground_speed_mps": 1.12,
    "heading_deg": 87.0
  },
  "quality": {
    "fix_type": 6,
    "satellite_count": 18,
    "hdop": 0.7,
    "horizontal_accuracy_m": 0.35,
    "vertical_accuracy_m": 0.5,
    "age_ms": 120,
    "trust_score": 0.93
  },
  "vehicle": {
    "armed": true,
    "mode": "GUIDED",
    "battery_percent": 78
  },
  "link": {
    "transport": "websocket",
    "latency_ms": 42,
    "signal_strength_dbm": -61,
    "packet_loss_percent": 0.2
  }
}
```

## Fusion Logic

The companion should run fusion in four stages.

### 1. Ingest and validate

- Reject samples outside the swarm ID.
- Reject samples older than the configured freshness window.
- Reject samples with missing coordinates.
- Apply trust penalties for stale, low-quality, or low-confidence peers.

### 2. Compute separation

- Convert peer positions to a local meter-based frame.
- Compute pairwise horizontal and vertical separation.
- Raise warnings when peers cross `warn_distance_m`.
- Raise critical alerts when peers cross `critical_distance_m`.

### 3. Estimate corrected state

- Keep the local drone’s GNSS/RTK state as the primary estimate.
- Use peers to nudge the estimate only when quality is good and the config allows it.
- Prefer the configured reference node when one exists.
- Weight self state more heavily than peer state.
- Use peer velocity and heading mainly to smooth short-term motion and relative pose, not to invent absolute position.

Recommended weighting behavior:

- `self_position` dominates when local quality is healthy.
- `peer_position` increases when local fix quality drops.
- `peer_velocity` contributes to short-term smoothing.
- `heading` contributes when movement is low and drift is visible.
- `quality` scales the overall trust of a peer sample.

### 4. Emit outputs

The fusion stage should emit:

- current fused pose
- raw self pose
- nearest-peer separation
- peer count used
- confidence score
- alert list

If peer coverage is poor or stale, the companion should fall back to local position and keep separation warnings active.

## API Endpoints For The Ground Station

The ground station should treat swarm state as a first-class companion service.

### Configuration

- `GET /api/swarm/config`
- `PUT /api/swarm/config`
- `POST /api/swarm/config/validate`

### Status and telemetry

- `GET /api/swarm/status`
- `GET /api/swarm/telemetry`
- `GET /api/swarm/telemetry/history`
- `GET /api/swarm/alerts`
- `GET /api/swarm/separation`
- `GET /api/swarm/fusion`

### Peer registry

- `GET /api/swarm/peers`
- `GET /api/swarm/peers/{drone_id}`
- `POST /api/swarm/peers/{drone_id}/heartbeat`

### Streaming

- `WS /ws/swarm`

### Operational controls

- `POST /api/swarm/broadcast`
- `POST /api/swarm/fusion/recompute`
- `POST /api/swarm/fusion/reset`

Recommended response patterns:

- Use `StatusResponse` envelopes for REST endpoints.
- Return `SwarmStatus` for `GET /api/swarm/status`.
- Return `SwarmFusionState` for `GET /api/swarm/fusion`.
- Return arrays of `SwarmTelemetryMessage` and `SwarmSeparationAlert` for telemetry and alerts.

## Ground Station Behavior

The UI should:

- show per-drone separation warnings on the map
- display the fused estimate alongside the raw local position
- highlight stale peers and low-confidence peers
- allow operator selection of the swarm role and transport profile
- preserve a local fallback if the swarm service is unavailable
- surface the leader-follower role, coverage partitioning, and collision-avoidance status in the dashboard header

## Companion Responsibilities

The companion owns:

- peer telemetry persistence in SQLite
- swarm fusion state persistence in SQLite
- alert generation for separation thresholds
- the API surface that the ground station reads at runtime

## Implementation Order

1. Add the swarm config and telemetry models.
2. Persist peer telemetry and fusion outputs in SQLite.
3. Expose the REST and WebSocket APIs.
4. Surface separation and fusion state in the ground station.
5. Add end-to-end tests for swarm status, alerts, and deconfliction.

## Summary

This design keeps the local drone authoritative for flight control while using peer telemetry for separation, coordination, and confidence boosting. That is the safest and most practical way to turn a swarm into a useful operational feature.
