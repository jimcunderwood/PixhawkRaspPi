# Quick Start Guide

## 30-Minute Setup

### Prerequisites
- Raspberry Pi 4 with Raspbian/Ubuntu
- Pixhawk 4 connected to Raspberry Pi via serial
- WiFi connectivity

### 1. Clone and Setup (5 minutes)

```bash
# On Raspberry Pi
cd /home/pi
git clone <repository-url>
cd PixhawkRaspPi/raspberry_pi_companion

# Run setup script
chmod +x setup.sh
./setup.sh
```

### 2. Configure (5 minutes)

```bash
# Copy template
cp .env.example .env

# Edit configuration
nano .env

# Minimal required changes:
# MAVLINK_PORT=/dev/serial0
# API_HOST=0.0.0.0
# API_KEY=<long random token>
# SPRAY_PUMP_PIN=17 (or your GPIO pin)
```

### 3. Test Connection (5 minutes)

```bash
source venv/bin/activate
python main.py
```

Wait for output:
```
INFO - Successfully connected to Pixhawk
INFO - ✓ Initialization complete
INFO - Starting API server on 0.0.0.0:8000...
```

### 4. Verify API (5 minutes)

From another terminal or your PC:

```bash
# Health check
curl http://<raspberry-pi-ip>:8000/health

# Get vehicle status
curl -H "x-api-key: <your-api-key>" \
  http://<raspberry-pi-ip>:8000/api/vehicle/status

# Get pre-arm readiness
curl -H "x-api-key: <your-api-key>" \
  http://<raspberry-pi-ip>:8000/api/vehicle/prearm

# Add test waypoint
curl -X POST http://<raspberry-pi-ip>:8000/api/mission/add-waypoint \
  -H "Content-Type: application/json" \
  -H "x-api-key: <your-api-key>" \
  -d '{"latitude": 40.7128, "longitude": -74.0060, "altitude": 50}'
```

Swagger API docs are available at `http://<raspberry-pi-ip>:8000/docs`.
Use the **Authorize** button and enter your `API_KEY`.

### 5. Run as Service (Optional)

```bash
sudo cp docs/drone-companion.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable drone-companion
sudo systemctl start drone-companion
```

## Basic Operations

### Arm the Drone
```python
import requests

requests.post('http://localhost:8000/api/vehicle/arm', 
              headers={'x-api-key': '<your-api-key>'},
              json={'arm': True})
```

### Takeoff
```python
requests.post('http://localhost:8000/api/vehicle/takeoff',
              headers={'x-api-key': '<your-api-key>'},
              json={'altitude': 30.0})  # 30 meters
```

### Create Mission
```python
# Add waypoints
for i in range(5):
    requests.post('http://localhost:8000/api/mission/add-waypoint',
                  headers={'x-api-key': '<your-api-key>'},
                  json={
                    'latitude': 40.7128 + i*0.001,
                    'longitude': -74.0060 + i*0.001,
                    'altitude': 50.0
                  })

# Start mission
requests.post('http://localhost:8000/api/mission/start',
              headers={'x-api-key': '<your-api-key>'})
```

### Control Spray
```python
# Start spray
requests.post('http://localhost:8000/api/payload/control',
              headers={'x-api-key': '<your-api-key>'},
              json={'action': 'spray_start'})

# Stop spray
requests.post('http://localhost:8000/api/payload/control',
              headers={'x-api-key': '<your-api-key>'},
              json={'action': 'spray_stop'})

# Get status
response = requests.get('http://localhost:8000/api/payload/status',
                        headers={'x-api-key': '<your-api-key>'})
status = response.json()
print(f"Spray time: {status['data']['spray_pump']['total_on_time']} seconds")
```

### Monitor Telemetry
```python
import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    print(f"Alt: {data['location']['alt']}m, "
          f"Battery: {data['battery']['level']}%")

ws = websocket.WebSocketApp(
    "ws://localhost:8000/ws/telemetry?api_key=<your-api-key>",
    on_message=on_message
)
ws.run_forever()
```

## Troubleshooting

### Can't connect to Pixhawk
```bash
# Check serial port
ls -la /dev/serial0

# Test with minicom
minicom -b 57600 -o -D /dev/serial0

# Check UART enabled
dtparam -l | grep uart
```

### API won't start
```bash
# Check port available
lsof -i :8000

# Look at logs
tail -f /var/log/syslog | grep drone
```

### GPIO not responding
```bash
# Add user to groups
sudo usermod -a -G gpio pi

# Reboot
sudo reboot
```

## Next Steps

1. **Ground Station**: Build React web UI (see ground_station/ directory)
2. **Field Testing**: Run test missions in safe area
3. **Spray Testing**: Calibrate flow sensor for accurate volume tracking
4. **Integration**: Connect to existing farm management systems

## Documentation

- [Full Setup Guide](docs/SETUP.md)
- [Architecture Details](docs/ARCHITECTURE.md)
- [API Reference](README.md)

## Support

For issues:
1. Check logs: `sudo journalctl -u drone-companion -f`
2. Enable debug: Set `API_DEBUG=True` in .env
3. Review [Troubleshooting](docs/SETUP.md#troubleshooting) section
