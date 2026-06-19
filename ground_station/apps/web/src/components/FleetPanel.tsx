import type { DroneFleetEntry } from '../../../../shared/types/fleet';

type FleetPanelProps = {
  drones: Array<DroneFleetEntry & { active?: boolean }>;
  activeDroneId?: string;
  onSelectDrone: (droneId: string) => void;
};

function toneForStatus(status?: string) {
  if (!status) {
    return 'neutral';
  }

  if (['active', 'connected', 'armed'].includes(status)) {
    return 'good';
  }

  if (['staged', 'ready', 'idle'].includes(status)) {
    return 'warn';
  }

  return 'bad';
}

export function FleetPanel({ drones, activeDroneId, onSelectDrone }: FleetPanelProps) {
  const activeCount = drones.filter((drone) => drone.active).length;

  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">Fleet</span>
          <h3>Multi-drone view</h3>
        </div>
        <span className="pill">{activeCount}/{drones.length} active</span>
      </div>

      <div className="list-card">
        {drones.map((drone) => (
          <button
            type="button"
            key={drone.drone_id}
            className={`fleet-row ${activeDroneId === drone.drone_id ? 'fleet-row-active' : ''}`}
            onClick={() => onSelectDrone(drone.drone_id)}
          >
            <div>
              <strong>
                {drone.callsign ?? drone.drone_id}
                {drone.active ? ' (live)' : ''}
              </strong>
              <span>{drone.role ?? 'mission member'}</span>
            </div>
            <span className={`check-status check-${toneForStatus(drone.status)}`}>
              {drone.status ?? 'unknown'}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
