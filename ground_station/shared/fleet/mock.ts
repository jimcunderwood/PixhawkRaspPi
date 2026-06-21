import type { FleetConfig } from '../types/fleet';

export const mockFleetConfig: FleetConfig = {
  fleet_id: 'field-alpha',
  default_transport: 'http',
  drones: [
    {
      drone_id: 'drone-01',
      callsign: 'Alpha',
      role: 'leader',
      transport: {
        type: 'http',
        endpoint: 'http://localhost:8000',
        api_key: 'ee3ba92d63dcc1b0f54605b9351f00bf16444383e1a8d4cd7cea8825aa8b8c38',
        control_token: '',
      },
      endpoints: ['http://localhost:8000', 'ws://localhost:8000/ws/telemetry'],
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
        endpoint: 'udp://localhost:14550',
        api_key: 'ee3ba92d63dcc1b0f54605b9351f00bf16444383e1a8d4cd7cea8825aa8b8c38',
        control_token: '',
      },
      endpoints: ['udp://localhost:14550'],
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
