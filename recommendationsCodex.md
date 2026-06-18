# recommendationsCodex

Date: 2026-06-18

This file captures the highest-value issues and missing features I see after reviewing the companion project, with emphasis on what would make the Raspberry Pi companion and its surrounding ecosystem more complete, reliable, and usable in the field.

## Issues

### 1. Ground station is still effectively a placeholder
The companion backend is fairly complete, but the `ground_station/` workspace only contains documentation, type schemas, and planning notes. There is no real UI, mission editor, live map, or fleet dashboard yet.

Why it matters:
- Operators need a practical control surface for missions, telemetry, payloads, and safety events.
- The project is missing the main human-facing product layer.

### 2. README and status language is more optimistic than the repo state
Several docs describe the system as complete or production ready, but the repository still has major missing deliverables, especially on the ground-station side and in deployment automation.

Why it matters:
- New contributors may overestimate readiness.
- It becomes harder to prioritize real gaps when the docs are ahead of the implementation.

### 3. Validation is still too limited for a flight-adjacent system
There is good unit coverage around some modules, but the repo still lacks a strong integration story for:
- SITL-based mission execution
- end-to-end API workflows
- hardware-in-the-loop validation
- long-running stability tests

Why it matters:
- Drone software needs confidence across failure modes, reconnection, telemetry load, and command sequencing.

### 4. Deployment and operations are underbuilt
There is no obvious containerization, release pipeline, metrics endpoint, or standardized rollout workflow for the companion app.

Why it matters:
- Field systems need reproducible builds, easy updates, and clear rollback paths.
- Operational issues are harder to diagnose without metrics and health telemetry.

### 5. Security is functional but not hardened enough
The API has auth and command authority concepts, but the system still appears to be missing stronger production protections such as:
- TLS/mTLS guidance
- rate limiting
- user/session management beyond shared API keys
- explicit secret handling guidance

Why it matters:
- This system controls aircraft and field operations, so authentication alone is not enough.

### 6. UX for safety and compliance needs more operator-facing clarity
The companion tracks safety state, waivers, and Remote ID metadata, but the repo still lacks a dedicated operator workflow for:
- preflight checklists
- safety exceptions
- compliance review
- post-flight audit summaries

Why it matters:
- Field operators need quick, unambiguous confirmation before arming or launching.

### 7. Documentation is broad, but not yet tied to implementation workflows
The docs are detailed, but some critical paths are spread across multiple files and can be hard to follow end-to-end.

Why it matters:
- Onboarding and maintenance are slower than they need to be.
- A first-time operator or contributor may not know the exact path from setup to first flight.

## Features

### 1. Real ground station application
Build the actual client application in `ground_station/` with:
- map view for live vehicle tracking
- waypoint and boundary editing
- mission upload/download controls
- payload panel
- telemetry charts
- multi-drone/fleet awareness

### 2. Mission planning UI
Add a visual mission builder that supports:
- waypoint editing and drag/drop
- spray route generation
- survey grid generation
- loiter/orbit planning
- altitude profile visualization

### 3. Mapping workflow completion
The backend already has mapping primitives, but the product would benefit from a full mapping workflow:
- survey presets by camera and crop type
- geotag review and export tooling
- NDVI preview review in the UI
- orthomosaic preview and export status
- point-cloud scan plan generation

### 4. Post-flight data workflow
Add a first-class post-flight experience:
- automatic flight log bundle creation
- photo/session review
- spray application report generation
- export to GeoJSON/CSV/PDF
- cloud upload hooks for archives

### 5. Stronger fleet and swarm support
Extend the current single-vehicle assumptions into a proper fleet model:
- multiple vehicle profiles
- per-vehicle health and transport state
- swarm or leader/follower mission assignments
- unified map and alerting

### 6. Operational monitoring
Add production-grade observability:
- metrics endpoint
- structured logs
- alerting for battery, link loss, GPS loss, and sensor failures
- long-duration stability checks

### 7. Safety workflow improvements
Build operator workflow around safety states:
- pre-arm checklist UI
- explicit arming acknowledgement
- geofence and no-fly zone editor
- emergency landing zone visualization
- compliance and waiver review before mission start

### 8. Deployment packaging
Add reproducible deployment assets:
- Dockerfile and compose files
- systemd hardening guidance
- release automation
- OTA/upgrade strategy with rollback

### 9. Testing expansion
Add test layers that match the mission-critical nature of the software:
- SITL integration tests
- API contract tests for all public endpoints
- hardware abstraction tests for GPIO/camera/sensors
- load tests for WebSocket telemetry

### 10. Ground station transport abstraction
Keep the client transport-agnostic so the same UI can talk over:
- HTTP/WebSocket
- local IPC
- MAVLink bridge
- device-appropriate fallback channels

## Suggested Priority Order

1. Build the ground station UI foundation.
2. Add the mission and mapping workflows that the backend already anticipates.
3. Expand validation with SITL and integration tests.
4. Harden deployment, observability, and security.
5. Turn compliance and post-flight reporting into first-class operator workflows.

## Bottom Line

The companion backend is no longer the biggest gap. The biggest missing pieces are the operator experience, deployment discipline, and validation pipeline that make the system safe and usable in the real world.
