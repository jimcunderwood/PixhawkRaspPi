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
  weather: {
    enabled: true,
    station_id: 'KJFK',
    configured: true,
    last_briefing: {
      station_id: 'KJFK',
      ready: true,
      blocking_reasons: [],
      advisories: ['TAF contains significant changes or tempo periods.'],
      metar: {
        flight_category: 'VFR',
        visibility_sm: 6,
        ceiling_ft: 3200,
        wind: {
          direction: '180',
          speed_kt: 8,
          gust_kt: 14,
        },
      },
      taf: {
        significant_changes: ['BECMG 1820/1822 18008KT P6SM SCT020'],
      },
      updated_at: Date.now() / 1000,
      updated_at_iso: new Date().toISOString(),
    },
  },
  edge_ai: {
    enabled: true,
    backend: 'yolo',
    configured: true,
    confidence_threshold: 0.5,
    sample_interval_seconds: 0.5,
    last_result: {
      available: true,
      backend: 'yolo',
      detections: [
        {
          label: 'tree',
          confidence: 0.88,
          bbox: { x1: 120, y1: 84, x2: 278, y2: 264 },
        },
      ],
      obstacle_detections: [
        {
          label: 'tree',
          confidence: 0.88,
          bbox: { x1: 120, y1: 84, x2: 278, y2: 264 },
        },
      ],
      obstacle_risk: true,
      scan_at: Date.now() / 1000,
    },
  },
  fleet: {
    fleet_id: 'field-alpha-swarm',
    self_drone_id: 'drone-01',
    enabled: true,
    peer_count: 2,
    active_drone_count: 2,
    drones: [
      {
        drone_id: 'drone-01',
        callsign: 'Alpha',
        role: 'leader',
        transport: {
          type: 'websocket',
          endpoint: 'ws://localhost:9001',
        },
        status: 'active',
        last_seen_at: Date.now() / 1000,
        position: {
          latitude: 40.1123,
          longitude: -74.2129,
          altitude: 51.4,
          heading: 128,
        },
        vehicle: {
          armed: false,
          mode: 'GUIDED',
          battery_percent: 78,
        },
      },
      {
        drone_id: 'drone-02',
        callsign: 'Bravo',
        role: 'wing',
        transport: {
          type: 'udp',
          endpoint: 'udp://localhost:14550',
        },
        status: 'staged',
        last_seen_at: Date.now() / 1000 - 18,
        position: {
          latitude: 40.1129,
          longitude: -74.2134,
          altitude: 50.8,
          heading: 132,
        },
        vehicle: {
          armed: false,
          mode: 'AUTO',
          battery_percent: 71,
        },
      },
    ],
    fusion: {
      swarm_id: 'field-alpha-swarm',
      self_drone_id: 'drone-01',
    },
    status: {
      swarm_id: 'field-alpha-swarm',
      self_drone_id: 'drone-01',
      enabled: true,
      healthy_peer_count: 2,
      peer_count: 2,
      fusion_mode: 'weighted_gnss',
      alerts: [],
    },
    updated_at: Date.now() / 1000,
  },
  prescription: {
    enabled: true,
    configured: true,
    active_map: {
      map_id: 'corn-field-2026',
      name: 'Corn Field 2026',
      description: 'Mock prescription map for variable-rate spraying',
      source_format: 'geojson',
      default_rate_lpha: 18,
      swath_width_m: 12,
      active: true,
      zones: [
        {
          zone_id: 1,
          label: 'North edge',
          target_rate_lpha: 22,
          geometry_type: 'polygon',
          priority: 2,
        },
      ],
    },
    current_zone: {
      zone_id: 1,
      label: 'North edge',
      target_rate_lpha: 22,
      geometry_type: 'polygon',
      priority: 2,
    },
    target_rate_liters_per_hectare: 22,
    current_flow_rate_liters_per_minute: 8.8,
    recommended_duty_cycle: 0.53,
    ground_speed_mps: 3.8,
    swath_width_m: 12,
    location: {
      latitude: 40.1123,
      longitude: -74.2129,
    },
    updated_at: Date.now() / 1000,
  },
  calibration: {
    enabled: true,
    rtk_enabled: true,
    ppk_enabled: true,
    base_station_count: 1,
    active_base_station: {
      station_id: 'base-01',
      name: 'Field base station',
      latitude: 40.1119,
      longitude: -74.2132,
      altitude_m: 50.9,
      antenna_height_m: 1.5,
      correction_port: '/dev/ttyUSB0',
      correction_baudrate: 115200,
      mount_type: 'tripod',
      active: true,
    },
    base_stations: [],
    recent_jobs: [],
    last_job: {
      job_id: 'ppk-001',
      session: 'Draft route',
      status: 'complete',
      source_label: 'ground-station-telemetry',
      telemetry_window_seconds: 600,
      request: {
        session: 'Draft route',
        base_station_id: 'base-01',
        telemetry_window_seconds: 600,
        source_label: 'ground-station-telemetry',
      },
      summary: {
        sample_count: 120,
        path_length_m: 1560,
        duration_s: 612,
        average_ground_speed_mps: 3.8,
        estimated_horizontal_accuracy_m: 0.16,
      },
      quality: {
        correction_applied: true,
        estimated_position_error_m: 0.16,
      },
    },
  },
  farm: {
    enabled: true,
    configured: true,
    agleader_configured: true,
    isoxml_output_directory: '/var/lib/drone-companion/farm/isoxml',
    report_output_directory: '/var/lib/drone-companion/farm/reports',
    latest_isoxml_export: {
      archive_path: '/var/lib/drone-companion/farm/isoxml/isoxml-0001.zip',
      generated_at_iso: new Date().toISOString(),
    },
    latest_report: {
      report_path: '/var/lib/drone-companion/farm/reports/report-0001.json',
    },
    recent_isoxml_exports: [
      {
        name: 'isoxml-0001.zip',
        path: '/var/lib/drone-companion/farm/isoxml/isoxml-0001.zip',
        updated_at: Date.now() / 1000 - 7200,
      },
      {
        name: 'isoxml-0002.zip',
        path: '/var/lib/drone-companion/farm/isoxml/isoxml-0002.zip',
        updated_at: Date.now() / 1000 - 900,
      },
    ],
    recent_reports: [
      {
        name: 'report-0001.json',
        path: '/var/lib/drone-companion/farm/reports/report-0001.json',
        updated_at: Date.now() / 1000 - 3600,
      },
      {
        name: 'report-0002.json',
        path: '/var/lib/drone-companion/farm/reports/report-0002.json',
        updated_at: Date.now() / 1000 - 180,
      },
    ],
  },
  flight_log_sync: {
    status: 'idle',
    running: false,
    last_landing_at: Date.now() / 1000 - 420,
    last_armed_at: Date.now() / 1000 - 1120,
    base_directory: '/var/lib/drone-companion/flight-logs',
    updated_at: Date.now() / 1000 - 75,
  },
  swarm_coordination: {
    swarm_id: 'field-alpha-swarm',
    self_drone_id: 'drone-01',
    formation_mode: 'leader_follower',
    leader_drone_id: 'drone-01',
    assignments: [
      { drone_id: 'drone-01', callsign: 'Alpha', role: 'leader', sector_index: 0 },
      { drone_id: 'drone-02', callsign: 'Bravo', role: 'follower', sector_index: 1 },
    ],
    collision_avoidance: {
      enabled: true,
      recommended_action: 'continue',
    },
    fusion: {
      swarm_id: 'field-alpha-swarm',
      self_drone_id: 'drone-01',
      confidence: 0.84,
    },
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
