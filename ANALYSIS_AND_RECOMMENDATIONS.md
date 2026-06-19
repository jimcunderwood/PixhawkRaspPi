# Spray & Mapping Drone Companion Computer — Analysis & Recommendations

**Analyzed:** June 18, 2026 (Updated)  
**Project:** PixhawkRaspPi — Agricultural Drone Raspberry Pi Companion + Ground Station  
**Analysis Base:** Full source-code review of both `raspberry_pi_companion/` and `ground_station/`

---

## Executive Summary

This project is a **significantly more complete system** than previously documented. The companion computer (`raspberry_pi_companion/`) contains ~12,000 lines of production-quality Python spanning MAVLink communication, mission planning, payload control, telemetry, mapping/photogrammetry, safety/compliance, and a comprehensive REST/WebSocket API with authentication, idempotency, audit logging, and command authority.

The ground station (`ground_station/`) has a **working web application** built with React + Leaflet that provides a cockpit-style interface with a real map, live telemetry streaming, draft mission editing, fleet awareness, GeoTIFF overlay support, safety/compliance status panels, and companion API integration.

**Critical gaps that remain:** Deployment infrastructure (Docker/CI/CD), comprehensive testing (only 7 tests), edge AI/vision processing, multi-drone/swarm coordination, mobile app shell, variable rate application (prescription maps), and weather integration.

---

## Project Health Overview

### Strengths ✅
| Area | Assessment |
|------|-----------|
| Architecture | Clean modular design with separation of concerns across both companion and ground station |
| MAVLink Integration | Robust with reconnection, UDP-out/SITL support, parameter synchronization |
| Mission Management | Full upload/download/verify/clear cycle with checksum verification |
| Obstacle Avoidance | Comprehensive ArduPilot parameter config (PRX1_TYPE, AVOID_ENABLE, OA_TYPE, bendy ruler, GPIO/ROS/MAVLink sensor backends) |
| Terrain Following | Rangefinder, terrain database, RTL terrain mode, ROS bridge support |
| API Design | FastAPI with auth (role-based API keys), audit logging, idempotency, safety gates, command authority leases |
| Payload Control | Spray pump (GPIO), flow sensor (interrupt-driven), pressure sensor (ADC), tank level, camera trigger (GPIO pulse), camera (OpenCV), video recording |
| Sensor Integration | GPIO (RPi.GPIO), ADC (MCP3008 SPI), ROS bridge (rclpy), MAVLink distance sensors, flow rate monitoring |
| **Mapping & Survey** ✅ | **Survey grid generation, photogrammetry planning (CameraSpec, GSD calculation, overlap), Geotagging (EXIF/CSV), NDVI calculation, orthomosaic preview, point cloud scan planning** |
| **Telemetry Persistence** ✅ | **SQLite-backed time-series database with schema, rotation, compaction, and query by time window** |
| **Safety & Compliance** ✅ | **Geofence zones (no-fly, landing, emergency), Remote ID state, Part 107 waivers, pre-flight checklists, progressive failsafe (warn → RTL → land), dynamic altitude geofencing** |
| **Ground Station** ✅ | **Working React + Leaflet web app with map, boundary/waypoint editing, survey preview, live telemetry stream, telemetry charts, fleet panel, GeoTIFF overlay, safety/navigation panels** |
| Configuration | Environment variables, SQLite databases (telemetry, profiles, safety state), calibration management |
| Client API Integration | Shared TypeScript modules for mission/route/planning/fleet that work across web, desktop, and mobile |
| Documentation | README, QUICKSTART, SETUP, ARCHITECTURE, SWARM_ARCHITECTURE, PROJECT_STRUCTURE |

