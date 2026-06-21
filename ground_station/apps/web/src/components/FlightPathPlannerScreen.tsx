import { useMemo } from 'react';
import { FieldMap } from './FieldMap';
import type { DroneFleetEntry, FleetConfig } from '../../../../shared/types/fleet';
import type { LatLngPoint, MissionWaypoint } from '../types';
import type { MissionEditorMode } from '../../../../shared/types/base';
import type { FlightPathParameters } from '../../../../shared/mission/routes';

type ObstaclePoint = LatLngPoint & { radius_m?: number; label?: string };

type FlightPathPlannerScreenProps = {
  fleet: FleetConfig;
  selectedDroneId?: string;
  onSelectedDroneChange: (droneId: string) => void;
  boundary: LatLngPoint[];
  waypoints: MissionWaypoint[];
  obstacles: ObstaclePoint[];
  parameters: FlightPathParameters;
  routeName: string;
  mode: MissionEditorMode;
  onModeChange: (mode: MissionEditorMode) => void;
  onBoundaryChange: (boundary: LatLngPoint[]) => void;
  onWaypointsChange: (waypoints: MissionWaypoint[]) => void;
  onObstaclesChange: (obstacles: ObstaclePoint[]) => void;
  onRouteNameChange: (name: string) => void;
  onParametersChange: (parameters: FlightPathParameters) => void;
  onGeneratePath: () => void;
  onSaveRoute: () => void;
  onSaveParameters: () => void;
  onLoadBoundary: () => void;
  routeStatus: string;
  missionHint: string;
  vehicle?: LatLngPoint & { heading?: number };
  breadcrumb: Array<{ location?: LatLngPoint }>;
  surveyPreview: LatLngPoint[][];
  coverage: Array<LatLngPoint & { intensity?: number; radius?: number; label?: string }>;
  activeDroneId?: string;
  onSelectDrone?: (droneId: string) => void;
  onSaveMission: () => void;
  onUploadMission: () => void;
};

export function FlightPathPlannerScreen({
  fleet,
  selectedDroneId,
  onSelectedDroneChange,
  boundary,
  waypoints,
  obstacles,
  parameters,
  routeName,
  mode,
  onModeChange,
  onBoundaryChange,
  onWaypointsChange,
  onObstaclesChange,
  onRouteNameChange,
  onParametersChange,
  onGeneratePath,
  onSaveRoute,
  onSaveParameters,
  onLoadBoundary,
  routeStatus,
  missionHint,
  vehicle,
  breadcrumb,
  surveyPreview,
  coverage,
  activeDroneId,
  onSelectDrone,
  onSaveMission,
  onUploadMission,
}: FlightPathPlannerScreenProps) {
  const selectedDrone = useMemo(
    () => fleet.drones.find((drone) => drone.drone_id === selectedDroneId) ?? fleet.drones[0],
    [fleet.drones, selectedDroneId],
  );

  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">Flight path</span>
          <h3>Generate the Flight Path</h3>
        </div>
        <span className="pill">{routeStatus}</span>
      </div>

      <div className="planner-layout">
        <div className="planner-main">
          <div className="planner-toolbar">
            <label className="field">
              <span>Drone</span>
              <select value={selectedDrone?.drone_id ?? ''} onChange={(event) => onSelectedDroneChange(event.target.value)}>
                {fleet.drones.map((drone) => (
                  <option key={drone.drone_id} value={drone.drone_id}>
                    {drone.callsign ?? drone.drone_id}
                  </option>
                ))}
              </select>
            </label>
            <div className="planner-buttons">
              <button type="button" className="secondary-button" onClick={onLoadBoundary}>
                Import boundary
              </button>
              <button type="button" className="secondary-button" onClick={() => onModeChange('boundary')}>
                Draw boundary
              </button>
              <button type="button" className="secondary-button" onClick={() => onModeChange('waypoint')}>
                Add waypoints
              </button>
              <button type="button" className="secondary-button" onClick={onGeneratePath}>
                Auto-optimize
              </button>
              <button type="button" className="primary-button" onClick={onSaveMission}>
                Save mission
              </button>
              <button type="button" className="secondary-button" onClick={onUploadMission}>
                Upload mission
              </button>
            </div>
          </div>

          <FieldMap
            center={[vehicle?.latitude ?? 40.1123, vehicle?.longitude ?? -74.2129]}
            boundary={boundary}
            waypoints={waypoints}
            breadcrumb={breadcrumb as never}
            surveyPreview={surveyPreview}
            coverage={coverage}
            vehicle={vehicle}
            fleet={fleet.drones.map((drone) => ({
              ...drone,
              active: drone.drone_id === activeDroneId,
              position: drone.drone_id === activeDroneId ? vehicle : undefined,
            }))}
            mode={mode}
            followViewport
            onMapClick={(point) => {
              if (mode === 'boundary') {
                onBoundaryChange([...boundary, point]);
                return;
              }
              if (mode === 'waypoint') {
                onWaypointsChange([
                  ...waypoints,
                  {
                    ...point,
                    id: `wp-${waypoints.length + 1}`,
                    label: `Waypoint ${waypoints.length + 1}`,
                  },
                ]);
              }
            }}
            onBoundaryChange={onBoundaryChange}
            onWaypointsChange={onWaypointsChange}
            activeDroneId={activeDroneId}
            onSelectDrone={onSelectDrone}
          />
        </div>

        <aside className="planner-side">
          <label className="field">
            <span>Field name</span>
            <input value={routeName} onChange={(event) => onRouteNameChange(event.target.value)} />
          </label>
          <label className="field">
            <span>Flight altitude (m)</span>
            <input type="number" value={parameters.altitude_m} onChange={(event) => onParametersChange({ ...parameters, altitude_m: Number(event.target.value) })} />
          </label>
          <label className="field">
            <span>Speed (m/s)</span>
            <input type="number" value={parameters.speed_mps} onChange={(event) => onParametersChange({ ...parameters, speed_mps: Number(event.target.value) })} />
          </label>
          <label className="field">
            <span>Swath width (m)</span>
            <input type="number" value={parameters.swath_width_m} onChange={(event) => onParametersChange({ ...parameters, swath_width_m: Number(event.target.value) })} />
          </label>
          <label className="field">
            <span>Boundary pass</span>
            <select value={parameters.boundary_pass} onChange={(event) => onParametersChange({ ...parameters, boundary_pass: event.target.value as FlightPathParameters['boundary_pass'] })}>
              <option value="none">None</option>
              <option value="before">Before</option>
              <option value="after">After</option>
            </select>
          </label>
          <label className="field checkbox-field">
            <input type="checkbox" checked={parameters.auto_optimize} onChange={(event) => onParametersChange({ ...parameters, auto_optimize: event.target.checked })} />
            <span>Enable Auto Optimization</span>
          </label>
          <div className="stack">
            <button type="button" className="secondary-button" onClick={onSaveParameters}>Save Parameters</button>
            <button type="button" className="secondary-button" onClick={onSaveRoute}>Save and Fly</button>
          </div>
          <div className="list-card">
            <div className="list-row"><div><strong>Boundary</strong><span>{boundary.length} points</span></div></div>
            <div className="list-row"><div><strong>Obstacles</strong><span>{obstacles.length} defined</span></div></div>
            <div className="list-row"><div><strong>Hint</strong><span>{missionHint}</span></div></div>
          </div>
        </aside>
      </div>
    </section>
  );
}
