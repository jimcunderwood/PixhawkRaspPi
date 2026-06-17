# Architecture and Design

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Ground Station (PC/Tablet)               │
│                      Web Browser / App                       │
│                   (React, WebGL, REST Client)                │
└────────────────┬──────────────────────────────────────────┬─┘
                 │ WiFi / MAVLink Radio                      │
                 │ JSON over HTTP/WebSocket                  │ MAVLink Telemetry
                 │                                            │
        ┌────────▼──────────────────────────────────────────▼──┐
        │                                                       │
        │         Raspberry Pi 4 - Companion Computer          │
        │                                                       │
        │  ┌────────────────────────────────────────────────┐  │
        │  │            FastAPI Server (Port 8000)         │  │
        │  │  - REST API Endpoints                         │  │
        │  │  - WebSocket Telemetry Stream                 │  │
        │  │  - Request/Response Handler                   │  │
        │  └────────────────────────────────────────────────┘  │
        │                     ▲                                 │
        │                     │                                 │
        │  ┌──────────────────┼──────────────────────────────┐ │
        │  │                  │                              │ │
        │  │  ┌───────────────────────────┐   ┌───────────┐ │ │
        │  │  │ Connection Manager        │   │ Telemetry │ │ │
        │  │  │ - ARM/DISARM              │   │ Collector │ │ │
        │  │  │ - TAKEOFF/LAND            │   │ - Logger  │ │ │
        │  │  │ - MODE CHANGES            │   │ - Streamer│ │ │
        │  │  │ - GOTO LOCATION           │   └───────────┘ │ │
        │  │  │ - NAV SAFETY PARAMS       │                 │ │
        │  │  └──────────────────────────┘                    │ │
        │  │                                                   │ │
        │  │  ┌──────────────────┐   ┌──────────────────────┐│ │
        │  │  │ Mission Planner  │   │ Payload Controller  ││ │
        │  │  │ - Waypoints      │   │ - Spray Pump        ││ │
        │  │  │ - Field Bounds   │   │ - Camera            ││ │
        │  │  │ - Auto Routes    │   │ - Flow Sensor       ││ │
        │  │  └──────────────────┘   └──────────────────────┘│ │
        │  └────────────────────────────────────────────────┘  │
        │                     ▲                                 │
        │                     │ Serial UART                     │
        │                     │ (/dev/serial1, 57600 baud)     │
        └─────────────────────┼─────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Pixhawk 4         │
                    │ Flight Controller  │
                    │                    │
                    │ - Motors/ESCs      │
                    │ - Sensors          │
                    │ - Stabilization    │
                    │ - Failsafes        │
                    └────────────────────┘
