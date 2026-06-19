# Agricultural Drone Companion Computer

Python application for Raspberry Pi 4 connected to Pixhawk 4 flight controller.

## Features

- **MAVLink Communication**: Full MAVLink v2 protocol support for drone control
- **Mission Planning**: Waypoint-based missions with field boundaries and survey grids
- **Live Telemetry**: Real-time vehicle state, GPS, battery, and attitude data
- **Telemetry Archiving**: SQLite time-series storage with automatic rotation and compact history queries
- **Navigation Safety**: Configurable obstacle avoidance and terrain-following support
- **Companion Safety**: Altitude geofencing, no-fly zones, emergency landing zones, and progressive failsafes
- **Payload Control**: Spray pump, camera (photo/video), flow sensor
- **Weather Briefing**: METAR/TAF pre-flight checks with configurable go/no-go thresholds
- **Edge AI Pilot**: Optional camera-based obstacle detection with Coral TPU or YOLO backends
- **Prescription Control**: GPS-synchronized variable-rate application from prescription maps
- **RTK/PPK Workflows**: Base-station calibration and post-processing support
- **Farm Integration**: ISOXML, agLeader exports, and automated reporting
- **Swarm Coordination**: Leader-follower, coverage partitioning, and peer collision avoidance
- **Mapping**: Photogrammetry, EXIF geotagging, NDVI, orthomosaic previews, SQLite-backed GeoTIFF overlay uploads, point-cloud scan planning
- **REST API**: Complete RESTful interface for ground station integration
- **WebSocket Streaming**: Live telemetry streaming to multiple clients
- **Multi-transport**: Supports Serial, UDP, and TCP MAVLink connections

## Hardware Requirements

- Raspberry Pi 4 (4GB+ RAM recommended)
- Pixhawk 4 flight controller
- Spray pump with relay (GPIO controlled)
- USB camera or Pi Camera Module
- Flow meter sensor
- 5V power supply for Pi

## Installation

### 1. Clone the repository
```bash
git clone <repository-url>
cd raspberry_pi_companion
```

### 2. Run setup script
```bash
chmod +x setup.sh
./setup.sh
```

### 3. Configure environment
```bash
cp .env.example .env
nano .env
```

Key configuration options:
- `MAVLINK_PORT`: Serial port for Pixhawk (e.g. `/dev/serial0` for Pi pins 32/33)
- `API_HOST`/`API_PORT`: API server address (default: `0.0.0.0:8000`)
- `API_KEY`: Shared API key required by protected REST and WebSocket endpoints
- `CORS_ORIGINS`: Comma-separated browser origins allowed to call the API
- `SPRAY_PUMP_PIN`, `FLOW_SENSOR_PIN`: GPIO pins for hardware
- `OBSTACLE_AVOIDANCE_*`: ArduPilot avoidance defaults plus live sensor source
- `OBSTACLE_AVOIDANCE_SENSOR_*`: Obstacle sensor source, 360-mode, Pixhawk ID, GPIO, and ROS hooks
- `TERRAIN_*`: Terrain following source, AGL limits, waypoint/RTL behavior, and ROS/MAVROS hooks
- `SURVEY_*`: Photogrammetry overlap, altitude, heading, and terrain-adjustment defaults
- `CAMERA_*`: Camera sensor geometry used for GSD and trigger timing calculations
- `NDVI_*`: Band selection and feature toggles for vegetation monitoring
- `WEATHER_*`: METAR/TAF station, fetch templates, and pre-flight thresholds
- `EDGE_AI_*`: Optional Coral/YOLO obstacle-detection backend, model paths, and label keywords
- `GEOTIFF_DATABASE_FILE`: SQLite catalog for uploaded GeoTIFF overlays
- `GEOTIFF_ASSET_DIRECTORY`: Storage path for uploaded GeoTIFF rasters and previews
- `SWARM_DATABASE_FILE`: SQLite store for swarm config, peer telemetry, alerts, and fusion state
- `SWARM_DATABASE_MAX_BYTES`: Rotate the swarm database once it reaches this size
- `AUDIT_LOG_FILE`: JSONL audit log path, usually under `/var/lib/drone-companion/audit/`
- `AUDIT_LOG_MAX_BYTES`: Rotate the audit log once it reaches this many bytes
- `AUDIT_LOG_BACKUP_COUNT`: How many rotated audit files to keep
- `TELEMETRY_DATABASE_FILE`: SQLite database for telemetry history, usually under `/var/lib/drone-companion/telemetry/`
- `TELEMETRY_DATABASE_MAX_BYTES`: Rotate telemetry storage when the database exceeds this many bytes
- `FLIGHT_LOG_DIRECTORY`: Post-flight Pixhawk and companion log archive directory
- `FLIGHT_LOG_CLOUD_UPLOAD_ENABLED`: Enable HTTP upload of the post-flight archive bundle
- `FLIGHT_LOG_CLOUD_UPLOAD_URL`: Upload endpoint for the archive bundle
- `SAFETY_STATE_FILE`: Companion-side geofence, Remote ID, and waiver state
- `ALTITUDE_HARD_*` and `ALTITUDE_SOFT_*`: Companion-enforced altitude limits
- `LOW_BATTERY_*` / `GPS_LOSS_*` / `LOST_LINK_*`: Progressive emergency thresholds
- `REMOTE_ID_*`: Remote ID broadcast metadata surfaced in the API
- `PART107_*`: Night flight and BVLOS waiver metadata
- `CAMERA_TRIGGER_PULSE_MS`: Camera trigger pulse duration in milliseconds; fractional values are allowed
- `LOG_LEVEL`: Logging verbosity (INFO, DEBUG, WARNING, ERROR)

