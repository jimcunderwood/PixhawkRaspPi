# Raspberry Pi 4 Companion Computer - Setup Guide

## Hardware Setup

### Serial Connection to Pixhawk

The Pixhawk 4 connects to the Raspberry Pi via serial (UART):

**Pixhawk TELEM1 to Pi GPIO**:
- Pixhawk TELEM1 TX → Pi RX (GPIO 15)
- Pixhawk TELEM1 RX → Pi TX (GPIO 14)
- Pixhawk GND → Pi GND (GPIO 6)

**Wiring Details**:
- Use a 5V-to-3.3V level converter if required (Pixhawk runs at 5V)
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

### 2. Disable Serial Login

```bash
sudo systemctl stop serial-getty@ttyAMA0.service
sudo systemctl disable serial-getty@ttyAMA0.service
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
ls -la /dev/ttyAMA0
# Should show: crw-rw---- 1 root dialout
```

Test connection:
```bash
cat /dev/ttyAMA0  # Should show telemetry data from Pixhawk
```

## Software Installation

### 1. Install Dependencies

```bash
cd ~/agri_dronesetup/raspberry_pi_companion
chmod +x setup.sh
./setup.sh
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env
```

Edit key settings:
- `MAVLINK_PORT=/dev/ttyAMA0` (or `/dev/ttyUSB0` if using USB)
- `API_HOST=0.0.0.0` (accessible from network)
- `API_PORT=8000`
- Hardware pins match your wiring

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

## Running as Service

### 1. Create Systemd Service

```bash
sudo cp docs/drone-companion.service /etc/systemd/system/
```

### 2. Configure Paths

Edit service file to match your installation:
```bash
sudo nano /etc/systemd/system/drone-companion.service
```

Change paths if not using default:
- `WorkingDirectory=/home/pi/agri_dronesetup/raspberry_pi_companion`
- Environment PATH

### 3. Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable drone-companion
sudo systemctl start drone-companion
```

### 4. Verify Service

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
curl http://localhost:8000/api/vehicle/status
```

### 3. Add Waypoint

```bash
curl -X POST http://localhost:8000/api/mission/add-waypoint \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 40.7128,
    "longitude": -74.0060,
    "altitude": 50.0
  }'
```

### 4. WebSocket Telemetry Stream

```bash
# Using wscat or websocat
wscat -c ws://localhost:8000/ws/telemetry
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
sudo chmod 666 /dev/ttyAMA0
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
   minicom -b 57600 -o -D /dev/ttyAMA0
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