```

## Components

### 1. Connection Manager (`src/mavlink/connection_manager.py`)

**Responsibilities**:
- Establish MAVLink connection to Pixhawk
- Vehicle control (arm, disarm, takeoff, land, goto)
- Flight mode changes
- Apply obstacle avoidance and terrain-following parameters
- Monitor connection health
- Event callbacks for state changes

**Key Methods**:
- `connect()` - Establish connection
- `arm()` / `disarm()` - Arm/disarm vehicle
- `takeoff(altitude)` - Begin takeoff
- `land()` - Land drone
- `goto_location(lat, lon, alt)` - Autonomous flight to point
- `set_mode(mode)` - Change flight mode (GUIDED, AUTO, LOITER, etc.)
- `apply_navigation_config(config)` - Apply avoidance/terrain Pixhawk params
- `get_navigation_status()` - Report relevant Pixhawk navigation params
- `get_vehicle_state()` - Query current state

**State Management**:
- Connected flag
- Vehicle object from DroneKit
- Connection thread for health monitoring

### 2. Mission Planner (`src/missions/planner.py`)

**Responsibilities**:
- Create and manage waypoint missions
- Handle field boundaries (spray zones)
- Generate spray mission patterns
- Persist navigation safety config
- Mark mission items as relative-altitude or terrain-altitude
- Track mission execution progress
- Persist missions to file

**Data Structures**:
- `GeoPoint` - Single GPS coordinate
- `MissionItem` - Waypoint with metadata
- `FieldBoundary` - Polygon boundary for field
- `NavigationConfig` - Obstacle avoidance and terrain-following settings
- Mission list with sequence tracking

**Key Methods**:
- `add_waypoint()` - Add waypoint to mission
- `add_loiter_point()` - Add loiter (circle) waypoint
- `add_spray_zone()` - Generate spray passes over field
- `start_mission()` / `pause_mission()` / `abort_mission()`
- `save_mission()` / `load_mission()` - Persistence
- `update_navigation_config()` - Update persisted navigation settings

### 3. Telemetry Collector (`src/telemetry/collector.py`)

**Responsibilities**:
- Continuously collect vehicle state
- Store historical data (circular buffer)
- Broadcast updates to WebSocket clients
- Compute statistics (min/max/avg)
- Stream live telemetry

**Components**:
- `TelemetryCollector` - Background collection loop
- `TelemetryPoint` - Single timestamped reading
- `LiveTelemetryStream` - WebSocket broadcast management
- `TelemetryManager` - High-level interface

**Update Cycle**:
1. Background thread calls `vehicle_getter()` every N seconds
2. Data added to circular buffer (max 3600 points)
3. Callbacks triggered for new data
4. WebSocket clients receive updates

### 4. Payload Controller (`src/payloads/controller.py`)

**Responsibilities**:
- Control spray pump via GPIO relay
- Manage camera (photo/video recording)
- Monitor flow sensor for spray volume
- Track payload usage statistics

**Payload Types**:
- `SprayPump` - GPIO relay control
- `FlowSensor` - Pulse counter integration
- `CameraController` - Video/photo capture via OpenCV

**GPIO Pinout** (configurable in `.env`):
- GPIO 17: Spray pump relay signal
- GPIO 27: Flow sensor pulse input

**Statistics Tracking**:
- Total spray time
- Total volume sprayed
- Photos/videos captured
- Recording duration

### 5. FastAPI Server (`src/api/server.py`)

**Responsibilities**:
- Serve REST API endpoints
- Handle WebSocket connections
- Request validation via Pydantic
- CORS support for web clients

**API Endpoints** (See README for full list):

```
Vehicle Control:
  POST   /api/vehicle/arm
  POST   /api/vehicle/takeoff
  POST   /api/vehicle/land
  POST   /api/vehicle/goto
  POST   /api/vehicle/mode
  GET    /api/vehicle/status

Mission Management:
  POST   /api/mission/add-waypoint
  GET    /api/mission/waypoints
  POST   /api/mission/start/pause/resume/abort
  GET    /api/mission/stats

Navigation:
  GET    /api/navigation/config
  POST   /api/navigation/config
  POST   /api/navigation/apply

Payloads:
  POST   /api/payload/control
  GET    /api/payload/status

Telemetry:
  GET    /api/telemetry/current
  GET    /api/telemetry/history
  GET    /api/telemetry/stats
  WS     /ws/telemetry

Field:
  POST   /api/field-boundaries
  GET    /api/field-boundaries

Health:
  GET    /health
```

**Request/Response Format**:
```json
// Success Response
{
  "status": "success",
  "message": "Vehicle armed",
  "data": {...}
}

// Error Response
{
  "status": "error",
  "message": "Failed to arm",
  "data": null
}
```

### 6. Main Application (`main.py`)

**Responsibilities**:
- Initialize all subsystems
- Start API server
- Handle graceful shutdown
- Cleanup resources

**Startup Sequence**:
1. Load configuration from `.env`
2. Initialize MAVLink connection manager
3. Verify Pixhawk connection
4. Start mission planner
5. Initialize payload controller
6. Start telemetry collector
7. Launch FastAPI server

## Data Flow Diagrams

### ARM Sequence
```
Ground Station         API Server              Connection Mgr         Pixhawk
    │                     │                         │                   │
    ├─ POST /arm ────────>│                         │                   │
    │                     ├─ arm() ───────────────>│                   │
    │                     │                         ├─ vehicle.armed ──>│
    │                     │                         │<─ ACK ────────────┤
    │                     │                         │ poll for 100ms    │
    │                     │<─ return True ─────────┤                   │
    │                     ├─ trigger_callback ────>│                   │
    │<─ 200 OK (success)──┤                         │                   │
    │                     │                         │                   │
```

### Telemetry Stream
```
Pixhawk              Connection Mgr          Telemetry Mgr         WebSocket Client
   │                     │                       │                      │
   ├─ MAVLink data ────> │                       │                      │
   │                     ├─ get_vehicle_state()  │                      │
   │                     │                       ├─ collect loop        │
   │                     │                       │<─ vehicle_state ─┐   │
   │                     │                       ├─ add_point()     │   │
   │                     │                       ├─ trigger callback    │
   │                     │                       ├─ broadcast() ────┬─>│
   │                     │                       │                  │   │
   │                     │                  (repeats every 0.5s)    │   │
   │                     │                       │                  │   │