Obstacle avoidance sensor options:
- `OBSTACLE_AVOIDANCE_SENSOR_SOURCE=mavlink`: read live Pixhawk `DISTANCE_SENSOR` data
- `OBSTACLE_AVOIDANCE_SENSOR_SOURCE=gpio`: read a local Raspberry Pi GPIO input
- `OBSTACLE_AVOIDANCE_SENSOR_SOURCE=ros`: subscribe to a ROS topic
- `OBSTACLE_AVOIDANCE_SENSOR_COVERAGE_MODE=forward`: treat the sensor as a forward-facing obstacle detector
- `OBSTACLE_AVOIDANCE_SENSOR_COVERAGE_MODE=360`: treat the sensor as a 360-degree sensor for ROS/UI logic
- `OBSTACLE_AVOIDANCE_SENSOR_MAVLINK_ID=1`: default Pixhawk sensor ID for obstacle avoidance

Terrain ROS hooks:
- `TERRAIN_ROS_BRIDGE_ENABLED=True` enables terrain bridge metadata in the API
- `TERRAIN_ROS_BACKEND=mavros` keeps the terrain hooks compatible with MAVROS
- `TERRAIN_MAVROS_TOPIC` and `TERRAIN_ROS_TOPIC` let you document the ROS/MAVROS topic names you plan to use

### 4. Test the connection
```bash
source venv/bin/activate
python main.py
```

The companion exposes the live API that the ground station uses at runtime,
including weather, obstacle-scan, swarm, calibration, and farm integration
state.

## Docker

Build the companion image from the repository root:

```bash
docker build -f raspberry_pi_companion/Dockerfile -t raspberry-pi-companion .
```

Run it with the Pi devices and network access you need:

```bash
docker run --rm -it \
  --network host \
  --device=/dev/serial0 \
  --device=/dev/gpiomem \
  -v /var/lib/drone-companion:/var/lib/drone-companion \
  raspberry-pi-companion
```

The companion image keeps the hardware-specific packages optional on non-Pi
systems so CI can build the same Dockerfile without GPIO or SPI hardware.

To run the companion with Docker Compose on the Pi:

```bash
docker compose --profile companion up -d
```

That profile uses the companion defaults unless you export overrides in your
shell or create a root-level `.env` file for Compose variable substitution.

## API Documentation

Interactive Swagger documentation is available at:

```
http://<raspberry-pi-ip>:8000/docs
```

