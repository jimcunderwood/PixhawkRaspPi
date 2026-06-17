# Agricultural Drone Companion Computer

Python application for Raspberry Pi 4 connected to Pixhawk 4 flight controller.

## Features

- **MAVLink Communication**: Full MAVLink v2 protocol support for drone control
- **Mission Planning**: Waypoint-based missions with field boundaries
- **Live Telemetry**: Real-time vehicle state, GPS, battery, and attitude data
- **Navigation Safety**: Configurable obstacle avoidance and terrain-following support
- **Payload Control**: Spray pump, camera (photo/video), flow sensor
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
- `OBSTACLE_AVOIDANCE_*`: ArduPilot simple/BendyRuler avoidance defaults
- `TERRAIN_*`: Terrain following source, AGL limits, and waypoint/RTL behavior
- `LOG_LEVEL`: Logging verbosity (INFO, DEBUG, WARNING, ERROR)

### 4. Test the connection
```bash
source venv/bin/activate
python main.py
```

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

### Navigation Safety
```
GET  /api/v1/navigation/config        - Get avoidance/terrain config and Pixhawk status
POST /api/v1/navigation/config        - Update companion navigation config
POST /api/v1/navigation/apply         - Apply saved navigation config to Pixhawk params
```

When terrain following is enabled, new mission waypoints default to the
`terrain` altitude frame unless a waypoint explicitly sets `altitude_frame` to
`relative`.

Pixhawk rangefinders are read live from MAVLink `DISTANCE_SENSOR` messages, not
from Raspberry Pi GPIO pins. The current sensor mapping is:

- `RNGFND1` / `DISTANCE_SENSOR id=0`: terrain following
- `RNGFND2` / `DISTANCE_SENSOR id=1`: obstacle avoidance

Obstacle avoidance still uses ArduPilot's configured proximity or rangefinder
sensors; the companion app reads and reports the live Pixhawk data, but it does
not replace ArduPilot's flight-critical avoidance logic.

### Payload Control
```
POST /api/v1/payload/control          - Control spray, camera
GET  /api/v1/payload/status           - Get payload status
```

### Telemetry
```
GET  /api/v1/telemetry/current        - Current vehicle state
GET  /api/v1/telemetry/history        - Telemetry history
GET  /api/v1/telemetry/stats          - Statistics
WS   /ws/telemetry                 - WebSocket live stream
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