```

### Mission Execution
```
Ground Station         API Server           Mission Planner      Connection Mgr       Pixhawk
    │                     │                      │                    │                  │
    ├─ POST /start ──────>│                      │                    │                  │
    │                     ├─ start_mission() ──>│                    │                  │
    │                     │                      ├─ is_executing=true │                  │
    │                     │                      ├─ current_idx=0     │                  │
    │<─ 200 OK ───────────┤                      │                    │                  │
    │                     │                      │                    │                  │
    │ (external loop polls mission)              │                    │                  │
    ├─ GET /waypoints ───>│                      │                    │                  │
    │<─ mission items ────┤                      │                    │                  │
    │                     │                      │                    │                  │
    ├─ POST /goto ──────> │                      │                    │                  │
    │                     ├─ goto_location() ──────────────────────> │ MAVLink cmd ───>│
    │                     │                      │                    │<─ ACK ────────┤
    │<─ 200 OK ───────────┤                      │                    │                  │
    │                     │                      │                    │                  │
    │ (repeat for each waypoint)                 │                    │                  │
    │                     │                      │                    │                  │
```

## Configuration Management

Environment variables in `.env`:

```
[MAVLink]
MAVLINK_PORT=/dev/serial0        # Serial port or UDP config
MAVLINK_BAUDRATE=57600
MAVLINK_TIMEOUT=30

[API]
API_HOST=0.0.0.0
API_PORT=8000

[Hardware]
SPRAY_PUMP_PIN=17
FLOW_SENSOR_PIN=27
CAMERA_ENABLED=True

[Mission]
MAX_WAYPOINTS=100
DEFAULT_AIRSPEED=5
OBSTACLE_AVOIDANCE_ENABLED=False
OBSTACLE_AVOIDANCE_MODE=simple
TERRAIN_FOLLOWING_ENABLED=False
TERRAIN_SENSOR_SOURCE=rangefinder
TERRAIN_TARGET_AGL_METERS=

[Telemetry]
TELEMETRY_UPDATE_INTERVAL=0.5
TELEMETRY_HISTORY_SIZE=3600

[Audit]
AUDIT_LOG_FILE=/var/lib/drone-companion/audit/events.jsonl
AUDIT_LOG_MAX_BYTES=5242880
AUDIT_LOG_BACKUP_COUNT=5
```

Configuration is loaded into a `Config` singleton at startup.

The audit logger writes JSONL events and rotates the active file once it grows
past `AUDIT_LOG_MAX_BYTES`, keeping up to `AUDIT_LOG_BACKUP_COUNT` rotated
files alongside it. That keeps long-running missions from accumulating an
unbounded command log on the Pi.

## Threading Model

```
main.py (Main Thread)
├─ FastAPI Server (Uvicorn + async)
│  ├─ Request handlers (async)
│  └─ WebSocket handlers (async)
│
├─ Connection Manager
│  └─ _monitor_connection() (Background Thread)
│     └─ Health checks every 5s
│
└─ Telemetry Manager
   └─ Collector._collect_loop() (Background Thread)
      └─ Update every 0.5s
      └─ Callbacks to WebSocket broadcast
```

Synchronization:
- Threading locks used in telemetry/payload for state safety
- FastAPI handles request concurrency
- Queue-like subscription model for WebSocket clients

## Error Handling

**Connection Failures**:
- Automatic reconnection attempts
- Callback notifications to clients
- Graceful degradation

**API Errors**:
- Pydantic validation for requests
- HTTP status codes (200, 400, 500)
- Detailed error messages in response

**Payload Issues**:
- GPIO exceptions caught and logged
- Status field indicates error state
- Can disable failed components

## Security Considerations

1. **Serial Port**: Direct connection, no authentication needed
2. **API**: CORS enabled for all origins (can restrict)
3. **Network**: Firewall should restrict port 8000 to trusted subnets
4. **Credentials**: No user auth system (designed for field-only use)

For production:
- Add API authentication (JWT tokens)
- Restrict CORS origins
- Use encrypted connections (HTTPS/WSS)
- Implement rate limiting