### Weaknesses ❌
| Area | Assessment |
|------|-----------|
| Testing Coverage | Only 7 test files — no unit tests for connection_manager, API routes, or safety manager |
| Integration Testing | No SITL-based automated tests despite `install_sitl.sh` existing |
| Deployment | No Docker, no CI/CD pipeline, no monitoring integration (Prometheus/Grafana) |
| Security | No TLS (HTTPS not configured by default), no mTLS, no WireGuard for remote ops |
| Edge AI | No vision processing (YOLO, TensorFlow Lite, Coral TPU) despite obstacle avoidance hardware config |
| Multi-Drone / Swarm | Fleet data structures exist but no multi-vehicle telemetry aggregation or swarm coordination |
| Weather Integration | Not implemented — no METAR/TAF/wind APIs integrated |
| Mobile App | React Native/Capacitor shell is empty |
| Variable Rate Application | Spray is on/off only — no prescription map parsing or GPS-synchronized rate adjustment |
| RTK/PPK Workflows | No base station wizard, NTRIP client, or PPK post-processing pipeline |

---

## Current State by Feature Area

### Companion Computer — What Exists

| Module | Lines | Status | Notes |
|--------|-------|--------|-------|
| `src/mavlink/connection_manager.py` | 1,500 | **Production** | Full vehicle control, parameter sync, mission upload/download/verify, sensor fusion (MAVLink/GPIO/ROS obstacle), terrain hooks, callback system |
| `src/api/server.py` | 4,468 | **Production** | 80+ REST endpoints, WebSocket telemetry + events, auth (role-based API keys), idempotency, audit logging, command authority, Swagger UI |
| `src/payloads/controller.py` | 1,799 | **Production** | Spray pump, flow sensor (interrupt), pressure/tank (ADC), camera trigger (GPIO pulse), camera (OpenCV capture/stream/record), spray sessions, application records, GeoJSON export, EPA/FAA compliance reports |
| `src/telemetry/collector.py` | 243 | **Production** | SQLite-backed telemetry collection, live WebSocket streaming, statistics |
| `src/telemetry/database.py` | 684 | **Production** | Normalized schema (location/attitude/velocity/battery/GPS/RTK/terrain/payload), auto-rotation, compaction |
| `src/mapping/planner.py` | 623 | **Production** | Survey grid generation, CameraSpec, GSD calc, geotagging (EXIF/CSV), NDVI, orthomosaic preview, LiDAR scan planning |
| `src/missions/planner.py` | 874 | **Production** | Mission items, field boundaries, navigation config (obstacle avoidance/terrain) |
| `src/safety/manager.py` | 510 | **Production** | Geofence zones, Remote ID, waivers, pre-flight checklists, progressive failsafe, dynamic geofencing, emergency landing zones |
| `src/config/settings.py` | — | **Production** | Pydantic-settings with environment variable loading |
| `src/config/profiles.py` | — | **Production** | Config profile save/apply from SQLite |
| `src/audit/logger.py` | — | **Production** | Rotating file audit log |
| `src/logsync/manager.py` | — | Implemented | Flight log sync management |
| `src/mapping/geotiff_store.py` | — | **Production** | GeoTIFF upload, preview generation, asset management |

### Ground Station — What Exists

| Area | Lines | Status | Notes |
|------|-------|--------|-------|
| `apps/web/src/App.tsx` | 819 | **Working** | Full cockpit UI with map, telemetry, mission editor, fleet, safety, navigation panels |
| `apps/web/src/components/FieldMap.tsx` | 357 | **Working** | Leaflet map with boundary/waypoint drawing, survey preview, breadcrumb, GeoTIFF overlay, fleet markers |
| `apps/web/src/components/MissionEditor.tsx` | — | **Working** | Boundary/waypoint editing mode controls, route save/load/upload/download |
| `apps/web/src/components/TelemetryCharts.tsx` | — | **Working** | Real-time telemetry charts |
| `apps/web/src/components/FleetPanel.tsx` | — | **Working** | Multi-drone fleet status panel |
| `apps/web/src/hooks/useTelemetryStream.ts` | — | **Working** | WebSocket telemetry stream + REST fallback |
| `shared/mission/routes.ts` | — | **Working** | Route draft CRUD with localStorage persistence |
| `shared/mission/planning.ts` | — | **Working** | Survey preview computation, polygon center |
| `shared/api/mission.ts` | — | **Working** | Companion API client for mission upload, field boundaries |
| `shared/api/companion.ts` | — | **Working** | Companion snapshot loading API client |
| `shared/fleet/mock.ts` | — | **Working** | Fleet configuration with mock data |
| `packages/ui/src/MetricCard.tsx` | — | **Working** | Reusable metric display card |
| `packages/ui/src/StatusChip.tsx` | — | **Working** | Reusable status indicator |