Click **Authorize** and enter the configured `API_KEY`. Protected REST endpoints
also accept the key in the `x-api-key` header. The telemetry WebSocket accepts
either an `x-api-key` header or an `api_key` query parameter.

Flight-control and mission-editing commands also require a command authority
lease. Acquire one with `POST /api/v1/control/authority`, then send the returned
token in the `x-control-token` header for protected command requests.

GeoTIFF overlays can be uploaded with `POST /api/v1/mapping/geotiff/upload`
using a TIFF payload and bounding-box query parameters. The companion stores
metadata in SQLite, keeps the raster and preview on disk, and exposes the
preview at `GET /api/v1/mapping/geotiff/{asset_id}/preview`.

### Health Check
```
GET /health
```

### Command Authority
```
GET    /api/v1/control/authority       - Get current authority lease status
POST   /api/v1/control/authority       - Acquire command authority
POST   /api/v1/control/authority/renew - Renew command authority
DELETE /api/v1/control/authority       - Release command authority
```

### Vehicle Control
```
POST /api/v1/vehicle/arm              - Arm/disarm drone
POST /api/v1/vehicle/takeoff          - Takeoff to altitude
POST /api/v1/vehicle/land             - Land drone
POST /api/v1/vehicle/goto             - Fly to GPS location
POST /api/v1/vehicle/mode             - Change flight mode
GET  /api/v1/vehicle/status           - Get vehicle state
GET  /api/v1/vehicle/prearm           - Get pre-arm readiness and messages
```

### Mission Planning
```
POST /api/v1/mission/add-waypoint     - Add waypoint
GET  /api/v1/mission/waypoints        - Get mission waypoints
POST /api/v1/mission/start            - Start mission
POST /api/v1/mission/pause            - Pause mission
POST /api/v1/mission/resume           - Resume mission
POST /api/v1/mission/abort            - Abort mission
POST /api/v1/mission/clear            - Clear mission
GET  /api/v1/mission/stats            - Get mission statistics

POST /api/v1/field-boundaries         - Add field boundary polygon
GET  /api/v1/field-boundaries         - Get all field boundaries
```

Mapping workflows build on the same mission boundaries:

- Survey grids use camera sensor geometry, front/side overlap, and flight speed to derive spacing and trigger timing.
- Target GSD can be converted into an optimal altitude above ground level.
- Terrain-aware surveys can adjust waypoint altitude per position when terrain data is available.
- Geotagged captures can be exported to CSV or written into EXIF GPS tags for photogrammetry tools.
- NDVI support expects a camera or filter setup with usable red and NIR bands.
- Orthomosaic previews are intended as low-resolution in-flight mosaics before full-resolution cloud processing.
- Point-cloud workflows can reuse the same field boundary while adding orbit or tiered scan passes.

### Mapping
```
POST /api/v1/mapping/survey-grid         - Generate a photogrammetry survey plan
POST /api/v1/mapping/geotag/export       - Export geotag CSV from supplied records or a photo session
POST /api/v1/mapping/geotag/exif         - Write EXIF GPS tags into session images
POST /api/v1/mapping/ndvi/preview        - Generate an NDVI false-color preview PNG
POST /api/v1/mapping/orthomosaic/preview - Generate a low-res orthomosaic preview PNG
POST /api/v1/mapping/geotiff/upload      - Store a GeoTIFF and generate a PNG preview
GET  /api/v1/mapping/geotiff             - List stored GeoTIFF overlays
GET  /api/v1/mapping/geotiff/{asset_id}  - Get GeoTIFF overlay metadata
GET  /api/v1/mapping/geotiff/{asset_id}/preview - Fetch the stored preview PNG
DELETE /api/v1/mapping/geotiff/{asset_id} - Delete a stored GeoTIFF overlay
POST /api/v1/mapping/point-cloud/scan    - Generate a 3D scan waypoint plan
```

### Navigation Safety
```
GET  /api/v1/navigation/config        - Get avoidance/terrain config and Pixhawk status
POST /api/v1/navigation/config        - Update companion navigation config
POST /api/v1/navigation/apply         - Apply saved navigation config to Pixhawk params
GET  /api/v1/navigation/sensors       - Get live obstacle/terrain sensor data
```

