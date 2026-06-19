import type { FleetConfig } from '../types/fleet';

export const mockFleetConfig: FleetConfig = {
  fleet_id: 'field-alpha',
  default_transport: 'websocket',
  drones: [
    {
      drone_id: 'drone-01',
      callsign: 'Alpha',
      role: 'leader',
      transport: {
        type: 'websocket',
        endpoint: 'ws://192.168.1.50:9001',
        api_key: '',
      },
      endpoints: ['ws://192.168.1.50:9001', 'http://192.168.1.50:8000'],
      capabilities: ['arm', 'takeoff', 'land', 'mission', 'telemetry'],
      status: 'active',
      last_heartbeat: new Date().toISOString(),
    },
    {
      drone_id: 'drone-02',
      callsign: 'Bravo',
      role: 'wing',
      transport: {
        type: 'udp',
        endpoint: 'udp://192.168.1.51:14550',
        api_key: '',
      },
      endpoints: ['udp://192.168.1.51:14550'],
      capabilities: ['mission', 'telemetry'],
      status: 'staged',
      last_heartbeat: new Date().toISOString(),
    },
  ],
  device_profiles: [
    {
      profile_id: 'browser-tablet',
      runtime: 'web',
      preferred_transports: ['websocket', 'http'],
    },
    {
      profile_id: 'desktop-field-ops',
      runtime: 'desktop',
      preferred_transports: ['ipc', 'websocket', 'http'],
    },
  ],
};