### What is Still Missing / Will Be Addressed Later

The features below represent authentic gaps where no code exists yet, organized by priority.

---

## 🔴 CRITICAL Gaps

### 1. Deployment Infrastructure (Docker + CI/CD)

**Current state:** No Dockerfile, no docker-compose, no CI/CD pipeline.

**Impact:** Every deployment is a manual process. There's no reproducible build, no automated testing, no artifact publishing.

**Required:**
- `Dockerfile` with multi-stage build for ARM64 (Raspberry Pi 4/5) plus ARMv7 fallback
- `docker-compose.yml` for companion + optional services (mosquitto MQTT, postgis for geospatial)
- GitHub Actions CI pipeline that runs tests against SITL
- Automatic build and publish to GitHub Container Registry or Docker Hub
- Release tagging with auto-generated changelog

### 2. Comprehensive Testing

**Current state:** Only 7 test files exist:
- `test_api_contracts.py`
- `test_connection_manager.py`
- `test_mapping_planner.py`
- `test_mission_planner.py`
- `test_payload_controller.py`
- `test_performance_fixes.py`
- `test_safety_manager.py`
- `test_storage_and_exports.py`

**Missing:** No tests for the API server routes, telemetry collector/database, safety manager failsafe logic, or connection_manager mission methods. No integration tests against SITL. No performance/load tests.

**Required:**
- Unit tests for all `api/server.py` routes (use `httpx.AsyncClient` + `pytest-asyncio`)
- Unit tests for `telemetry/collector.py` and `database.py`
- Unit tests for `safety/manager.py` edge cases (zone transitions, battery state machine)
- Integration tests: SITL-based mission upload/download/verify cycle
- Performance tests: WebSocket throughput, telemetry database write rate

### 3. Monitoring & Alerting

**Current state:** No Prometheus metrics endpoint, no health check endpoint beyond readiness, no alerting.

**Required:**
- `/metrics` endpoint exposing Prometheus counters (connected status, telemetry points, API calls, errors)
- Systemd watchdog integration
- Grafana dashboard template for companion metrics
- Configurable SMS/email/webhook alerts for critical events (lost link, low battery, geofence breach)

---

## 🟠 HIGH Priority Gaps

### 4. Security Hardening

**Current state:** API key auth exists, but no TLS, no mTLS, no WireGuard.

**Required:**
- TLS/HTTPS via reverse proxy (Caddy/Autocert) or built-in cert generation
- mTLS for companion-to-ground-station communication
- WireGuard tunnel setup script for remote operations
- Rate limiting per API key
- JWT-based session management (currently static API keys only)

### 5. Edge AI & Computer Vision

**Current state:** Obstacle avoidance hardware (MAVLink distance sensors, GPIO, ROS) is supported, but there is no onboard vision processing.

**Required:**
- YOLO or TensorFlow Lite object detection (person, vehicle, wire, tree)
- Stereo camera or ToF depth integration for obstacle ranging beyond MAVLink
- Coral TPU / Intel NCS2 inference acceleration
- Crop health monitoring from aerial imagery
- Weed detection for spot-spray targeting

### 6. Weather Integration

**Current state:** No weather data is consumed by the companion or ground station.

