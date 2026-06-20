import { memo, useEffect, useMemo } from 'react';
import { divIcon, type DivIconOptions, type LeafletMouseEvent, type LatLngExpression, type Marker as LeafletMarker } from 'leaflet';
import {
  Circle,
  ImageOverlay,
  LayersControl,
  MapContainer,
  Marker,
  Pane,
  Polygon,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import type { LatLngPoint, MissionEditorMode, MissionWaypoint, TelemetrySeriesPoint } from '../types';
import type { DroneFleetEntry } from '../../../../shared/types/fleet';

type FieldOverlay = {
  url: string;
  bounds: [[number, number], [number, number]];
  opacity?: number;
  label?: string;
};

type CoveragePoint = LatLngPoint & {
  intensity?: number;
  radius?: number;
  label?: string;
};

type FieldMapProps = {
  center: [number, number];
  boundary: LatLngPoint[];
  waypoints: MissionWaypoint[];
  breadcrumb: TelemetrySeriesPoint[];
  surveyPreview: LatLngPoint[][];
  vehicle?: LatLngPoint & { heading?: number };
  fleet?: Array<DroneFleetEntry & { position?: LatLngPoint & { heading?: number } }>;
  coverage?: CoveragePoint[];
  aerialOverlay?: FieldOverlay;
  mode: MissionEditorMode;
  followViewport?: boolean;
  onMapClick: (point: LatLngPoint) => void;
  onBoundaryChange: (boundary: LatLngPoint[]) => void;
  onWaypointsChange: (waypoints: MissionWaypoint[]) => void;
  activeDroneId?: string;
  onSelectDrone?: (droneId: string) => void;
};

function buildPoint(lat: number, lng: number): LatLngPoint {
  return { latitude: lat, longitude: lng };
}

function toLatLngTuple(point: LatLngPoint): [number, number] {
  return [point.latitude, point.longitude];
}

function toLatLngExpression(point: LatLngPoint): LatLngExpression {
  return [point.latitude, point.longitude];
}

function createMarkerIcon(kind: 'boundary' | 'waypoint' | 'vehicle' | 'drone', label?: string, active = false) {
  const labelMarkup = label ? `<span>${label}</span>` : '';
  const className = ['field-marker', `field-marker-${kind}`, active ? 'field-marker-active' : '']
    .filter(Boolean)
    .join(' ');

  return divIcon({
    className: '',
    html: `<div class="${className}">${labelMarkup}</div>`,
    iconSize: kind === 'vehicle' ? [42, 42] : [34, 34],
    iconAnchor: kind === 'vehicle' ? [21, 21] : [17, 17],
  } satisfies DivIconOptions);
}

function MapInteractionLayer({ onMapClick }: { onMapClick: (point: LatLngPoint) => void }) {
  useMapEvents({
    click(event: LeafletMouseEvent) {
      onMapClick(buildPoint(event.latlng.lat, event.latlng.lng));
    },
  });

  return null;
}

function MapViewportSync({ center, followViewport }: { center: [number, number]; followViewport: boolean }) {
  const map = useMap();
  const [latitude, longitude] = center;

  useEffect(() => {
    if (!followViewport) {
      return;
    }

    map.setView(center, map.getZoom(), { animate: true });
  }, [latitude, longitude, followViewport, map]);

  return null;
}

const FleetMarkerLayer = memo(function FleetMarkerLayer({
  fleet,
  activeDroneId,
  onSelectDrone,
}: {
  fleet: Array<DroneFleetEntry & { position?: LatLngPoint & { heading?: number } }>;
  activeDroneId?: string;
  onSelectDrone?: (droneId: string) => void;
}) {
  return (
    <>
      {fleet.map((drone) => {
        const position = drone.position;
        if (position?.latitude === undefined || position.longitude === undefined) {
          return null;
        }

        const isActive = activeDroneId === drone.drone_id;
        return (
          <Marker
            key={drone.drone_id}
            position={toLatLngExpression(position)}
            icon={createMarkerIcon('drone', drone.callsign ?? drone.drone_id, isActive)}
            eventHandlers={
              onSelectDrone
                ? {
                    click: () => onSelectDrone(drone.drone_id),
                  }
                : undefined
            }
          >
            <Tooltip sticky>{drone.callsign ?? drone.drone_id}</Tooltip>
          </Marker>
        );
      })}
    </>
  );
});

const VehicleLayer = memo(function VehicleLayer({
  vehicle,
}: {
  vehicle?: LatLngPoint & { heading?: number };
}) {
  const vehicleHeading = typeof vehicle?.heading === 'number' ? vehicle.heading : undefined;

  if (vehicle?.latitude === undefined || vehicle?.longitude === undefined) {
    return null;
  }

  return (
    <Pane name="vehicle-layer" style={{ zIndex: 460 }}>
      <Marker position={toLatLngExpression(vehicle)} icon={createMarkerIcon('vehicle', 'AIR', true)}>
        <Tooltip sticky>Aircraft</Tooltip>
      </Marker>
      {vehicleHeading !== undefined ? (
        <Polyline
          positions={[
            [vehicle.latitude, vehicle.longitude],
            [
              vehicle.latitude + Math.cos((vehicleHeading * Math.PI) / 180) * 0.0018,
              vehicle.longitude + Math.sin((vehicleHeading * Math.PI) / 180) * 0.0018,
            ],
          ]}
          pathOptions={{ color: '#ff6d6d', weight: 4, opacity: 0.9 }}
        />
      ) : null}
    </Pane>
  );
});

function FieldMapInner({
  center,
  boundary,
  waypoints,
  breadcrumb,
  surveyPreview,
  vehicle,
  fleet = [],
  coverage = [],
  aerialOverlay,
  mode,
  followViewport = true,
  onMapClick,
  onBoundaryChange,
  onWaypointsChange,
  activeDroneId,
  onSelectDrone,
}: FieldMapProps) {
  const boundaryCoords = useMemo(() => boundary.map(toLatLngTuple), [boundary]);
  const routeCoords = useMemo(() => waypoints.map(toLatLngTuple), [waypoints]);
  const breadcrumbCoords = useMemo(
    () =>
      breadcrumb.reduce<Array<[number, number]>>((acc, point) => {
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
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Street">
            <Pane name="basemap-street" style={{ zIndex: 100 }}>
              <TileLayer
                attribution="&copy; OpenStreetMap contributors"
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
            </Pane>
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Satellite">
            <Pane name="basemap-satellite" style={{ zIndex: 100 }}>
              <TileLayer
                attribution="Tiles &copy; Esri"
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              />
            </Pane>
          </LayersControl.BaseLayer>
        </LayersControl>

        {followViewport ? <MapViewportSync center={center} followViewport={followViewport} /> : null}
        <MapInteractionLayer onMapClick={onMapClick} />

        {aerialOverlay ? (
          <Pane name="imagery-overlay" style={{ zIndex: 220 }}>
            <ImageOverlay url={aerialOverlay.url} bounds={aerialOverlay.bounds} opacity={aerialOverlay.opacity ?? 0.72} />
          </Pane>
        ) : null}

        {coverage.length ? (
          <Pane name="coverage-overlay" style={{ zIndex: 260 }}>
            {coverage.map((point, index) => {
              const opacity = Math.max(0.06, Math.min(point.intensity ?? 0.16, 0.34));
              const radius = point.radius ?? 22;
              return (
                <Circle
                  key={`coverage-${index}-${point.latitude}-${point.longitude}`}
                  center={toLatLngExpression(point)}
                  radius={radius}
                  pathOptions={{
                    color: '#ff6d6d',
                    fillColor: index % 3 === 0 ? '#ff6d6d' : index % 3 === 1 ? '#ffb000' : '#2fd6c4',
                    fillOpacity: opacity,
                    opacity,
                    weight: 0,
                  }}
                >
                  {point.label ? <Tooltip sticky>{point.label}</Tooltip> : null}
                </Circle>
              );
            })}
          </Pane>
        ) : null}

        {boundaryCoords.length >= 3 ? (
          <Pane name="boundary-overlay" style={{ zIndex: 300 }}>
            <Polygon
              positions={boundaryCoords}
              pathOptions={{ color: '#ffb000', fillColor: '#ffb000', fillOpacity: 0.12, weight: 2 }}
            >
              <Tooltip sticky>Draft field boundary</Tooltip>
            </Polygon>
          </Pane>
        ) : null}

        {surveyPreview.map((segment, index) => (
          <Pane key={`survey-${index}`} name={`survey-${index}`} style={{ zIndex: 310 }}>
            <Polyline
              positions={segment.map(toLatLngTuple)}
              pathOptions={{ color: '#2fd6c4', weight: 1, dashArray: '5 8', opacity: 0.55 }}
            />
          </Pane>
        ))}

        {routeCoords.length >= 2 ? (
          <Pane name="route-line" style={{ zIndex: 320 }}>
            <Polyline
              positions={routeCoords}
              pathOptions={{ color: '#6ea8fe', weight: 3, opacity: 0.7, dashArray: '2 6' }}
            >
              <Tooltip sticky>Waypoints route</Tooltip>
            </Polyline>
          </Pane>
        ) : null}

        {breadcrumbCoords.length >= 2 ? (
          <Pane name="breadcrumb-line" style={{ zIndex: 330 }}>
            <Polyline positions={breadcrumbCoords} pathOptions={{ color: '#6ea8fe', weight: 4, opacity: 0.75 }}>
              <Tooltip sticky>Recent telemetry breadcrumb</Tooltip>
            </Polyline>
          </Pane>
        ) : null}

        {boundary.map((point, index) => (
          <Marker
            key={`boundary-${index}`}
            position={toLatLngExpression(point)}
            draggable
            icon={createMarkerIcon('boundary', String(index + 1))}
            eventHandlers={{
              dragend: (event) => {
                const marker = event.target as LeafletMarker;
                const nextLatLng = marker.getLatLng();
                const nextBoundary = boundary.slice();
                nextBoundary[index] = buildPoint(nextLatLng.lat, nextLatLng.lng);
                onBoundaryChange(nextBoundary);
              },
              contextmenu: () => {
                if (boundary.length <= 3) {
                  return;
                }

                onBoundaryChange(boundary.filter((_, currentIndex) => currentIndex !== index));
              },
            }}
          >
            <Tooltip sticky direction="top" offset={[0, -10]}>
              Boundary vertex {index + 1}
            </Tooltip>
          </Marker>
        ))}

        {waypoints.map((waypoint, index) => (
          <Marker
            key={waypoint.id}
            position={toLatLngExpression(waypoint)}
            draggable
            icon={createMarkerIcon('waypoint', String(index + 1))}
            eventHandlers={{
              dragend: (event) => {
                const marker = event.target as LeafletMarker;
                const nextLatLng = marker.getLatLng();
                const nextWaypoints = waypoints.slice();
                nextWaypoints[index] = {
                  ...waypoint,
                  latitude: nextLatLng.lat,
                  longitude: nextLatLng.lng,
                };
                onWaypointsChange(nextWaypoints);
              },
              contextmenu: () => {
                onWaypointsChange(waypoints.filter((_, currentIndex) => currentIndex !== index));
              },
            }}
          >
            <Tooltip sticky direction="top" offset={[0, -10]}>
              {waypoint.label}
            </Tooltip>
            <Popup>
              <strong>{waypoint.label}</strong>
              <div>
                {waypoint.latitude.toFixed(5)}, {waypoint.longitude.toFixed(5)}
              </div>
            </Popup>
          </Marker>
        ))}

        <FleetMarkerLayer fleet={fleet} activeDroneId={activeDroneId} onSelectDrone={onSelectDrone} />

        <VehicleLayer vehicle={vehicle} />
      </MapContainer>

      <div className="map-hud">
        <span>Mode</span>
        <strong>{mode}</strong>
        <span>Layer</span>
        <strong>{aerialOverlay ? 'imagery loaded' : 'street / satellite'}</strong>
      </div>
    </div>
  );
}

function areEqual(prev: FieldMapProps, next: FieldMapProps) {
  return (
    prev.center[0] === next.center[0] &&
    prev.center[1] === next.center[1] &&
    prev.boundary === next.boundary &&
    prev.waypoints === next.waypoints &&
    prev.breadcrumb === next.breadcrumb &&
    prev.surveyPreview === next.surveyPreview &&
    prev.vehicle === next.vehicle &&
    prev.fleet === next.fleet &&
    prev.coverage === next.coverage &&
    prev.aerialOverlay === next.aerialOverlay &&
    prev.mode === next.mode &&
    prev.followViewport === next.followViewport &&
    prev.onMapClick === next.onMapClick &&
    prev.onBoundaryChange === next.onBoundaryChange &&
    prev.onWaypointsChange === next.onWaypointsChange &&
    prev.activeDroneId === next.activeDroneId &&
    prev.onSelectDrone === next.onSelectDrone
  );
}

export const FieldMap = memo(function FieldMap(props: FieldMapProps) {
  return <FieldMapInner {...props} />;
}, areEqual);
