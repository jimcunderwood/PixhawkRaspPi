# recommendationsCodex

Date: 2026-06-18

This document tracks the remaining implementation roadmap for the companion and ground station. The core stack is now real: the web, desktop, and mobile shells share the same runtime contract, the companion exposes calibration, farm, swarm, telemetry, and GeoTIFF workflows, and CI already covers the container build path.

## Completed Baseline

- Web, desktop, and mobile shell scaffolding is in place.
- Calibration wizard and PPK processing are implemented and persisted.
- Farm exports, agLeader sync payloads, and automated reports are implemented.
- Swarm configuration, coordination, and collision-awareness workflows are implemented.
- GeoTIFF upload, browse, preview, and delete flows are implemented.
- Telemetry and audit history are persisted and queryable.
- Shell status, calibration history, farm timeline, and flight-log replay panels are now surfaced in the dashboard.
- Docker CI safeguards for the GHCR tag naming issue are in place.

## Remaining Roadmap

### 1. Finish shell parity across web, desktop, and mobile
The shells now share the same product logic, but the operator experience still needs polish on every form factor.

Focus areas:
- offline and reconnect behavior
- responsive layout and navigation parity
- touch-first map editing and desktop pointer ergonomics
- clearer runtime companion configuration handling
- desktop and mobile packaging/versioning flows
- accessibility and keyboard navigation cleanup
- shared shell parity tests so desktop and mobile do not drift from web

### 2. Add regression coverage for the live workflows
The important flows exist, but we still want stronger guardrails so they stay working as the code evolves.

Focus areas:
- browser smoke tests against a live companion
- calibration history browse and rerun coverage
- farm export/report timeline coverage
- swarm config edit and persistence coverage
- GeoTIFF upload/list/get/delete contract tests
- telemetry history and replay coverage
- CI checks that boot the web shell against the companion API
- API contract tests for log-sync history and replay

### 3. Strengthen Companion persistence, observability, and replayable history
The companion has the storage primitives already; the next step is making history easier to inspect and operate.

Focus areas:
- structured logging and metrics exposure
- health, readiness, and disk-pressure visibility
- telemetry export and audit export helpers
- longer-lived history retention and archive management
- replayable operator history for calibration, farm, and swarm actions
- correlation between command logs, telemetry, and workflow records
- flight-log history indexing and replay audit trails

### 4. Harden deployment and release automation
Build and release automation still needs the usual production-grade scaffolding.

Focus areas:
- image publish and release tagging automation
- release-note or changelog generation
- desktop and mobile distribution packaging
- CI smoke tests for published images
- environment and secret validation in release jobs
- deploy-time health gating and rollback checks
- release manifests that record the active shell parity and supported workflow set

### 5. Finish the operator safety, compliance, and payload workflows
The safety/compliance layer is present, but the operator flow still needs a few end-to-end gates.

Focus areas:
- pre-arm checklist and geofence review
- Remote ID and waiver gating
- explicit compliance review before upload or launch
- spray and camera workflow confirmations
- emergency land, abort, and return-to-home decision paths
- payload state and mission-state acknowledgements before release
- operator acknowledgements before replaying, exporting, or re-running archived jobs

## Suggested Priority Order

1. Finish shell parity across web, desktop, and mobile.
2. Add regression coverage for the live workflows.
3. Strengthen Companion persistence, observability, and replayable history.
4. Harden deployment and release automation.
5. Finish the operator safety, compliance, and payload workflows.

## Summary

The project has moved past the placeholder phase. The remaining work is now mostly about polish, regression coverage, and release hardening so the system can behave like a dependable field product.