### Weather
```
POST /api/v1/weather/briefing         - Build a METAR/TAF briefing from supplied or fetched reports
GET  /api/v1/weather/status           - Get the current weather integration status
```

### Vision
```
POST /api/v1/vision/obstacles/scan    - Run an obstacle scan against the latest camera frame
GET  /api/v1/vision/obstacles/status   - Get edge AI detector status
```

### Safety and Compliance
```
GET    /api/safety/status                 - Companion safety evaluation and geofence state
GET    /api/safety/checklist              - Preflight safety checklist
GET    /api/safety/geofences              - List geofence/no-fly/landing zones
POST   /api/safety/geofences              - Add or update a geofence zone
DELETE /api/safety/geofences/{name}       - Remove a geofence zone
GET    /api/safety/emergency-landing-zones - Identify the best landing zone
GET    /api/compliance/remote-id          - Get Remote ID configuration
PUT    /api/compliance/remote-id          - Update Remote ID configuration
GET    /api/compliance/waivers            - Get Part 107 waiver metadata
PUT    /api/compliance/waivers            - Update waiver metadata
GET    /api/arming/checks                 - Pre-arm plus companion safety checks
POST   /api/arming/motor-test             - Prepare motor test / ESC calibration procedure
```

When terrain following is enabled, new mission waypoints default to the
`terrain` altitude frame unless a waypoint explicitly sets `altitude_frame` to
`relative`.

Terrain following stays on the Pixhawk and still reads live MAVLink rangefinder
data. The current mapping is:

- `RNGFND1` / `DISTANCE_SENSOR id=0`: terrain following
- `RNGFND2` / `DISTANCE_SENSOR id=1`: obstacle avoidance by default

Obstacle avoidance can be sourced from Pixhawk MAVLink, a GPIO pin, or ROS
hooks depending on config. The companion app reads and reports the live sensor
data, but it does not replace ArduPilot's flight-critical avoidance logic.

ROS/MAVROS terrain hooks are exposed in config so the terrain workflow can be
integrated with a ROS stack later without changing the Pixhawk-side defaults.

Example `.env` setup:
```env
AUDIT_LOG_FILE=/var/lib/drone-companion/audit/events.jsonl
AUDIT_LOG_MAX_BYTES=5242880
AUDIT_LOG_BACKUP_COUNT=5
OBSTACLE_AVOIDANCE_SENSOR_SOURCE=mavlink
OBSTACLE_AVOIDANCE_SENSOR_COVERAGE_MODE=forward
OBSTACLE_AVOIDANCE_SENSOR_MAVLINK_ID=1
OBSTACLE_AVOIDANCE_SENSOR_ROS_ENABLED=False
TERRAIN_ROS_BRIDGE_ENABLED=True
TERRAIN_ROS_BACKEND=mavros
TERRAIN_MAVROS_TOPIC=/mavros/distance_sensor/hrlv_ez4_pub
TERRAIN_ROS_TOPIC=/terrain/range
```

If you use pressure or tank sensors with `SOURCE=adc`, install `spidev`.
The MCP3008 ADC reader depends on it.

### Payload Control
```
POST /api/v1/payload/control          - Control spray, camera
GET  /api/v1/payload/status           - Get payload status
```

Photo captures are stored under the configured `PHOTO_DIRECTORY`, grouped by
session when one is provided. Video recordings now use a session-scoped path
under `PHOTO_DIRECTORY/videos/`, so each recording gets its own file instead of
overwriting `/tmp/video.mp4`.

### Telemetry
```
GET  /api/v1/telemetry/current        - Current vehicle state
GET  /api/v1/telemetry/history        - Telemetry history
GET  /api/v1/telemetry/stats          - Statistics
WS   /ws/telemetry                 - WebSocket live stream
```

Telemetry history is now backed by SQLite instead of an in-memory ring buffer,
which makes long-range analysis and post-flight review much easier.

