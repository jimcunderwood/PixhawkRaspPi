"""
Example Client Script
Demonstrates how to use the Companion Computer API
"""

import requests
import websocket
import json
import os
import time
import threading

# Configuration
API_URL = "http://192.168.4.10:8000"  # Change to your Pi's IP
WS_URL = "ws://192.168.4.10:8000"
API_KEY = os.getenv("DRONE_API_KEY", "")


class DroneClient:
    """Example client for controlling the drone"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.ws = None
        self.session = requests.Session()
        if API_KEY:
            self.session.headers.update({"x-api-key": API_KEY})

    def health_check(self):
        """Check if API is running"""
        try:
            response = self.session.get(f"{self.base_url}/health")
            print(f"✓ API Health: {response.json()}")
            return True
        except Exception as e:
            print(f"✗ API Error: {str(e)}")
            return False

    def get_vehicle_status(self):
        """Get current vehicle state"""
        response = self.session.get(f"{self.base_url}/api/vehicle/status")
        data = response.json()
        
        if data['status'] == 'success':
            vehicle = data['data']
            print(f"Vehicle Status:")
            print(f"  Armed: {vehicle['armed']}")
            print(f"  Mode: {vehicle['mode']}")
            print(
                f"  GPS: {vehicle['location']['latitude']:.6f}, "
                f"{vehicle['location']['longitude']:.6f}"
            )
            print(f"  Altitude: {vehicle['location']['altitude']:.1f}m")
            print(f"  Battery: {vehicle['battery']['level_percent']:.1f}%")
            return vehicle
        else:
            print(f"Error: {data['message']}")
            return None

    def arm_drone(self, arm: bool = True):
        """Arm or disarm the drone"""
        action = "Arming" if arm else "Disarming"
        print(f"{action} drone...")
        
        response = self.session.post(
            f"{self.base_url}/api/vehicle/arm",
            json={'armed': arm}
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def takeoff(self, altitude: float):
        """Takeoff to specified altitude"""
        print(f"Taking off to {altitude}m...")
        
        response = self.session.post(
            f"{self.base_url}/api/vehicle/takeoff",
            json={'altitude': altitude}
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def land(self):
        """Land the drone"""
        print("Landing...")
        
        response = self.session.post(f"{self.base_url}/api/vehicle/land")
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def goto(self, latitude: float, longitude: float, altitude: float):
        """Fly to GPS location"""
        print(f"Flying to {latitude:.6f}, {longitude:.6f} at {altitude}m...")
        
        response = self.session.post(
            f"{self.base_url}/api/vehicle/goto",
            json={
                'location': {
                    'latitude': latitude,
                    'longitude': longitude,
                    'altitude': altitude
                }
            }
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def set_mode(self, mode: str):
        """Change flight mode"""
        print(f"Setting mode to {mode}...")
        
        response = self.session.post(
            f"{self.base_url}/api/vehicle/mode",
            json={'mode': mode}
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    # Mission Operations
    
    def add_waypoint(
        self,
        latitude: float,
        longitude: float,
        altitude: float,
        altitude_frame: str | None = None,
    ):
        """Add waypoint to mission"""
        print(f"Adding waypoint: {latitude:.6f}, {longitude:.6f}, {altitude}m")

        payload = {
            'location': {
                'latitude': latitude,
                'longitude': longitude,
                'altitude': altitude
            }
        }
        if altitude_frame:
            payload['altitude_frame'] = altitude_frame

        response = self.session.post(
            f"{self.base_url}/api/mission/add-waypoint",
            json=payload
        )
        data = response.json()
        return data['status'] == 'success'

    def get_mission(self):
        """Get current mission"""
        response = self.session.get(f"{self.base_url}/api/mission/waypoints")
        data = response.json()
        
        if data['status'] == 'success':
            mission = data['data']
            waypoints = mission.get('waypoints', [])
            print(f"Mission ({len(waypoints)} waypoints):")
            for item in waypoints:
                print(f"  {item['sequence']}: "
                      f"{item['location']['latitude']:.6f}, "
                      f"{item['location']['longitude']:.6f}, "
                      f"{item['location']['altitude']}m "
                      f"({item.get('altitude_frame', 'relative')})")
            return waypoints
        return None

    def start_mission(self):
        """Start mission execution"""
        print("Starting mission...")
        
        response = self.session.post(f"{self.base_url}/api/mission/start")
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def pause_mission(self):
        """Pause mission"""
        print("Pausing mission...")
        
        response = self.session.post(f"{self.base_url}/api/mission/pause")
        data = response.json()
        return data['status'] == 'success'

    def abort_mission(self):
        """Abort mission"""
        print("Aborting mission...")
        
        response = self.session.post(f"{self.base_url}/api/mission/abort")
        data = response.json()
        return data['status'] == 'success'

    def get_mission_stats(self):
        """Get mission statistics"""
        response = self.session.get(f"{self.base_url}/api/mission/stats")
        data = response.json()
        
        if data['status'] == 'success':
            stats = data['data']
            print(f"Mission Stats:")
            print(f"  Total items: {stats.get('total_item_count', 0)}")
            print(f"  Waypoints: {stats.get('waypoint_count', 0)}")
            print(f"  Altitude range: {stats.get('min_altitude', 0):.1f} - "
                  f"{stats.get('max_altitude', 0):.1f}m")
            return stats
        return None

    # Navigation Safety

    def get_navigation_config(self):
        """Get obstacle avoidance and terrain-following config"""
        response = self.session.get(f"{self.base_url}/api/navigation/config")
        data = response.json()

        if data['status'] == 'success':
            navigation = data['data']
            config = navigation['config']
            print("Navigation Config:")
            print(f"  Obstacle avoidance: {config['obstacle_avoidance']['enabled']}")
            print(f"    Mode: {config['obstacle_avoidance']['mode']}")
            print(f"    Margin: {config['obstacle_avoidance']['margin_meters']}m")
            print(f"  Terrain following: {config['terrain_following']['enabled']}")
            print(f"    Source: {config['terrain_following']['source']}")
            print(f"    AGL limits: {config['terrain_following']['min_agl_meters']} - "
                  f"{config['terrain_following']['max_agl_meters']}m")
            return navigation
        return None

    def configure_navigation(
        self,
        obstacle_enabled: bool = True,
        obstacle_mode: str = "bendy_ruler",
        terrain_enabled: bool = True,
        terrain_source: str = "rangefinder",
        apply_to_pixhawk: bool = False,
    ):
        """Configure obstacle avoidance and terrain following"""
        print("Configuring navigation safety...")

        response = self.session.post(
            f"{self.base_url}/api/navigation/config",
            json={
                'obstacle_avoidance': {
                    'enabled': obstacle_enabled,
                    'mode': obstacle_mode,
                    'margin_meters': 2.0,
                    'lookahead_meters': 5.0,
                    'behavior': 'slide',
                    'bendy_ruler_type': 'horizontal',
                    'proximity_type': 4,
                },
                'terrain_following': {
                    'enabled': terrain_enabled,
                    'source': terrain_source,
                    'min_agl_meters': 2.0,
                    'max_agl_meters': 120.0,
                    'use_rangefinder_for_waypoints': terrain_source == 'rangefinder',
                },
                'apply_to_pixhawk': apply_to_pixhawk,
            }
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def apply_navigation_config(self):
        """Apply saved navigation config to Pixhawk parameters"""
        print("Applying navigation config to Pixhawk...")
        response = self.session.post(f"{self.base_url}/api/navigation/apply")
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    # Payload Control

    def start_spray(self):
        """Start spray pump"""
        print("Starting spray...")
        
        response = self.session.post(
            f"{self.base_url}/api/payload/control",
            json={'action': 'spray_start'}
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def stop_spray(self):
        """Stop spray pump"""
        print("Stopping spray...")
        
        response = self.session.post(
            f"{self.base_url}/api/payload/control",
            json={'action': 'spray_stop'}
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def capture_photo(self):
        """Capture photo"""
        print("Capturing photo...")
        
        response = self.session.post(
            f"{self.base_url}/api/payload/control",
            json={'action': 'photo'}
        )
        data = response.json()
        print(f"  Result: {data['message']}")
        return data['status'] == 'success'

    def get_payload_status(self):
        """Get payload status"""
        response = self.session.get(f"{self.base_url}/api/payload/status")
        data = response.json()
        
        if data['status'] == 'success':
            payload = data['data']
            print(f"Payload Status:")
            
            if 'spray_pump' in payload:
                spray = payload['spray_pump']
                print(f"  Spray Pump: {spray['status']}")
                print(f"    Total time: {spray['total_on_time_seconds']:.1f}s")
            
            if 'flow_sensor' in payload:
                flow = payload['flow_sensor']
                print(f"  Flow Sensor:")
                print(f"    Total volume: {flow['total_volume_liters']:.2f}L")
                print(f"    Flow rate: {flow['flow_rate_liters_per_minute']:.2f}L/min")
            
            if 'camera' in payload:
                camera = payload['camera']
                print(f"  Camera:")
                print(f"    Photos: {camera['total_photos']}")
                print(f"    Recording: {camera['is_recording']}")
            
            return payload
        return None

    # Telemetry

    def get_telemetry(self):
        """Get current telemetry"""
        response = self.session.get(f"{self.base_url}/api/telemetry/current")
        data = response.json()
        
        if data['status'] == 'success':
            telemetry = data['data']
            print(f"Current Telemetry:")
            print(f"  GPS: {telemetry['location']['latitude']:.6f}, "
                  f"{telemetry['location']['longitude']:.6f}, "
                  f"{telemetry['location']['altitude']:.1f}m")
            print(f"  Battery: {telemetry['battery']['level_percent']:.1f}% "
                  f"({telemetry['battery']['voltage']:.2f}V)")
            print(f"  Groundspeed: {telemetry['ground_speed']:.1f} m/s")
            print(f"  Heading: {telemetry['heading']}°")
            return telemetry
        return None

    def subscribe_telemetry(self, callback):
        """Subscribe to live telemetry stream"""
        print("Subscribing to telemetry stream...")
        ws_url = f"{WS_URL}/ws/telemetry"
        if API_KEY:
            ws_url = f"{ws_url}?api_key={API_KEY}"
        
        def run():
            try:
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=lambda ws, msg: callback(json.loads(msg)),
                    on_error=lambda ws, err: print(f"WS Error: {err}"),
                    on_close=lambda ws: print("Connection closed")
                )
                self.ws.run_forever()
            except Exception as e:
                print(f"WebSocket error: {str(e)}")
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread


def example_simple_flight():
    """Simple flight example"""
    print("=== Simple Flight Example ===\n")
    
    client = DroneClient(API_URL)
    
    # Check health
    if not client.health_check():
        print("Cannot connect to drone computer")
        return
    
    print()
    
    # Get status
    client.get_vehicle_status()
    print()
    
    # Arm
    if not client.arm_drone(True):
        return
    
    time.sleep(2)
    
    # Takeoff
    if not client.takeoff(30):  # 30 meters
        return
    
    time.sleep(10)
    
    # Check status
    client.get_vehicle_status()
    print()
    
    # Land
    if not client.land():
        return
    
    time.sleep(5)
    
    # Disarm
    client.arm_drone(False)


def example_mission():
    """Mission planning example"""
    print("=== Mission Planning Example ===\n")
    
    client = DroneClient(API_URL)
    
    # Clear previous mission
    client.session.post(f"{API_URL}/api/mission/clear")
    
    # Create mission
    waypoints = [
        (40.7128, -74.0060, 50.0),
        (40.7150, -74.0080, 50.0),
        (40.7180, -74.0100, 60.0),
        (40.7200, -74.0070, 60.0),
    ]
    
    for lat, lon, alt in waypoints:
        client.add_waypoint(lat, lon, alt)
    
    print()
    
    # Show mission
    client.get_mission()
    print()
    
    # Get statistics
    client.get_mission_stats()


def example_navigation_safety():
    """Obstacle avoidance and terrain-following example"""
    print("=== Navigation Safety Example ===\n")

    client = DroneClient(API_URL)

    client.get_navigation_config()
    print()

    client.configure_navigation(
        obstacle_enabled=True,
        obstacle_mode="bendy_ruler",
        terrain_enabled=True,
        terrain_source="rangefinder",
        apply_to_pixhawk=False,
    )
    print()

    client.get_navigation_config()


def example_spray_mission():
    """Spray mission example"""
    print("=== Spray Mission Example ===\n")
    
    client = DroneClient(API_URL)
    
    print("Arming and taking off...")
    client.arm_drone(True)
    time.sleep(1)
    client.takeoff(30)
    time.sleep(5)
    
    print("\nStarting spray mission...")
    client.start_spray()
    
    time.sleep(10)  # Spray for 10 seconds
    
    print("\nStopping spray...")
    client.stop_spray()
    
    print("\nPayload status:")
    client.get_payload_status()
    
    print("\nLanding...")
    client.land()
    time.sleep(5)
    client.arm_drone(False)


def example_telemetry_stream():
    """Live telemetry stream example"""
    print("=== Telemetry Stream Example ===\n")
    
    client = DroneClient(API_URL)
    
    message_count = [0]
    
    def on_telemetry(data):
        message_count[0] += 1
        if message_count[0] % 10 == 0:  # Print every 10th message
            print(f"Telemetry #{message_count[0]}: "
                  f"Alt={data['location']['altitude']:.1f}m, "
                  f"Batt={data['battery']['level_percent']:.1f}%")
    
    thread = client.subscribe_telemetry(on_telemetry)
    
    # Let it run for 30 seconds
    time.sleep(30)
    
    if client.ws:
        client.ws.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python example_client.py [flight|mission|navigation|spray|telemetry]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "flight":
        example_simple_flight()
    elif command == "mission":
        example_mission()
    elif command == "navigation":
        example_navigation_safety()
    elif command == "spray":
        example_spray_mission()
    elif command == "telemetry":
        example_telemetry_stream()
    else:
        print(f"Unknown command: {command}")