**Required:**
- METAR/TAF parsing for pre-flight weather checks (wind, visibility, ceiling)
- In-flight wind monitoring (gust above threshold → RTL)
- Precipitation radar overlay on ground station map
- Spray drift modeling based on wind direction/speed

### 7. Multi-Drone / Swarm Support

**Current state:** Fleet data structures exist in the ground station (`shared/types/fleet.ts`, `FleetPanel` component), but there is no multi-vehicle coordination.

**Required:**
- Multi-vehicle telemetry aggregation in the ground station (many WebSocket connections)
- Fleet management API on the companion (vehicle registry, discovery)
- Swarm coordination: leader-follower, coverage partitioning, inter-drone collision avoidance
- Shared communication channel (MAVLink forwarding via companion)

---

## 🟡 MEDIUM Priority Gaps

### 8. Variable Rate Application (VRA)

**Current state:** Spray is simple on/off with basic flow rate monitoring. No GPS-synchronized rate adjustment.

**Required:**
- Prescription map parsing (shapefile, GeoJSON, KML)
- Real-time GPS-synchronized flow rate adjustment
- Boom section control with overlap prevention
- As-applied map generation

### 9. RTK/PPK Calibration & Processing

**Current state:** RTK/PPK config parameters exist in the mission planner, but no operational workflows.

**Required:**
- Base station setup wizard
- NTRIP client for correction data relay
- PPK post-processing pipeline via RTKLIB integration
- Accuracy assessment reporting

### 10. Mobile Application

**Current state:** Capacitor/React Native shell directories exist but are empty.

**Required:**
- Mission monitoring and camera view from phone/tablet
- Emergency stop button
- Offline basemap caching
- Push notifications for mission events

### 11. Farm Management Integration

**Current state:** No integration with farm management systems.

**Required:**
- ISOXML support for precision agriculture compatibility
- Shapefile/GeoJSON import for field boundaries
- Automated spray report generation (PDF/CSV)
- Field operation history

### 12. Flight Log Sync from Pixhawk

**Current state:** Companion logs system events, but does not automatically download Pixhawk `.bin`/`.log` files after landing.

**Required:**
- Automatic Pixhawk log download after landing detection
- Log aggregation (companion events + Pixhawk logs)
- Cloud upload for long-term storage

---

## 🔵 LOWER Priority Gaps

### 13. Performance Optimizations

- Use Raspberry Pi GPU (MMAL/OpenMAX) for hardware-accelerated video encoding
- Connection pooling for SQLite telemetry database
- AsyncIO conversion of remaining thread-based components
- HTTP/2 support, response compression (gzip/brotli)

### 14. Camera Pipeline Enhancements

- PiCamera/HQ camera module native driver (currently uses OpenCV)
- Hardware JPEG encoder for faster photo capture
- Video recording using GPU-accelerated codecs

### 15. UI Polish for Ground Station

- Dark/light theme support
- Keyboard shortcuts for mission editing
- Undo/redo for boundary and waypoint edits
- Full-screen map mode
- Offline PWA support

---

## Implementation Priority Matrix

| Priority | Feature | Effort | Impact | Dependencies |
|----------|---------|--------|--------|-------------|
| 🔴 P0 | Docker + CI/CD pipeline | 1-2 weeks | Critical | Companion API already ready |
| 🔴 P0 | Comprehensive unit/integration tests | 3-4 weeks | Critical | None |
| 🔴 P0 | Prometheus monitoring + alerting | 1-2 weeks | High | None |
| 🟠 P1 | TLS/HTTPS + mTLS security | 1-2 weeks | High | Cert management |
| 🟠 P1 | Edge AI / computer vision | 4-8 weeks | High | Coral TPU / camera |
| 🟠 P1 | Weather integration | 2-3 weeks | Medium | API key needed |
| 🟠 P1 | Multi-drone / swarm support | 4-6 weeks | Medium | Major architectural work |
| 🟡 P2 | Variable rate application (VRA) | 3-4 weeks | Medium | Prescription maps |
| 🟡 P2 | RTK/PPK calibration workflows | 2-3 weeks | Low | RTKLIB integration |
| 🟡 P2 | Mobile application | 2-3 months | Low | Ground station first |
| 🟡 P2 | Farm management integration | 3-4 weeks | Low | API contracts |
| 🟡 P2 | Flight log sync from Pixhawk | 1 week | Medium | Post-landing detection |
| 🔵 P3 | Performance optimizations | 2-3 weeks | Low | Profiling data |
| 🔵 P3 | Camera pipeline (GPU encoding) | 1-2 weeks | Low | PiCamera HAL |
| 🔵 P3 | UI polish (themes, undo/redo) | 2-3 weeks | Low | None |

