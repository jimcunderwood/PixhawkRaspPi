# Raspberry Pi 4 Companion Computer - Setup Guide

## Hardware Setup

### Serial Connection to Pixhawk

The Pixhawk 4 connects to the Raspberry Pi via serial (UART):

**Pixhawk TELEM1 to Pi GPIO**:
- Pixhawk Pin 3 (TELEM1 RX) → Pi Pin 32 (GPIO 12, UART1 TX)
- Pixhawk Pin 2 (TELEM1 TX) → Pi Pin 33 (GPIO 13, UART1 RX)
- Pixhawk Pin 6 (GND) → Pi Pin 6 (GND)

**Wiring Details**:
- Use a 5V-to-3.3V level converter if required (Pixhawk runs at 5V)
- Enable UART1 on the Pi when using pins 32/33
- Ensure solid solder joints or quality connectors
- Use twisted pairs to minimize noise

### Payload Hardware

**Spray Pump Control** (GPIO 17):
- GPIO 17 → Relay signal pin
- 5V relay coil power
- Relay NC → Pump ground circuit

**Flow Sensor** (GPIO 27):
- Hall effect sensor pulse output → GPIO 27
- 5V power supply
- Common ground

**USB Camera**:
- Connect USB camera to any USB 3.0 port
- Or use Pi Camera Module on CSI port

## Raspberry Pi Configuration

### 1. Enable UART (Serial)

```bash
sudo raspi-config
# Interface Options → Serial Port
# Would you like a login shell accessible over serial? No
# Would you like the serial port hardware to be enabled? Yes
```

Or run:
```bash
sudo raspi-config nonint do_serial_hw 0
sudo raspi-config nonint do_serial_console 1
```

If you are using Pi pins 32/33 for Pixhawk UART1, also add the following to `/boot/config.txt`:
```ini
enable_uart=1
dtoverlay=uart1
```

### 2. Disable Serial Login

```bash
sudo systemctl stop serial-getty@serial0.service || true
sudo systemctl disable serial-getty@serial0.service || true
```

### 3. Grant GPIO Access

Add user to required groups:
```bash
sudo usermod -a -G dialout,gpio,i2c,spi pi
```

Reboot after changes:
```bash
sudo reboot
```

### 4. Verify Serial Port

```bash
ls -la /dev/serial0
# Should show: crw-rw---- 1 root dialout
```

Test connection:
```bash
cat /dev/serial0  # Should show telemetry data from Pixhawk
```

## Software Installation

### 1. Install Dependencies

The setup script installs both Python dependencies and the `ripgrep` system
tool used for fast repository searches.

```bash
cd ~/PixhawkRaspPi/raspberry_pi_companion
chmod +x setup.sh
./setup.sh
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env
```

Edit key settings:
- `MAVLINK_PORT=/dev/serial0` (or `/dev/ttyUSB0` if using USB)
- `API_HOST=0.0.0.0` (accessible from network)
- `API_PORT=8000`
- `API_KEY=replace-with-a-long-random-token`
- `API_KEY_ROLES=viewer:viewer-token,operator:operator-token,maintenance:maintenance-token,admin:admin-token`
- `AUDIT_LOG_FILE=/var/lib/drone-companion/audit/events.jsonl`
- `AUDIT_LOG_MAX_BYTES=5242880` if you want smaller audit chunks on the Pi
- `AUDIT_LOG_BACKUP_COUNT=5` to keep a handful of rotated logs
- `IDEMPOTENCY_TTL_SECONDS=300`
- `CONFIG_DATABASE_FILE=/var/lib/drone-companion/config/profiles.sqlite3`
- Hardware pins match your wiring

API keys can be assigned one of four roles:
`viewer` for read-only dashboards, `operator` for vehicle and payload commands,
`maintenance` for configuration/audit workflows, and `admin` for full access.

### 3. Test Connection

```bash
source venv/bin/activate
python main.py
```

Expected output:
```
2024-01-15 10:30:45,123 - root - INFO - Initializing Agricultural Drone Companion Computer...
2024-01-15 10:30:45,234 - root - INFO - Initializing MAVLink connection...
2024-01-15 10:30:46,456 - root - INFO - Successfully connected to Pixhawk
2024-01-15 10:30:46,789 - root - INFO - ✓ Initialization complete
```

