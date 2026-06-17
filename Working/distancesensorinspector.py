#!/usr/bin/env python3
import time
from pymavlink import mavutil

# Connect to the vehicle over the physical serial port
master = mavutil.mavlink_connection('/dev/serial0', baud=57600)

print("Waiting for vehicle heartbeat...")
master.wait_heartbeat()
print("Connected! Monitoring exclusively for range sensor packets...\n")

while True:
    # Filter the stream specifically for rangefinder messages
    msg = master.recv_match(type=['DISTANCE_SENSOR', 'RANGEFINDER'], blocking=True)
    
    if msg:
        msg_name = msg.get_type()
        msg_id = msg.get_msgId()
        
        # 1. Get the raw binary hex string of the entire packet frame
        raw_frame = msg.get_msgbuf()
        hex_frame = " ".join(f"{b:02X}" for b in raw_frame)
        
        # 2. Get the clean python dictionary representation of the data fields
        msg_fields = msg.to_dict()
        
        # Print the complete, unified packet layout to the screen
        print(f"=== [ {msg_name} | Message ID: {msg_id} ] ===")
        print(f"  Frame Bytes ({len(raw_frame)} total):")
        print(f"    {hex_frame}")
        print("  Decoded Data Payload:")
        
        for key, value in msg_fields.items():
            print(f"    {key}: {value}")
            
        print("-" * 50 + "\n")
        
    time.sleep(0.05)