---

## What Was Already Implemented Since Last Analysis

The following items from the June 2026 analysis were found to already be implemented in the codebase:

| Previously Reported as Missing | Current Status | Where |
|-------------------------------|---------------|-------|
| Ground Station (map + telemetry + mission editor) | ✅ **Working web app** | `ground_station/apps/web/src/` |
| Survey grid generation | ✅ **Implemented** | `raspberry_pi_companion/src/mapping/planner.py` (623 lines) |
| Telemetry persistence (SQLite) | ✅ **Implemented** | `raspberry_pi_companion/src/telemetry/database.py` (684 lines) |
| Safety gate improvements | ✅ **Implemented** | `raspberry_pi_companion/src/safety/manager.py` (510 lines) |
| Geotagging pipeline (EXIF + CSV) | ✅ **Implemented** | `raspberry_pi_companion/src/mapping/planner.py` |
| NDVI/vegetation indices | ✅ **Implemented** | `raspberry_pi_companion/src/mapping/planner.py` |
| Orthomosaic preview | ✅ **Implemented** | `raspberry_pi_companion/src/mapping/planner.py` |
| Point cloud / LiDAR scan planning | ✅ **Implemented** | `raspberry_pi_companion/src/mapping/planner.py` |
| Geofence zones (no-fly, landing) | ✅ **Implemented** | `raspberry_pi_companion/src/safety/manager.py` |
| Remote ID + Part 107 waivers | ✅ **Implemented** | `raspberry_pi_companion/src/safety/manager.py` |
| Pre-flight checklist automation | ✅ **Implemented** | `raspberry_pi_companion/src/safety/manager.py` |
| Dynamic geofencing | ✅ **Implemented** | `raspberry_pi_companion/src/safety/manager.py` |
| Emergency landing zone ID | ✅ **Implemented** | `raspberry_pi_companion/src/safety/manager.py` |
| Audit logging | ✅ **Implemented** | `raspberry_pi_companion/src/audit/logger.py` |
| Config profiles | ✅ **Implemented** | `raspberry_pi_companion/src/config/profiles.py` |
| GeoTIFF asset store | ✅ **Implemented** | `raspberry_pi_companion/src/mapping/geotiff_store.py` |
| Command authority (control lease) | ✅ **Implemented** | `raspberry_pi_companion/src/api/server.py` (ControlAuthority) |
| Idempotency support | ✅ **Implemented** | `raspberry_pi_companion/src/api/server.py` (idempotency middleware) |
| Spray application records (GeoJSON) | ✅ **Implemented** | `raspberry_pi_companion/src/payloads/controller.py` |
| EPA/FAA compliance reports | ✅ **Implemented** | `raspberry_pi_companion/src/payloads/controller.py` |

---

## Architecture Recommendations

### Immediate (0-1 month)
1. **Add Docker + CI/CD** — Single most impactful improvement for deployment reliability
2. **Write comprehensive tests** — Start with API route tests, then SITL integration tests
3. **Add Prometheus `/metrics` endpoint** — Foundation for monitoring and alerting

