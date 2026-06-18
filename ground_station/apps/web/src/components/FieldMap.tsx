import { useEffect, useMemo } from 'react';
import { CircleMarker, MapContainer, Polygon, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import type { LatLngPoint, MissionEditorMode, MissionWaypoint, TelemetrySeriesPoint } from '../types';
import type { DroneFleetEntry } from '../../../../shared/types/fleet';

type FieldMapProps = {
  center: [number, number];
  boundary: LatLngPoint[];
  waypoints: MissionWaypoint[];
  breadcrumb: TelemetrySeriesPoint[];
  surveyPreview: LatLngPoint[][];
  vehicle?: LatLngPoint & { heading?: number };
  fleet?: Array<DroneFleetEntry & { position?: LatLngPoint & { heading?: number } }>;
  mode: MissionEditorMode;
  followViewport?: boolean;
  onMapClick: (point: LatLngPoint) => void;
  activeDroneId?: string;
  onSelectDrone?: (droneId: string) => void;
};

function buildPoint(lat: number, lng: number): LatLngPoint {
  return { latitude: lat, longitude: lng };
}

function MapInteractionLayer({ onMapClick }: { onMapClick: (point: LatLngPoint) => void }) {
  useMapEvents({
    click(event) {
      onMapClick(buildPoint(event.latlng.lat, event.latlng.lng));
    },
  });

  return null;
}

function MapViewportSync({ center }: { center: [number, number] }) {
  const map = useMap();
  const [latitude, longitude] = center;

  useEffect(() => {
    map.setView(center);
  }, [latitude, longitude, map]);

  return null;
}

function toLatLngTuple(point: LatLngPoint): [number, number] {
  return [point.latitude, point.longitude];
}

function FieldMapInner({
  center,
  boundary,
  waypoints,
  breadcrumb,
  surveyPreview,
  vehicle,
  fleet = [],
  mode,
  followViewport = true,
  onMapClick,
  activeDroneId,
  onSelectDrone,
}: FieldMapProps) {
  const boundaryCoords = useMemo(() => boundary.map(toLatLngTuple), [boundary]);
  const breadcrumbCoords = useMemo(
    () =>
      breadcrumb
        .reduce<Array<[number, number]>>((acc, point) => {
          const latitude = point.location?.latitude;
          const longitude = point.location?.longitude;
          if (latitude === undefined || longitude === undefined) {
            return acc;
          }

          acc.push([latitude, longitude]);
          return acc;
        }, []),
    [breadcrumb],
  );

  return (
    <div className="field-map-shell">
      <MapContainer center={center} zoom={17} scrollWheelZoom className="field-map">
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {followViewport ? <MapViewportSync center={center} /> : null}
        <MapInteractionLayer onMapClick={onMapClick} />

        {boundaryCoords.length >= 3 ? (
          <Polygon
            positions={boundaryCoords}
            pathOptions={{ color: '#ffb000', fillColor: '#ffb000', fillOpacity: 0.12, weight: 2 }}
          >
            <Tooltip sticky>Draft field boundary</Tooltip>
          </Polygon>
        ) : null}

        {surveyPreview.map((segment, index) => (
          <Polyline
            key={`survey-${index}`}
            positions={segment.map(toLatLngTuple)}
            pathOptions={{ color: '#2fd6c4', weight: 1, dashArray: '5 8', opacity: 0.55 }}
          />
        ))}

        {breadcrumbCoords.length >= 2 ? (
          <Polyline
            positions={breadcrumbCoords}
            pathOptions={{ color: '#6ea8fe', weight: 4, opacity: 0.7 }}
          >
            <Tooltip sticky>Recent telemetry breadcrumb</Tooltip>
          </Polyline>
        ) : null}

        {waypoints.map((waypoint, index) => (
          <CircleMarker
            key={waypoint.id}
            center={toLatLngTuple(waypoint)}
            radius={8}
            pathOptions={{ color: '#2fd6c4', fillColor: '#2fd6c4', fillOpacity: 0.9, weight: 2 }}
          >
            <Tooltip permanent direction="top" offset={[0, -8]}>
              {index + 1}
            </Tooltip>
            <Popup>
              <strong>{waypoint.label}</strong>
              <div>
                {waypoint.latitude.toFixed(5)}, {waypoint.longitude.toFixed(5)}
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {fleet.map((drone) => {
          const position = drone.position;
          if (position?.latitude === undefined || position.longitude === undefined) {
            return null;
          }

          const isActive = activeDroneId === drone.drone_id;
          return (
            <CircleMarker
              key={drone.drone_id}
              center={toLatLngTuple(position)}
              radius={isActive ? 10 : 8}
              pathOptions={{
                color: isActive ? '#ffb000' : '#6ea8fe',
                fillColor: isActive ? '#ffb000' : '#6ea8fe',
                fillOpacity: 0.95,
                weight: 2,
              }}
              eventHandlers={
                onSelectDrone
                  ? {
                      click: () => onSelectDrone(drone.drone_id),
                    }
                  : undefined
              }
            >
              <Tooltip sticky>{drone.callsign ?? drone.drone_id}</Tooltip>
            </CircleMarker>
          );
        })}

        {vehicle?.latitude !== undefined && vehicle?.longitude !== undefined ? (
          <>
            <CircleMarker
              center={toLatLngTuple(vehicle)}
              radius={10}
              pathOptions={{ color: '#ff6d6d', fillColor: '#ff6d6d', fillOpacity: 1, weight: 2 }}
            >
              <Tooltip sticky>Aircraft</Tooltip>
            </CircleMarker>
            {typeof vehicle.heading === 'number' ? (
              <Polyline
                positions={[[vehicle.latitude, vehicle.longitude], [vehicle.latitude + Math.cos((vehicle.heading * Math.PI) / 180) * 0.0018, vehicle.longitude + Math.sin((vehicle.heading * Math.PI) / 180) * 0.0018]]}
                pathOptions={{ color: '#ff6d6d', weight: 4, opacity: 0.85 }}
              />
            ) : null}
          </>
        ) : null}
      </MapContainer>

      <div className="map-hud">
        <span>Mode</span>
        <strong>{mode}</strong>
      </div>
    </div>
  );
}

export function FieldMap(props: FieldMapProps) {
  return <FieldMapInner {...props} />;
}
