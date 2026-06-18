import type { CompanionSnapshot } from '../types';

export const mockSnapshot: CompanionSnapshot = {
  health: {
    status: 'ok',
    message: 'Mock companion ready',
    data: {
      status: 'ok',
      version: 'dev',
      uptime_seconds: 1842,
      connected: true,
      api_ready: true,
    },
  },
  vehicle: {
    armed: false,
    mode: 'GUIDED',
    ground_speed: 3.8,
    air_speed: 4.1,
    heading: 128,
    location: {
      latitude: 40.1123,
      longitude: -74.2129,
      altitude: 51.4,
    },
    battery: {
      voltage: 23.4,
      current: 8.2,
      level_percent: 78,
    },
    gps: {
      fix_type: 6,
      satellite_count: 15,
    },
  },
  readiness: {
    healthy: true,
    warning_count: 1,
    critical_count: 0,
    checks: [
      { name: 'GPS lock', status: 'pass', detail: '3D fix with 15 satellites' },
      { name: 'Battery', status: 'pass', detail: '78 percent remaining' },
      { name: 'Geofence', status: 'warn', detail: 'North boundary under review' },
    ],
  },
  safety: {
    geofences: [
      { name: 'North Field', type: 'field', enabled: true },
      { name: 'Road Buffer', type: 'no-fly', enabled: true },
    ],
    waivers: {
      night_flight_authorized: false,
      bvlos_authorized: false,
    },
    remote_id: {
      enabled: true,
      identifier: 'RID-AGRI-001',
    },
  },
  mission: {
    waypoint_count: 12,
    active: true,
    completed: 5,
    total_distance_m: 1840,
    estimated_duration_s: 1480,
  },
  navigation: {
    obstacle_avoidance: {
      enabled: true,
      mode: 'simple',
      margin_meters: 2.5,
    },
    terrain_following: {
      enabled: true,
      source: 'rangefinder',
      target_agl_meters: 18,
    },
    distance_sensors: [
      { sensor_id: 0, distance_meters: 6.7, source: 'mavlink.distance_sensor' },
      { sensor_id: 1, distance_meters: 11.9, source: 'mavlink.distance_sensor' },
    ],
  },
  telemetry: {
    timestamp: Date.now() / 1000,
    armed: false,
    mode: 'GUIDED',
    ground_speed: 3.8,
    air_speed: 4.1,
    heading: 128,
    battery: {
      level_percent: 78,
      voltage: 23.4,
      current: 8.2,
    },
    location: {
      latitude: 40.1123,
      longitude: -74.2129,
      altitude: 51.4,
    },
  },
};
