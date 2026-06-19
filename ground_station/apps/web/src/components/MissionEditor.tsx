import type { MissionEditorMode, MissionWaypoint, LatLngPoint } from '../types';

type MissionEditorProps = {
  mode: MissionEditorMode;
  boundary: LatLngPoint[];
  waypoints: MissionWaypoint[];
  routeName: string;
  onModeChange: (mode: MissionEditorMode) => void;
  onClearBoundary: () => void;
  onClearWaypoints: () => void;
  onUndoBoundaryPoint: () => void;
  onUndoWaypoint: () => void;
  onRouteNameChange: (name: string) => void;
  onSaveRoute: () => void;
  onUploadRoute: () => void;
  onDownloadRoute: () => void;
  onLoadRoute: () => void;
  routeStatus: string;
};

function countLabel(count: number, label: string) {
  return `${count} ${label}${count === 1 ? '' : 's'}`;
}

export function MissionEditor({
  mode,
  boundary,
  waypoints,
  routeName,
  onModeChange,
  onClearBoundary,
  onClearWaypoints,
  onUndoBoundaryPoint,
  onUndoWaypoint,
  onRouteNameChange,
  onSaveRoute,
  onUploadRoute,
  onDownloadRoute,
  onLoadRoute,
  routeStatus,
}: MissionEditorProps) {
  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">Mission editor</span>
          <h3>Boundary drawing and waypoint tools</h3>
        </div>
        <span className="pill">{mode}</span>
      </div>

      <div className="editor-toolbar">
        <button
          className={mode === 'view' ? 'toolbar-button active' : 'toolbar-button'}
          onClick={() => onModeChange('view')}
          type="button"
        >
          View
        </button>
        <button
          className={mode === 'boundary' ? 'toolbar-button active' : 'toolbar-button'}
          onClick={() => onModeChange('boundary')}
          type="button"
        >
          Draw boundary
        </button>
        <button
          className={mode === 'waypoint' ? 'toolbar-button active' : 'toolbar-button'}
          onClick={() => onModeChange('waypoint')}
          type="button"
        >
          Add waypoints
        </button>
      </div>

      <label className="field">
        <span>Route name</span>
        <input
          value={routeName}
          onChange={(event) => onRouteNameChange(event.target.value)}
          placeholder="North field survey"
        />
      </label>

      <div className="editor-actions">
        <button type="button" className="ghost-button" onClick={onUndoBoundaryPoint} disabled={!boundary.length}>
          Undo boundary point
        </button>
        <button type="button" className="ghost-button" onClick={onClearBoundary} disabled={!boundary.length}>
          Clear boundary
        </button>
        <button type="button" className="ghost-button" onClick={onUndoWaypoint} disabled={!waypoints.length}>
          Undo waypoint
        </button>
        <button type="button" className="ghost-button" onClick={onClearWaypoints} disabled={!waypoints.length}>
          Clear waypoints
        </button>
        <button type="button" className="ghost-button" onClick={onSaveRoute}>
          Save route
        </button>
        <button type="button" className="ghost-button" onClick={onDownloadRoute}>
          Export JSON
        </button>
        <button type="button" className="ghost-button" onClick={onLoadRoute}>
          Load companion
        </button>
        <button type="button" className="ghost-button" onClick={onUploadRoute}>
          Upload route
        </button>
      </div>

      <p className="hint">
        Click on the map to add boundary points or mission waypoints. Drag vertices and waypoints to edit them, and use the boundary polygon after the third point.
      </p>

      <div className="editor-stats">
        <div>
          <strong>{countLabel(boundary.length, 'boundary point')}</strong>
          <span>Defines the field envelope</span>
        </div>
        <div>
          <strong>{countLabel(waypoints.length, 'waypoint')}</strong>
          <span>Builds the draft route</span>
        </div>
      </div>

      <div className="list-card">
        <div className="list-row">
          <div>
            <strong>Map hint</strong>
            <span>{mode === 'boundary' ? 'Boundary mode active' : mode === 'waypoint' ? 'Waypoint mode active' : 'View mode active'}</span>
          </div>
        </div>
        <div className="list-row">
          <div>
            <strong>Route status</strong>
            <span>{routeStatus}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
