import type { LatLngPoint, MissionWaypoint } from '../types/base';

export function makeMissionWaypoint(
  point: LatLngPoint,
  index: number,
): MissionWaypoint {
  return {
    ...point,
    id: `wp-${index + 1}`,
    label: `WP-${String(index + 1).padStart(2, '0')}`,
  };
}

export function computePolygonCenter(points: LatLngPoint[]): LatLngPoint | undefined {
  if (points.length === 0) {
    return undefined;
  }

  const latitude = points.reduce((sum, point) => sum + point.latitude, 0) / points.length;
  const longitude = points.reduce((sum, point) => sum + point.longitude, 0) / points.length;

  return { latitude, longitude };
}

export function buildSurveyPreview(boundary: LatLngPoint[]): LatLngPoint[][] {
  if (boundary.length < 3) {
    return [];
  }

  const latitudes = boundary.map((point) => point.latitude);
  const longitudes = boundary.map((point) => point.longitude);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const minLng = Math.min(...longitudes);
  const maxLng = Math.max(...longitudes);
  const lineCount = Math.max(3, Math.min(8, boundary.length + 1));
  const segments: LatLngPoint[][] = [];

  for (let index = 1; index < lineCount; index += 1) {
    const ratio = index / lineCount;
    const latitude = minLat + (maxLat - minLat) * ratio;
    const wobble = index % 2 === 0 ? 0.00012 : -0.00012;
    segments.push([
      { latitude, longitude: minLng + wobble },
      { latitude, longitude: maxLng - wobble },
    ]);
  }

  return segments;
}
