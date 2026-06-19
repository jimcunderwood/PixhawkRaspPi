# recommendationsCodex

Date: 2026-06-18

This document tracks the remaining implementation roadmap for the companion and ground station. The core pieces are now in place: the web ground station is real, the Leaflet map is live, mission drafting works, and GeoTIFF overlays are backed by SQLite on the companion. The remaining work is about hardening, completion, and validation.

## Current Baseline

- `ground_station/apps/web/` is a working React/Vite control surface with a live field map, telemetry panels, mission editing, and GeoTIFF overlay upload/preview support.
- `raspberry_pi_companion/` now exposes a SQLite-backed GeoTIFF catalog plus upload, list, fetch, preview, and delete routes.
- The main gaps are now production hardening, workflow completion, and end-to-end validation.

## Roadmap

### 1. Finish the ground station as a field-ready app
The current UI is functional, but it still needs the polish required for real operations.

Focus areas:
- offline and reconnect behavior
- clearer map editing affordances
- better fleet selection and status presentation
- a dedicated payload and camera workflow
- saved layouts or mission workspace presets

### 2. Complete the GeoTIFF lifecycle
The SQLite-backed catalog is a solid foundation, but it should become a first-class asset workflow.

Focus areas:
- browse and manage stored overlays in the UI
- associate overlays with missions, fields, or camera sessions
- support metadata updates and cleanup flows
- expose provenance and upload history in the catalog

### 3. Add end-to-end validation for the new workflows
Now that the map and GeoTIFF paths are real, they need full coverage.

Focus areas:
- UI-to-companion upload and preview flow
- mission draft save/load flow
- field boundary editing round-trip
- GeoTIFF upload/list/get/delete contract tests
- SITL-backed mission execution tests

### 4. Expand persistence for operational history
The repo now has useful SQLite-backed storage, and the next step is to make more of the operating history queryable.

Focus areas:
- telemetry history queries
- mission and route snapshots
- overlay provenance and session association
- post-flight artifacts and audit summaries

### 5. Harden deployment and observability
The system needs the usual operational scaffolding before it can be treated as field-ready.

Focus areas:
- containerized builds
- CI that runs companion and ground station checks
- structured logging and metrics
- health and readiness endpoints for both services

### 6. Turn safety and compliance into an explicit operator workflow
The safety primitives exist; the remaining work is to surface them clearly in the operator experience.

Focus areas:
- pre-arm checklist
- geofence awareness on the map
- emergency landing selection
- explicit compliance review before upload or launch

## Suggested Priority Order

1. Complete the GeoTIFF lifecycle in the ground station and companion.
2. Add end-to-end validation for the map, mission, and GeoTIFF flows.
3. Harden persistence, observability, and deployment.
4. Expand the safety and compliance workflow.
5. Polish multi-vehicle and post-flight flows after the core path is stable.

## Summary

The project has crossed the threshold from placeholder scaffolding to a usable core system. The remaining work is to turn that core into a dependable field application with stronger workflows, better history, and more exhaustive validation.