### Spray Records
```
GET  /api/payload/spray/sessions/{session}/geojson            - Export field boundary and flight path as GeoJSON
POST /api/payload/spray/sessions/{session}/compliance-report  - Generate a signed compliance report
```

## Systemd Service

To run as a systemd service:

```bash
chmod +x install_service.sh
sudo ./install_service.sh
```

The installer copies the app to `/opt/drone-companion`, creates the
`drone-companion` service user, prepares `/var/lib/drone-companion`, and starts
the service.

Check status:
```bash
sudo systemctl status drone-companion
```

View logs:
```bash
sudo journalctl -u drone-companion -f
```

## Ground Station Integration

The API is designed for consumption by web-based ground stations:

### Python Client Example
```python
import requests
import websockets
import json

BASE_URL = 'http://localhost:8000'
API_KEY = 'replace-with-your-api-key'
headers = {'x-api-key': API_KEY}

authority = requests.post(
    f'{BASE_URL}/api/v1/control/authority',
    headers=headers,
    json={'client_id': 'example-client', 'operator': 'pilot'}
).json()
control_headers = {
    **headers,
    'x-control-token': authority['data']['authority']['token'],
}

# Get vehicle status
response = requests.get(f'{BASE_URL}/api/v1/vehicle/status', headers=headers)
status = response.json()

# Add waypoint
requests.post(
    f'{BASE_URL}/api/v1/mission/add-waypoint',
    headers=control_headers,
    json={
        'location': {
            'latitude': 40.7128,
            'longitude': -74.0060,
            'altitude': 50.0
        }
    }
)

# Subscribe to live telemetry
async def telemetry_stream():
    async with websockets.connect(f'ws://localhost:8000/ws/telemetry?api_key={API_KEY}') as ws:
        async for message in ws:
            data = json.loads(message)
            print(f"Battery: {data['battery']['level_percent']}%")
```

### JavaScript Web Example
```javascript
// Get current telemetry
const apiKey = 'replace-with-your-api-key';
const headers = {'Content-Type': 'application/json', 'x-api-key': apiKey};

fetch('/api/v1/telemetry/current', {headers})
  .then(r => r.json())
  .then(data => console.log(data));

const authority = await fetch('/api/v1/control/authority', {
  method: 'POST',
  headers,
  body: JSON.stringify({client_id: 'web-ground-station', operator: 'pilot'})
}).then(r => r.json());
const controlHeaders = {
  ...headers,
  'x-control-token': authority.data.authority.token
};

// Control drone
fetch('/api/v1/vehicle/arm', {
  method: 'POST',
  headers: controlHeaders,
  body: JSON.stringify({armed: true})
});

// Live telemetry via WebSocket
const ws = new WebSocket(`ws://localhost:8000/ws/telemetry?api_key=${apiKey}`);
ws.onmessage = (event) => {
  const telemetry = JSON.parse(event.data);
  console.log('Battery:', telemetry.battery.level_percent + '%');
};
```

## Troubleshooting

### Connection Issues
1. Check serial port: `ls -la /dev/serial0`
2. Verify Pixhawk is powered and connected
3. Check baud rate in `.env` matches Pixhawk config
4. View logs: `tail -f /var/log/drone-companion.log`

### GPIO Issues
- Ensure script runs with sufficient privileges (sudoers or systemd service)
- Verify GPIO pins are correct in `.env`
- Check hardware connections

### API Issues
- Verify API server is running: `lsof -i :8000`
- Check firewall: `sudo ufw status`
- Enable if needed: `sudo ufw allow 8000`

## Development

### Run tests
```bash
pytest tests/
```

### Enable debug mode
```bash
API_DEBUG=True python main.py
```

## References

- [Pixhawk 4 Documentation](https://docs.px4.io/master/en/flight_controller/pixhawk4.html)
- [DroneKit-Python](https://dronekit-python.readthedocs.io/)
- [MAVLink Protocol](https://mavlink.io/)
- [FastAPI](https://fastapi.tiangolo.com/)

## License

Proprietary - Underwood UAV

## Support

For issues and questions, contact support@underwooduav.com
