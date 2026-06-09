# Project Structure

## Overview

Agricultural Drone Software - Raspberry Pi Companion Computer for Pixhawk 4

```
agri_dronesetup/
├── raspberry_pi_companion/          # Main Raspberry Pi application
│   ├── src/                         # Application source code
│   │   ├── config/
│   │   │   └── settings.py         # Configuration management
│   │   ├── mavlink/
│   │   │   └── connection_manager.py  # MAVLink/Pixhawk interface
│   │   ├── missions/
│   │   │   └── planner.py          # Mission planning engine
│   │   ├── payloads/
│   │   │   └── controller.py       # Spray pump, camera, sensors
│   │   ├── telemetry/
│   │   │   └── collector.py        # Telemetry collection & streaming
│   │   ├── api/
│   │   │   └── server.py           # FastAPI REST/WebSocket server
│   │   └── __init__.py
│   ├── tests/
│   │   └── test_mission_planner.py  # Unit tests
│   ├── docs/
│   │   ├── SETUP.md                # Hardware & software setup guide
│   │   ├── ARCHITECTURE.md         # System design documentation
│   │   └── drone-companion.service # Systemd service file
│   ├── main.py                      # Application entry point
│   ├── requirements.txt             # Python dependencies
│   ├── .env.example                 # Configuration template
│   ├── setup.sh                     # Installation script
│   ├── README.md                    # Full documentation
│   ├── QUICKSTART.md               # Quick start guide
│   └── PROJECT_STRUCTURE.md        # This file
│
├── ground_station/                  # Ground station (PC/Tablet)
│   ├── web/                        # React web app (not yet implemented)
│   ├── mobile/                     # React Native mobile app (future)
│   └── docs/                       # Ground station documentation
│
└── docs/                            # Project-level documentation
    ├── HARDWARE_SETUP.md           # Hardware wiring guide
    ├── COMMUNICATION.md            # MAVLink & WiFi protocols
    ├── API_SPECIFICATION.md        # Detailed API reference
    └── DEVELOPMENT.md              # Developer guide
```

## Component Details

### `src/config/settings.py`
**Purpose**: Centralized configuration management via environment variables
**Key Classes**:
- `MAVLinkConfig` - Connection settings
- `APIConfig` - Server settings
- `PayloadConfig` - Hardware pin mappings
- `MissionConfig` - Mission limits/defaults
- `TelemetryConfig` - Data collection settings

### `src/mavlink/connection_manager.py`
**Purpose**: Interface with Pixhawk flight controller
**Key Classes**:
- `ConnectionManager` - Main MAVLink interface
**Methods**:
- `connect()` - Establish connection
- `arm()` / `disarm()` - Arm/disarm vehicle
- `takeoff()` / `land()` - Flight commands
- `set_mode()` - Change flight mode
- `goto_location()` - Autonomous waypoint navigation
- `get_vehicle_state()` - Telemetry query

### `src/missions/planner.py`
**Purpose**: Mission planning and execution tracking
**Key Classes**:
- `GeoPoint` - GPS coordinate
- `MissionItem` - Single waypoint/action
- `FieldBoundary` - Spray zone polygon
- `MissionPlanner` - Mission manager
**Features**:
- Waypoint management
- Spray zone generation
- Mission persistence (save/load)
- Execution tracking

### `src/payloads/controller.py`
**Purpose**: Hardware control (spray pump, camera, sensors)
**Key Classes**:
- `SprayPump` - GPIO relay control
- `FlowSensor` - Pulse-based flow meter
- `CameraController` - Photo/video capture
- `PayloadController` - Master controller
**Tracking**:
- Spray time and volume
- Photo/video count and duration

### `src/telemetry/collector.py`
**Purpose**: Continuous telemetry collection and streaming
**Key Classes**:
- `TelemetryPoint` - Single timestamped reading
- `TelemetryCollector` - Background collection loop
- `LiveTelemetryStream` - WebSocket broadcast
- `TelemetryManager` - High-level interface
**Features**:
- 3600-point circular buffer (configurable)
- Real-time WebSocket streaming
- Historical data queries
- Statistics computation

### `src/api/server.py`
**Purpose**: REST API and WebSocket server
**Technology**: FastAPI + Uvicorn
**Endpoints**:
- Vehicle control (arm, takeoff, land, goto)
- Mission management (waypoints, execution)
- Payload control (spray, camera)
- Telemetry queries and streams
- Field boundary management

### `main.py`
**Purpose**: Application entry point
**Workflow**:
1. Load configuration
2. Initialize all subsystems
3. Connect to Pixhawk
4. Start API server
5. Handle graceful shutdown

## Dependencies

### Core Libraries
- `dronekit` (2.9.2) - MAVLink interface
- `pymavlink` (2.4.45) - MAVLink protocol
- `fastapi` (0.104.1) - Web API framework
- `uvicorn` (0.24.0) - ASGI server

