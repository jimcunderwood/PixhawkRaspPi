import type { FleetConfig } from '../types/fleet';
import type { LatLngPoint, MissionWaypoint } from '../types/base';
import { buildSurveyPreview, computePolygonCenter, makeMissionWaypoint } from './planning';

export type MissionRouteDraft = {
  id: string;
  name: string;
  boundary: LatLngPoint[];
  waypoints: MissionWaypoint[];
  created_at: string;
  updated_at: string;
};

export type MissionUploadResult = {
  boundary_uploaded: boolean;
  waypoint_count: number;
  pixhawk_uploaded?: boolean;
};

function nowIso() {
  return new Date().toISOString();
}

export function createMissionRouteDraft(name: string, boundary: LatLngPoint[] = [], waypoints: MissionWaypoint[] = []): MissionRouteDraft {
  const timestamp = nowIso();
  return {
    id: `route-${Date.now()}`,
    name,
    boundary,
    waypoints,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

export function updateDraftBoundary(draft: MissionRouteDraft, boundary: LatLngPoint[]): MissionRouteDraft {
  return {
    ...draft,
    boundary,
    updated_at: nowIso(),
  };
}

export function updateDraftWaypoints(draft: MissionRouteDraft, waypoints: MissionWaypoint[]): MissionRouteDraft {
  return {
    ...draft,
    waypoints,
    updated_at: nowIso(),
  };
}

export function appendDraftWaypoint(draft: MissionRouteDraft, point: LatLngPoint): MissionRouteDraft {
  return updateDraftWaypoints(
    draft,
    [...draft.waypoints, makeMissionWaypoint(point, draft.waypoints.length)],
  );
}

export function draftCenter(draft: MissionRouteDraft): LatLngPoint | undefined {
  return computePolygonCenter(draft.boundary);
}

export function draftSurveyPreview(draft: MissionRouteDraft): LatLngPoint[][] {
  return buildSurveyPreview(draft.boundary);
}

export function loadStoredDraft(storageKey: string): MissionRouteDraft | undefined {
  const raw = globalThis.localStorage?.getItem(storageKey);
  if (!raw) {
    return undefined;
  }

  try {
    return JSON.parse(raw) as MissionRouteDraft;
  } catch {
    return undefined;
  }
}

export function saveStoredDraft(storageKey: string, draft: MissionRouteDraft): void {
  globalThis.localStorage?.setItem(storageKey, JSON.stringify(draft));
}

export function buildMissionRouteExport(draft: MissionRouteDraft, fleet?: FleetConfig) {
  return {
    route: draft,
    fleet: fleet ?? null,
    summary: {
      boundary_points: draft.boundary.length,
      waypoint_count: draft.waypoints.length,
      has_polygon: draft.boundary.length >= 3,
    },
  };
}

export function serializeMissionRouteExport(draft: MissionRouteDraft, fleet?: FleetConfig): string {
  return JSON.stringify(buildMissionRouteExport(draft, fleet), null, 2);
}