## Networking Setup

### WiFi Configuration

If using WiFi hotspot from ground station:

```bash
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
```

Add:
```
network={
    ssid="DroneFieldAP"
    psk="passwordhere"
    key_mgmt=WPA-PSK
}
```

### Static IP (Recommended)

```bash
sudo nano /etc/dhcpcd.conf
```

Add at end:
```
interface wlan0
static ip_address=192.168.4.10/24
static routers=192.168.4.1
static domain_name_servers=8.8.8.8 8.8.4.4
```

### Firewall Configuration

Allow API access:
```bash
sudo ufw allow 8000/tcp
sudo ufw allow 8000/udp
```

The ground station reads the companion URL at runtime, so once the companion
is reachable on the network you only need to update `COMPANION_BASE_URL` on
the operator machine or in the web UI Docker env file.

## Running as Service

### 1. Install and Enable Systemd Service

```bash
chmod +x install_service.sh
sudo ./install_service.sh
```

The installer copies the app to `/opt/drone-companion`, creates the
`drone-companion` service user, prepares `/var/lib/drone-companion`, writes
`/etc/systemd/system/drone-companion.service`, enables it for reboot, and starts
it now.

### 2. Verify Service

```bash
sudo systemctl status drone-companion
sudo journalctl -u drone-companion -f  # Follow logs
```

## Testing

### 1. API Health Check

```bash
curl http://localhost:8000/health
```

Response:
```json
{"status":"ok","connected":true}
```

### 2. Get Vehicle Status

```bash
export DRONE_API_KEY="replace-with-your-api-key"

curl -H "x-api-key: $DRONE_API_KEY" \
  http://localhost:8000/api/v1/vehicle/status
```

### 3. Acquire Command Authority

Mission edits and vehicle commands require both `x-api-key` and
`x-control-token`. Acquire a short-lived command authority token before sending
those requests. UI retries should also send an `Idempotency-Key` or
`X-Idempotency-Key` header on mutating command requests so repeated submissions
return the original response instead of executing again:

```bash
CONTROL_TOKEN=$(
  curl -s -X POST http://localhost:8000/api/v1/control/authority \
    -H "Content-Type: application/json" \
    -H "x-api-key: $DRONE_API_KEY" \
    -d '{"client_id":"setup-test","operator":"field-tech"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["authority"]["token"])'
)
```

### 4. Add Waypoint

```bash
curl -X POST http://localhost:8000/api/v1/mission/add-waypoint \
  -H "Content-Type: application/json" \
  -H "x-api-key: $DRONE_API_KEY" \
  -H "x-control-token: $CONTROL_TOKEN" \
  -H "Idempotency-Key: add-waypoint-001" \
  -d '{
    "location": {
      "latitude": 40.7128,
      "longitude": -74.0060,
      "altitude": 50.0
    }
  }'
```

For the ground station install flow on Linux, macOS, Windows, and Docker, see
[ground_station/docs/INSTALLATION.md](../../ground_station/docs/INSTALLATION.md).

### 5. Update Calibration Values

Calibration updates require an API key, command authority token, and an
idempotency key. Changes are applied to the running companion process and
recorded in the audit log as `config.calibration_update`.

```bash
curl -X PATCH http://localhost:8000/api/v1/config/calibration \
  -H "Content-Type: application/json" \
  -H "x-api-key: $DRONE_API_KEY" \
  -H "x-control-token: $CONTROL_TOKEN" \
  -H "Idempotency-Key: calibration-001" \
  -d '{
    "flow_sensor": {"pulses_per_liter": 500},
    "pressure_sensor": {"min_voltage": 0.5, "max_voltage": 4.5},
    "tank_level_sensor": {"capacity_liters": 12, "minimum_level_percent": 15},
    "terrain_sensor": {"min_agl_meters": 2, "max_agl_meters": 120}
  }'
```

### 6. Store and Reapply Configuration Profiles

Configuration profiles are stored in SQLite at `CONFIG_DATABASE_FILE`. A profile
captures the current runtime configuration, navigation configuration, and
calibration values so it can be retrieved and reapplied later.

