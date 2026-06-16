"""
Mission Planner
Handles waypoint missions, field boundaries, and autonomous flight planning
"""

import logging
import json
import os
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class MissionItemType(Enum):
    """Types of mission items"""
    WAYPOINT = "waypoint"
    LOITER = "loiter"
    LAND = "land"
    TAKEOFF = "takeoff"
    SPRAY_START = "spray_start"
    SPRAY_STOP = "spray_stop"


class AltitudeFrame(Enum):
    """Altitude reference frames for uploaded mission items."""
    RELATIVE = "relative"
    TERRAIN = "terrain"


class ObstacleAvoidanceMode(Enum):
    """Autopilot obstacle avoidance strategy requested by the companion."""
    DISABLED = "disabled"
    SIMPLE = "simple"
    BENDY_RULER = "bendy_ruler"


class TerrainSource(Enum):
    """Terrain following altitude data source."""
    RANGEFINDER = "rangefinder"
    TERRAIN_DATABASE = "terrain_database"


@dataclass
class ObstacleAvoidanceConfig:
    """Configurable obstacle avoidance settings for ArduPilot-backed behavior."""
    enabled: bool = False
    mode: ObstacleAvoidanceMode = ObstacleAvoidanceMode.SIMPLE
    margin_meters: float = 2.0
    lookahead_meters: float = 5.0
    backup_speed_mps: float = 0.0
    min_altitude_meters: float = 0.0
    proximity_type: Optional[int] = 4
    behavior: str = "slide"
    bendy_ruler_type: str = "horizontal"
    obstacle_database_size: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "mode": self.mode.value,
            "margin_meters": self.margin_meters,
            "lookahead_meters": self.lookahead_meters,
            "backup_speed_mps": self.backup_speed_mps,
            "min_altitude_meters": self.min_altitude_meters,
            "proximity_type": self.proximity_type,
            "behavior": self.behavior,
            "bendy_ruler_type": self.bendy_ruler_type,
            "obstacle_database_size": self.obstacle_database_size,
        }

    @staticmethod
    def from_dict(data: Optional[dict]) -> 'ObstacleAvoidanceConfig':
        data = data or {}
        mode_value = data.get("mode", ObstacleAvoidanceMode.SIMPLE.value)
        try:
            mode = ObstacleAvoidanceMode(str(mode_value).strip().lower())
        except ValueError:
            mode = ObstacleAvoidanceMode.SIMPLE

        return ObstacleAvoidanceConfig(
            enabled=bool(data.get("enabled", False)),
            mode=mode,
            margin_meters=float(data.get("margin_meters", 2.0)),
            lookahead_meters=float(data.get("lookahead_meters", 5.0)),
            backup_speed_mps=float(data.get("backup_speed_mps", 0.0)),
            min_altitude_meters=float(data.get("min_altitude_meters", 0.0)),
            proximity_type=data.get("proximity_type", 4),
            behavior=str(data.get("behavior", "slide")).strip().lower(),
            bendy_ruler_type=str(data.get("bendy_ruler_type", "horizontal")).strip().lower(),
            obstacle_database_size=data.get("obstacle_database_size"),
        )


@dataclass
class TerrainFollowingConfig:
    """Configurable terrain-following settings for autonomous navigation."""
    enabled: bool = False
    source: TerrainSource = TerrainSource.RANGEFINDER
    min_agl_meters: float = 2.0
    max_agl_meters: float = 120.0
    target_agl_meters: Optional[float] = None
    use_rangefinder_for_waypoints: bool = True
    rtl_terrain_enabled: bool = False
    terrain_spacing_meters: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "source": self.source.value,
            "min_agl_meters": self.min_agl_meters,
            "max_agl_meters": self.max_agl_meters,
            "target_agl_meters": self.target_agl_meters,
            "use_rangefinder_for_waypoints": self.use_rangefinder_for_waypoints,
            "rtl_terrain_enabled": self.rtl_terrain_enabled,
            "terrain_spacing_meters": self.terrain_spacing_meters,
        }

    @staticmethod
    def from_dict(data: Optional[dict]) -> 'TerrainFollowingConfig':
        data = data or {}
        source_value = data.get("source", TerrainSource.RANGEFINDER.value)
        try:
            source = TerrainSource(str(source_value).strip().lower())
        except ValueError:
            source = TerrainSource.RANGEFINDER

        return TerrainFollowingConfig(
            enabled=bool(data.get("enabled", False)),
            source=source,
            min_agl_meters=float(data.get("min_agl_meters", 2.0)),
            max_agl_meters=float(data.get("max_agl_meters", 120.0)),
            target_agl_meters=data.get("target_agl_meters"),
            use_rangefinder_for_waypoints=bool(data.get("use_rangefinder_for_waypoints", True)),
            rtl_terrain_enabled=bool(data.get("rtl_terrain_enabled", False)),
            terrain_spacing_meters=data.get("terrain_spacing_meters"),
        )


