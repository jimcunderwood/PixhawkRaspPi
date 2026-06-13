# Agricultural Drone Companion Computer

Python application for Raspberry Pi 4 connected to Pixhawk 4 flight controller.

## Features

- **MAVLink Communication**: Full MAVLink v2 protocol support for drone control
- **Mission Planning**: Waypoint-based missions with field boundaries
- **Live Telemetry**: Real-time vehicle state, GPS, battery, and attitude data
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
- `SPRAY_PUMP_PIN`, `FLOW_SENSOR_PIN`: GPIO pins for hardware
- `LOG_LEVEL`: Logging verbosity (INFO, DEBUG, WARNING, ERROR)

### 4. Test the connection
```bash
source venv/bin/activate
python main.py
```

## API Documentation

### Health Check
```
GET /health
```

### Vehicle Control
```
POST /api/vehicle/arm              - Arm/disarm drone
POST /api/vehicle/takeoff          - Takeoff to altitude
POST /api/vehicle/land             - Land drone
POST /api/vehicle/goto             - Fly to GPS location
POST /api/vehicle/mode             - Change flight mode
GET  /api/vehicle/status           - Get vehicle state
```

### Mission Planning
```
POST /api/mission/add-waypoint     - Add waypoint
GET  /api/mission/waypoints        - Get mission waypoints
POST /api/mission/start            - Start mission
POST /api/mission/pause            - Pause mission
POST /api/mission/resume           - Resume mission
POST /api/mission/abort            - Abort mission
POST /api/mission/clear            - Clear mission
GET  /api/mission/stats            - Get mission statistics

POST /api/field-boundaries         - Add field boundary polygon
GET  /api/field-boundaries         - Get all field boundaries
```

### Payload Control
```
POST /api/payload/control          - Control spray, camera
GET  /api/payload/status           - Get payload status
```

### Telemetry
```
GET  /api/telemetry/current        - Current vehicle state
GET  /api/telemetry/history        - Telemetry history
GET  /api/telemetry/stats          - Statistics
WS   /ws/telemetry                 - WebSocket live stream
```

## Systemd Service

To run as a systemd service:

```bash
sudo cp docs/drone-companion.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable drone-companion
sudo systemctl start drone-companion
```

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

# Get vehicle status
response = requests.get('http://localhost:8000/api/vehicle/status')
status = response.json()

# Add waypoint
requests.post('http://localhost:8000/api/mission/add-waypoint', json={
    'latitude': 40.7128,
    'longitude': -74.0060,
    'altitude': 50.0
})

# Subscribe to live telemetry
async def telemetry_stream():
    async with websockets.connect('ws://localhost:8000/ws/telemetry') as ws:
        async for message in ws:
            data = json.loads(message)
            print(f"Battery: {data['battery']['level']}%")
```

### JavaScript Web Example
```javascript
// Get current telemetry
fetch('/api/telemetry/current')
  .then(r => r.json())
  .then(data => console.log(data));

// Control drone
fetch('/api/vehicle/arm', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({arm: true})
});

// Live telemetry via WebSocket
const ws = new WebSocket('ws://localhost:8000/ws/telemetry');
ws.onmessage = (event) => {
  const telemetry = JSON.parse(event.data);
  console.log('Battery:', telemetry.battery.level + '%');
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