```bash
curl -X POST http://localhost:8000/api/v1/config/profiles \
  -H "Content-Type: application/json" \
  -H "x-api-key: $DRONE_API_KEY" \
  -H "x-control-token: $CONTROL_TOKEN" \
  -H "Idempotency-Key: config-profile-store-001" \
  -d '{"name":"field-baseline","description":"Known-good runtime setup"}'

curl -H "x-api-key: $DRONE_API_KEY" \
  http://localhost:8000/api/v1/config/profiles/field-baseline

curl -X POST http://localhost:8000/api/v1/config/profiles/field-baseline/apply \
  -H "Content-Type: application/json" \
  -H "x-api-key: $DRONE_API_KEY" \
  -H "x-control-token: $CONTROL_TOKEN" \
  -H "Idempotency-Key: config-profile-apply-001" \
  -d '{"apply_to_pixhawk":false}'
```

### 7. WebSocket Telemetry Stream

```bash
# Using wscat or websocat
wscat -c "ws://localhost:8000/ws/telemetry?api_key=$DRONE_API_KEY"
```

### 8. WebSocket Command/Event Stream

```bash
# Emits command.accepted, command.blocked, command.failed, authority,
# emergency, mission, and spray-record events.
wscat -c "ws://localhost:8000/ws/events?api_key=$DRONE_API_KEY"
```

## Troubleshooting

### Serial Connection Issues

**Port not found**:
```bash
dmesg | grep tty  # Check kernel messages
ls /dev/tty*      # List all tty devices
```

**Permission denied**:
```bash
sudo chmod 666 /dev/serial0
# Or better: add user to dialout group and reboot
```

### API Server Won't Start

Check port is not in use:
```bash
lsof -i :8000
# If occupied, kill process or use different port in .env
```

Check logs:
```bash
sudo journalctl -n 50  # Last 50 log lines
```

### Connection to Pixhawk Fails

1. Verify UART enabled:
   ```bash
   sudo dtparam -l | grep uart
   ```

2. Test with Arduino IDE or minicom:
   ```bash
   minicom -b 57600 -o -D /dev/serial0
   ```

3. Check Pixhawk TELEM1 settings in Mission Planner

### PX4 SITL on Raspberry Pi

If you want to run PX4 SITL locally on the Raspberry Pi, use the helper script and local UDP configuration.

```bash
chmod +x install_sitl.sh
./install_sitl.sh
```

Then configure `.env` for local UDP receive:

```bash
MAVLINK_CONNECTION_TYPE=udp
MAVLINK_UDP_DIRECTION=in
MAVLINK_UDP_IP=0.0.0.0
MAVLINK_UDP_PORT=5760
```

Start SITL on the Pi with a PX4 build or package that sends UDP to port `5760`, and then run:

```bash
source venv/bin/activate
python main.py
```

If SITL is on another machine, use remote UDP-out mode instead:

```bash
MAVLINK_CONNECTION_TYPE=udp
MAVLINK_UDP_DIRECTION=out
MAVLINK_UDP_IP=<sitl-host-ip>
MAVLINK_UDP_PORT=5760
```

### GPIO Issues

Check GPIO numbering:
```bash
gpio readall  # Requires gpio utility
```

Verify pins in `.env` match BCM numbering (not BOARD numbering)

## Performance Tuning

### Increase Update Frequency

Edit `.env`:
```
TELEMETRY_UPDATE_INTERVAL=0.2  # More frequent updates
```

Trade-off: Higher CPU usage

### Network Optimization

For WiFi:
- Use 5GHz band if available (less interference)
- Keep antenna clear of obstacles
- Monitor signal: `iwconfig wlan0`

For UDP MAVLink:
```
MAVLINK_UDP_IP=192.168.4.1
MAVLINK_UDP_PORT=14550
```

## Security Considerations

### Disable SSH (Headless Operation)

```bash
sudo systemctl disable ssh
sudo systemctl stop ssh
```

### Firewall Rules

Restrict API access to local network:
```bash
sudo ufw allow from 192.168.4.0/24 to any port 8000
```

### Environment Files

Never commit `.env` with credentials. Keep git safe:
```bash
echo ".env" >> .gitignore
```

## Next Steps

1. Set up ground station (React web app or mobile)
2. Test mission planning with QGroundControl first
3. Run actual field tests with safety protocols
4. Collect flight logs for analysis

For questions, refer to [DroneKit Documentation](https://dronekit-python.readthedocs.io/)