@dataclass
class NavigationConfig:
    """Mission navigation features managed by the companion app."""
    obstacle_avoidance: ObstacleAvoidanceConfig = None
    terrain_following: TerrainFollowingConfig = None

    def __post_init__(self):
        if self.obstacle_avoidance is None:
            self.obstacle_avoidance = ObstacleAvoidanceConfig()
        if self.terrain_following is None:
            self.terrain_following = TerrainFollowingConfig()

    def to_dict(self) -> dict:
        return {
            "obstacle_avoidance": self.obstacle_avoidance.to_dict(),
            "terrain_following": self.terrain_following.to_dict(),
        }

    @staticmethod
    def from_dict(data: Optional[dict]) -> 'NavigationConfig':
        data = data or {}
        return NavigationConfig(
            obstacle_avoidance=ObstacleAvoidanceConfig.from_dict(
                data.get("obstacle_avoidance")
            ),
            terrain_following=TerrainFollowingConfig.from_dict(
                data.get("terrain_following")
            ),
        )


@dataclass
class GeoPoint:
    """GPS coordinate point"""
    latitude: float
    longitude: float
    altitude: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> 'GeoPoint':
        return GeoPoint(**data)


@dataclass
class MissionItem:
    """Single mission item"""
    sequence: int
    type: MissionItemType
    location: GeoPoint
    param1: float = 0.0  # Generic parameter 1
    param2: float = 0.0  # Generic parameter 2
    param3: float = 0.0  # Generic parameter 3
    param4: float = 0.0  # Generic parameter 4
    altitude_frame: AltitudeFrame = AltitudeFrame.RELATIVE

    def to_dict(self) -> dict:
        data = asdict(self)
        data['type'] = self.type.value
        data['location'] = self.location.to_dict()
        data['altitude_frame'] = self.altitude_frame.value
        return data

    @staticmethod
    def from_dict(data: dict) -> 'MissionItem':
        data = data.copy()
        data['type'] = MissionItemType(data['type'])
        data['location'] = GeoPoint.from_dict(data['location'])
        data['altitude_frame'] = AltitudeFrame(
            data.get('altitude_frame', AltitudeFrame.RELATIVE.value)
        )
        return MissionItem(**data)


@dataclass
class FieldBoundary:
    """Field boundary polygon"""
    name: str
    vertices: List[GeoPoint]
    altitude: float = 0.0

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'vertices': [v.to_dict() for v in self.vertices],
            'altitude': self.altitude,
        }

    @staticmethod
    def from_dict(data: dict) -> 'FieldBoundary':
        vertices = [GeoPoint.from_dict(v) for v in data['vertices']]
        return FieldBoundary(
            name=data['name'],
            vertices=vertices,
            altitude=data.get('altitude', 0.0)
        )

    def point_in_boundary(self, point: GeoPoint) -> bool:
        """Check if point is within boundary (simplified)"""
        if len(self.vertices) < 3:
            return False
        
        # Simple point-in-polygon using ray casting algorithm
        x, y = point.longitude, point.latitude
        n = len(self.vertices)
        inside = False
        
        j = n - 1
        for i in range(n):
            xi, yi = self.vertices[i].longitude, self.vertices[i].latitude
            xj, yj = self.vertices[j].longitude, self.vertices[j].latitude
            
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        
        return inside