### Hardware
- `RPi.GPIO` (0.7.0) - Raspberry Pi GPIO control
- `opencv-python` (4.8.1.78) - Camera/image processing
- `pyserial` (3.5) - Serial communication

### Utilities
- `pydantic` (2.5.0) - Data validation
- `python-dotenv` (1.0.0) - Environment management
- `websockets` (12.0) - WebSocket support

See `requirements.txt` for complete list.

## Configuration

Environment variables in `.env`:

```ini
# MAVLink Connection
MAVLINK_PORT=/dev/ttyAMA0              # Serial port
MAVLINK_BAUDRATE=57600                 # Baud rate
MAVLINK_TIMEOUT=30                     # Connection timeout (sec)

# API Server
API_HOST=0.0.0.0                       # Listen address
API_PORT=8000                          # Listen port
API_DEBUG=False                        # Debug mode

# Hardware GPIO Pins
SPRAY_PUMP_PIN=17                      # Relay signal pin
FLOW_SENSOR_PIN=27                     # Pulse counter pin
CAMERA_ENABLED=True
FLOW_SENSOR_ENABLED=True

# Mission Limits
MAX_WAYPOINTS=100
MIN_ALTITUDE=5                         # Minimum safe altitude (m)
MAX_ALTITUDE=120                       # Legal limit (m)
DEFAULT_AIRSPEED=5                     # m/s

# Telemetry
TELEMETRY_UPDATE_INTERVAL=0.5          # Collection rate (sec)
TELEMETRY_HISTORY_SIZE=3600            # Max data points
GPS_TIMEOUT=10                         # GPS watchdog (sec)

# Logging
LOG_LEVEL=INFO                         # DEBUG, INFO, WARNING, ERROR
ENVIRONMENT=production
```

## Data Models

### GeoPoint
```python
GeoPoint(
    latitude: float,
    longitude: float,
    altitude: float = 0.0
)
```

### MissionItem
```python
MissionItem(
    sequence: int,
    type: MissionItemType,      # WAYPOINT, LOITER, SPRAY_START, etc.
    location: GeoPoint,
    param1-4: float             # Item-specific parameters
)
```

### FieldBoundary
```python
FieldBoundary(
    name: str,
    vertices: List[GeoPoint],   # Polygon boundary
    altitude: float = 0.0
)
```

## API Response Format

### Success
```json
{
  "status": "success",
  "message": "Action completed",
  "data": {...}
}
```

### Error
```json
{
  "status": "error",
  "message": "Error description",
  "data": null
}
```

## File Organization

```
Configuration & Setup
├── .env.example                    Configuration template
├── requirements.txt                Dependencies
├── setup.sh                        Installation script
└── docs/

Documentation
├── README.md                       Full documentation
├── QUICKSTART.md                  Quick start
├── docs/SETUP.md                  Detailed setup
├── docs/ARCHITECTURE.md           Design details
└── docs/drone-companion.service   Systemd service

Source Code
├── src/
│   ├── config/settings.py
│   ├── mavlink/connection_manager.py
│   ├── missions/planner.py
│   ├── payloads/controller.py
│   ├── telemetry/collector.py
│   ├── api/server.py
│   └── __init__.py files

Tests & Utilities
├── tests/
│   └── test_mission_planner.py
└── main.py                        Entry point
```

## Development Workflow

### 1. Setup Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env for your hardware
```

### 3. Run Application
```bash
python main.py
```

### 4. Run Tests
```bash
pytest tests/
```

### 5. Access API
```bash
curl http://localhost:8000/health
```

## Adding New Features

### 1. New Payload Type
Create in `src/payloads/controller.py`:
```python
class MyPayload:
    def __init__(self, config):
        # Initialize hardware
        pass
    
    def activate(self):
        # Control logic
        pass
    
    def get_status(self):
        # Return state dict
        return {}
```

Add to `PayloadController` and API endpoints in `src/api/server.py`.

### 2. New API Endpoint
Add to `src/api/server.py`:
```python
@self.app.post("/api/new-feature")
async def new_feature(request: NewFeatureRequest):
    try:
        # Implementation
        return StatusResponse(status="success", message="Done", data={})
    except Exception as e:
        return StatusResponse(status="error", message=str(e))
```

### 3. New Mission Type
Extend `MissionItemType` enum and add to `MissionPlanner`:
```python
class MissionItemType(Enum):
    NEW_ACTION = "new_action"
```

## Version History

- **v1.0.0** (2024) - Initial release
  - MAVLink interface to Pixhawk 4
  - Mission planning with waypoints
  - Spray pump and camera control
  - REST API and WebSocket telemetry
  - Systemd service support

## License

Proprietary - Underwood UAV

---

**Last Updated**: 2024-01-15
**For Questions**: Support contact information