### Short-term (1-3 months)
4. **TLS/HTTPS + security hardening** — Reverse proxy with autocert certs
5. **Edge AI pilot** — YOLO obstacle detection + Coral TPU inference
6. **Weather integration** — METAR/TAF pre-flight checks

### Medium-term (3-6 months)
7. **Multi-drone support** — Ground station multi-vehicle views + companion fleet API
8. **Variable rate application** — Prescription map parser and GPS-synchronized rate control
9. **Mobile app** — Capacitor web view wrapping the existing web app

### Long-term (6-12 months)
10. **RTK/PPK calibration workflows** — Base station wizard + PPK post-processing
11. **Farm management integration** — ISOXML, agLeader API, automated reports
12. **Swarm coordination** — Leader-follower, coverage partitioning, inter-drone collision avoidance

---

## Specific Files Requiring Changes

| File | Issue | Recommended Action |
|------|-------|-------------------|
| No Dockerfile | Reproducibility | Add multi-stage ARM64 Dockerfile |
| No CI config | No automated testing | Add GitHub Actions workflow |
| `raspberry_pi_companion/src/api/server.py` | No metrics endpoint | Add `GET /api/v1/metrics` with Prometheus counters |
| `raspberry_pi_companion/tests/` | 7 tests only | Add tests for api routes, telemetry, safety manager |
| `raspberry_pi_companion/requirements.txt` | Missing test deps | Add pytest-asyncio, httpx, pytest-mock |
| `ground_station/apps/web/` | No Docker setup | Add frontend Dockerfile for nginx static serving |
| No docker-compose.yml | No service orchestration | Add docker-compose with companion + optional services |
| No WireGuard config | Remote operations at risk | Add WireGuard setup script and documentation |
| No Grafana dashboard | No monitoring UI | Add dashboard JSON template |

---

## Lines of Code Summary

| Component | Estimated LOC | Maturity |
|-----------|--------------|----------|
| `raspberry_pi_companion/src/mavlink/connection_manager.py` | 1,500 | Production |
| `raspberry_pi_companion/src/api/server.py` | 4,468 | Production |
| `raspberry_pi_companion/src/payloads/controller.py` | 1,799 | Production |
| `raspberry_pi_companion/src/telemetry/` | 927 | Production |
| `raspberry_pi_companion/src/mapping/` | 700+ | Production |
| `raspberry_pi_companion/src/missions/planner.py` | 874 | Production |
| `raspberry_pi_companion/src/safety/manager.py` | 510 | Production |
| `raspberry_pi_companion/src/config/` | 200+ | Production |
| `raspberry_pi_companion/src/audit/` | 100+ | Production |
| Companion total | ~12,000+ | **Production-ready for single-drone ag operations** |
| `ground_station/apps/web/src/` | 1,800+ | Working MVP |
| `ground_station/shared/` | 500+ | Working |
| `ground_station/packages/ui/` | 100+ | Working |
| Ground station total | ~2,500+ | **Functional MVP** |

---

## Conclusion

The Raspberry Pi companion computer is **production-ready for single-drone agricultural spraying and mapping operations**. It has a comprehensive API, robust MAVLink handling, advanced payload control with sensor fusion, a full mapping/photogrammetry pipeline, and a complete safety/compliance system.

The ground station is a **functional MVP** with a real map, live telemetry, mission editing, GeoTIFF overlay support, and fleet awareness — suitable for field operations with further polish.

The project's remaining gaps are focused on **deployment infrastructure** (Docker, CI/CD, monitoring), **security hardening** (TLS, WireGuard), **testing** (comprehensive unit + integration), and **advanced capabilities** (edge AI, multi-drone, weather integration, VRA) that would elevate the system from a solid single-drone platform to a multi-vehicle, fully automated agricultural operations system.

**Total estimated project investment to date:** ~15,000+ lines of code across companion and ground station.

---

*Analysis updated June 18, 2026 — Based on full source review of both projects.*