class MissionPlanner:
    """Plans and manages drone missions"""

    def __init__(
        self,
        max_waypoints: int = 100,
        storage_file: Optional[str] = None,
        navigation_config: Optional[NavigationConfig] = None,
    ):
        self.max_waypoints = max_waypoints
        self.storage_file = storage_file
        self.navigation_config = navigation_config or NavigationConfig()
        self.mission_items: List[MissionItem] = []
        self.field_boundaries: Dict[str, FieldBoundary] = {}
        self.current_mission_index = -1
        self.is_executing = False
        if self.storage_file:
            storage_dir = os.path.dirname(self.storage_file)
            if storage_dir:
                os.makedirs(storage_dir, exist_ok=True)
            self._load_from_storage()

    def _state_to_dict(self) -> Dict:
        return {
            'items': [item.to_dict() for item in self.mission_items],
            'boundaries': {
                name: boundary.to_dict()
                for name, boundary in self.field_boundaries.items()
            },
            'current_mission_index': self.current_mission_index,
            'is_executing': self.is_executing,
            'navigation_config': self.navigation_config.to_dict(),
        }

    def _apply_state(self, mission_data: Dict):
        self.mission_items.clear()
        self.field_boundaries.clear()

        for item_data in mission_data.get('items', []):
            item = MissionItem.from_dict(item_data)
            self.mission_items.append(item)

        for name, boundary_data in mission_data.get('boundaries', {}).items():
            boundary = FieldBoundary.from_dict(boundary_data)
            self.field_boundaries[name] = boundary

        self.current_mission_index = int(mission_data.get('current_mission_index', -1))
        self.is_executing = bool(mission_data.get('is_executing', False))
        self.navigation_config = NavigationConfig.from_dict(
            mission_data.get('navigation_config', self.navigation_config.to_dict())
        )

    def _load_from_storage(self):
        if not self.storage_file or not os.path.exists(self.storage_file):
            return

        try:
            with open(self.storage_file, 'r') as f:
                self._apply_state(json.load(f))
            logger.info(f"Mission state restored from {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to restore mission state: {str(e)}")

    def _persist(self):
        if not self.storage_file:
            return

        try:
            storage_dir = os.path.dirname(self.storage_file)
            if storage_dir:
                os.makedirs(storage_dir, exist_ok=True)

            temp_file = f"{self.storage_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(self._state_to_dict(), f, indent=2)
            os.replace(temp_file, self.storage_file)
        except Exception as e:
            logger.error(f"Failed to persist mission state: {str(e)}")

    # Waypoint Management

    def add_waypoint(self, 
                    latitude: float, 
                    longitude: float, 
                    altitude: float,
                    sequence: Optional[int] = None,
                    altitude_frame: Optional[str] = None) -> bool:
        """
        Add waypoint to mission
        
        Args:
            latitude: Target latitude
            longitude: Target longitude
            altitude: Target altitude in meters
            sequence: Optional sequence number (auto if None)
            altitude_frame: Optional altitude reference frame
            
        Returns:
            bool: Success
        """
        if len(self.mission_items) >= self.max_waypoints:
            logger.error(f"Mission full: max {self.max_waypoints} waypoints")
            return False
        
        seq = sequence if sequence is not None else len(self.mission_items)
        location = GeoPoint(latitude, longitude, altitude)
        item = MissionItem(
            seq,
            MissionItemType.WAYPOINT,
            location,
            altitude_frame=self._resolve_altitude_frame(altitude_frame),
        )
        
        self.mission_items.append(item)
        logger.info(f"Waypoint added: {latitude}, {longitude}, {altitude}m")
        self._persist()
        
        return True

    def add_loiter_point(self,
                        latitude: float,
                        longitude: float,
                        altitude: float,
                        radius: float = 50.0,
                        turns: float = 0.0) -> bool:
        """
        Add loiter (circle) point
        
        Args:
            latitude: Center latitude
            longitude: Center longitude
            altitude: Altitude in meters
            radius: Loiter radius in meters
            turns: Number of turns (0 = infinite)
            
        Returns:
            bool: Success
        """
        if len(self.mission_items) >= self.max_waypoints:
            logger.error(f"Mission full")
            return False
        
        seq = len(self.mission_items)
        location = GeoPoint(latitude, longitude, altitude)
        item = MissionItem(
            seq, MissionItemType.LOITER, location,
            param1=radius,
            param2=turns,
            altitude_frame=self._resolve_altitude_frame(None),
        )
        
        self.mission_items.append(item)
        logger.info(f"Loiter point added at {latitude}, {longitude}")
        self._persist()
        
        return True

    def add_spray_zone(self,
                      field_boundary: FieldBoundary,
                      altitude: float,
                      spacing: float = 10.0) -> bool:
        """
        Generate spray mission over field boundary
        
        Args:
            field_boundary: Field polygon
            altitude: Spray altitude
            spacing: Distance between passes (meters)
            
        Returns:
            bool: Success
        """
        if not field_boundary.vertices or len(field_boundary.vertices) < 3:
            logger.error("Invalid field boundary")
            return False
        
        # Get boundary bounds
        lats = [v.latitude for v in field_boundary.vertices]
        lons = [v.longitude for v in field_boundary.vertices]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        
        # Generate parallel passes (simplified - real implementation would be more complex)
        lat_passes = int((max_lat - min_lat) / (spacing / 111000)) + 1
        
        for i in range(lat_passes):
            lat = min_lat + i * (spacing / 111000)
            
            # Start spray
            self.add_mission_item_generic(
                MissionItemType.SPRAY_START,
                lat, min_lon, altitude
            )
            
            # Waypoint across field
            self.add_waypoint(lat, max_lon, altitude)
            
            # Stop spray
            self.add_mission_item_generic(
                MissionItemType.SPRAY_STOP,
                lat, max_lon, altitude
            )
        
        logger.info(f"Spray mission generated over {field_boundary.name}")
        return True

    def add_mission_item_generic(self,
                                item_type: MissionItemType,
                                latitude: float,
                                longitude: float,
                                altitude: float,
                                **params) -> bool:
        """
        Add generic mission item
        
        Args:
            item_type: Type of mission item
            latitude: Latitude
            longitude: Longitude
            altitude: Altitude
            **params: Additional parameters (param1, param2, etc.)
            
        Returns:
            bool: Success
        """
        if len(self.mission_items) >= self.max_waypoints:
            logger.error("Mission full")
            return False
        
        seq = len(self.mission_items)
        location = GeoPoint(latitude, longitude, altitude)
        
        item = MissionItem(seq, item_type, location)
        item.param1 = params.get('param1', 0.0)
        item.param2 = params.get('param2', 0.0)
        item.param3 = params.get('param3', 0.0)
        item.param4 = params.get('param4', 0.0)
        item.altitude_frame = self._resolve_altitude_frame(params.get('altitude_frame'))
        
        self.mission_items.append(item)
        self._persist()
        return True

    def _resolve_altitude_frame(self, altitude_frame: Optional[str]) -> AltitudeFrame:
        if altitude_frame:
            return AltitudeFrame(str(altitude_frame).strip().lower())
        if self.navigation_config.terrain_following.enabled:
            return AltitudeFrame.TERRAIN
        return AltitudeFrame.RELATIVE

    def remove_waypoint(self, index: int) -> bool:
        """Remove waypoint by index"""
        if 0 <= index < len(self.mission_items):
            del self.mission_items[index]
            # Re-sequence
            for i, item in enumerate(self.mission_items):
                item.sequence = i
            if self.current_mission_index > index:
                self.current_mission_index -= 1
            if self.current_mission_index >= len(self.mission_items):
                self.current_mission_index = len(self.mission_items) - 1
            logger.info(f"Waypoint {index} removed")
            self._persist()
            return True
        return False

    def clear_mission(self):
        """Clear all mission items"""
        self.mission_items.clear()
        self.current_mission_index = -1
        self.is_executing = False
        logger.info("Mission cleared")
        self._persist()

    def get_mission(self) -> List[Dict]:
        """Get current mission as list of dicts"""
        return [item.to_dict() for item in self.mission_items]

    def get_navigation_config(self) -> Dict:
        """Return navigation feature configuration."""
        return self.navigation_config.to_dict()

    def update_navigation_config(
        self,
        obstacle_avoidance: Optional[dict] = None,
        terrain_following: Optional[dict] = None,
    ) -> Dict:
        """Update configurable navigation features and persist the mission state."""
        current = self.navigation_config.to_dict()
        if obstacle_avoidance is not None:
            current["obstacle_avoidance"].update(obstacle_avoidance)
        if terrain_following is not None:
            current["terrain_following"].update(terrain_following)

        updated = NavigationConfig.from_dict(current)
        self._validate_navigation_config(updated)
        self.navigation_config = updated
        self._persist()
        return self.get_navigation_config()

    def _validate_navigation_config(self, navigation_config: NavigationConfig):
        terrain = navigation_config.terrain_following
        if terrain.min_agl_meters < 0:
            raise ValueError("terrain min_agl_meters must be non-negative")
        if terrain.max_agl_meters <= terrain.min_agl_meters:
            raise ValueError("terrain max_agl_meters must be greater than min_agl_meters")
        if terrain.target_agl_meters is not None:
            target_agl = float(terrain.target_agl_meters)
            if target_agl < terrain.min_agl_meters or target_agl > terrain.max_agl_meters:
                raise ValueError("terrain target_agl_meters must be within min/max AGL limits")
            terrain.target_agl_meters = target_agl
        if terrain.terrain_spacing_meters is not None:
            terrain_spacing = float(terrain.terrain_spacing_meters)
            if terrain_spacing <= 0:
                raise ValueError("terrain_spacing_meters must be positive")
            terrain.terrain_spacing_meters = terrain_spacing

        avoidance = navigation_config.obstacle_avoidance
        if avoidance.margin_meters < 0:
            raise ValueError("obstacle margin_meters must be non-negative")
        if avoidance.lookahead_meters <= 0:
            raise ValueError("obstacle lookahead_meters must be positive")
        if avoidance.backup_speed_mps < 0:
            raise ValueError("obstacle backup_speed_mps must be non-negative")
        if avoidance.min_altitude_meters < 0:
            raise ValueError("obstacle min_altitude_meters must be non-negative")
        if avoidance.proximity_type is not None:
            avoidance.proximity_type = int(avoidance.proximity_type)
        if avoidance.obstacle_database_size is not None:
            avoidance.obstacle_database_size = int(avoidance.obstacle_database_size)
            if avoidance.obstacle_database_size < 0:
                raise ValueError("obstacle_database_size must be non-negative")
        if avoidance.behavior not in {"stop", "slide"}:
            raise ValueError("obstacle behavior must be stop or slide")
        if avoidance.bendy_ruler_type not in {"horizontal", "vertical"}:
            raise ValueError("bendy_ruler_type must be horizontal or vertical")

    def get_state(self) -> Dict:
        """Get complete mission state for API clients."""
        return {
            'waypoints': self.get_mission(),
            'field_boundaries': self.get_field_boundaries(),
            'statistics': self.get_statistics(),
            'execution': {
                'is_executing': self.is_executing,
                'current_mission_index': self.current_mission_index,
            },
            'navigation_config': self.get_navigation_config(),
        }

    # Field Boundary Management

    def add_field_boundary(self, boundary: FieldBoundary) -> bool:
        """Add field boundary"""
        if len(boundary.vertices) < 3:
            logger.error("Boundary must have at least 3 vertices")
            return False
        
        self.field_boundaries[boundary.name] = boundary
        logger.info(f"Field boundary '{boundary.name}' added")
        self._persist()
        return True

    def get_field_boundaries(self) -> Dict[str, Dict]:
        """Get all field boundaries"""
        return {name: boundary.to_dict() 
                for name, boundary in self.field_boundaries.items()}

    def get_field_boundary(self, name: str) -> Optional[FieldBoundary]:
        """Get specific field boundary"""
        return self.field_boundaries.get(name)

    def remove_field_boundary(self, name: str) -> bool:
        """Remove field boundary by name"""
        if name not in self.field_boundaries:
            return False

        del self.field_boundaries[name]
        logger.info(f"Field boundary '{name}' removed")
        self._persist()
        return True

    # Mission Execution Tracking

    def start_mission(self) -> bool:
        """Start mission execution"""
        if not self.mission_items:
            logger.error("No mission to execute")
            return False
        
        self.is_executing = True
        self.current_mission_index = 0
        logger.info(f"Mission started with {len(self.mission_items)} items")
        self._persist()
        return True

    def next_waypoint(self) -> Optional[MissionItem]:
        """Get next waypoint"""
        if not self.is_executing or self.current_mission_index >= len(self.mission_items):
            self.is_executing = False
            self._persist()
            return None
        
        item = self.mission_items[self.current_mission_index]
        self.current_mission_index += 1
        self._persist()
        
        return item

    def pause_mission(self):
        """Pause mission execution"""
        self.is_executing = False
        logger.info("Mission paused")
        self._persist()

    def resume_mission(self):
        """Resume mission execution"""
        if self.current_mission_index >= 0:
            self.is_executing = True
            logger.info("Mission resumed")
            self._persist()

    def abort_mission(self):
        """Abort mission execution"""
        self.is_executing = False
        self.current_mission_index = -1
        logger.info("Mission aborted")
        self._persist()

    # Serialization

    def save_mission(self, filename: str) -> bool:
        """Save mission to file"""
        try:
            with open(filename, 'w') as f:
                json.dump(self._state_to_dict(), f, indent=2)
            
            logger.info(f"Mission saved to {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save mission: {str(e)}")
            return False

    def load_mission(self, filename: str) -> bool:
        """Load mission from file"""
        try:
            with open(filename, 'r') as f:
                mission_data = json.load(f)
            
            self._apply_state(mission_data)
            self._persist()
            
            logger.info(f"Mission loaded from {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load mission: {str(e)}")
            return False

    def get_statistics(self) -> Dict:
        """Get mission statistics"""
        if not self.mission_items:
            return {}
        
        waypoints = [item for item in self.mission_items 
                    if item.type == MissionItemType.WAYPOINT]
        
        altitudes = [item.location.altitude for item in waypoints]
        
        return {
            'total_item_count': len(self.mission_items),
            'waypoint_count': len(waypoints),
            'field_boundary_count': len(self.field_boundaries),
            'min_altitude': min(altitudes) if altitudes else 0,
            'max_altitude': max(altitudes) if altitudes else 0,
            'is_executing': self.is_executing,
            'current_mission_index': self.current_mission_index,
        }
