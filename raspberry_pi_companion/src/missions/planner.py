"""
Mission Planner
Handles waypoint missions, field boundaries, and autonomous flight planning
"""

import logging
import json
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

    def to_dict(self) -> dict:
        data = asdict(self)
        data['type'] = self.type.value
        data['location'] = self.location.to_dict()
        return data

    @staticmethod
    def from_dict(data: dict) -> 'MissionItem':
        data['type'] = MissionItemType(data['type'])
        data['location'] = GeoPoint.from_dict(data['location'])
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

    def __init__(self, max_waypoints: int = 100):
        self.max_waypoints = max_waypoints
        self.mission_items: List[MissionItem] = []
        self.field_boundaries: Dict[str, FieldBoundary] = {}
        self.current_mission_index = -1
        self.is_executing = False

    # Waypoint Management

    def add_waypoint(self, 
                    latitude: float, 
                    longitude: float, 
                    altitude: float,
                    sequence: Optional[int] = None) -> bool:
        """
        Add waypoint to mission
        
        Args:
            latitude: Target latitude
            longitude: Target longitude
            altitude: Target altitude in meters
            sequence: Optional sequence number (auto if None)
            
        Returns:
            bool: Success
        """
        if len(self.mission_items) >= self.max_waypoints:
            logger.error(f"Mission full: max {self.max_waypoints} waypoints")
            return False
        
        seq = sequence if sequence is not None else len(self.mission_items)
        location = GeoPoint(latitude, longitude, altitude)
        item = MissionItem(seq, MissionItemType.WAYPOINT, location)
        
        self.mission_items.append(item)
        logger.info(f"Waypoint added: {latitude}, {longitude}, {altitude}m")
        
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
            param1=radius, param2=turns
        )
        
        self.mission_items.append(item)
        logger.info(f"Loiter point added at {latitude}, {longitude}")
        
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
        
        self.mission_items.append(item)
        return True

    def remove_waypoint(self, index: int) -> bool:
        """Remove waypoint by index"""
        if 0 <= index < len(self.mission_items):
            del self.mission_items[index]
            # Re-sequence
            for i, item in enumerate(self.mission_items):
                item.sequence = i
            logger.info(f"Waypoint {index} removed")
            return True
        return False

    def clear_mission(self):
        """Clear all mission items"""
        self.mission_items.clear()
        self.current_mission_index = -1
        self.is_executing = False
        logger.info("Mission cleared")

    def get_mission(self) -> List[Dict]:
        """Get current mission as list of dicts"""
        return [item.to_dict() for item in self.mission_items]

    # Field Boundary Management

    def add_field_boundary(self, boundary: FieldBoundary) -> bool:
        """Add field boundary"""
        if len(boundary.vertices) < 3:
            logger.error("Boundary must have at least 3 vertices")
            return False
        
        self.field_boundaries[boundary.name] = boundary
        logger.info(f"Field boundary '{boundary.name}' added")
        return True

    def get_field_boundaries(self) -> Dict[str, Dict]:
        """Get all field boundaries"""
        return {name: boundary.to_dict() 
                for name, boundary in self.field_boundaries.items()}

    def get_field_boundary(self, name: str) -> Optional[FieldBoundary]:
        """Get specific field boundary"""
        return self.field_boundaries.get(name)

    # Mission Execution Tracking

    def start_mission(self) -> bool:
        """Start mission execution"""
        if not self.mission_items:
            logger.error("No mission to execute")
            return False
        
        self.is_executing = True
        self.current_mission_index = 0
        logger.info(f"Mission started with {len(self.mission_items)} items")
        return True

    def next_waypoint(self) -> Optional[MissionItem]:
        """Get next waypoint"""
        if not self.is_executing or self.current_mission_index >= len(self.mission_items):
            self.is_executing = False
            return None
        
        item = self.mission_items[self.current_mission_index]
        self.current_mission_index += 1
        
        return item

    def pause_mission(self):
        """Pause mission execution"""
        self.is_executing = False
        logger.info("Mission paused")

    def resume_mission(self):
        """Resume mission execution"""
        if self.current_mission_index >= 0:
            self.is_executing = True
            logger.info("Mission resumed")

    def abort_mission(self):
        """Abort mission execution"""
        self.is_executing = False
        self.current_mission_index = -1
        logger.info("Mission aborted")

    # Serialization

    def save_mission(self, filename: str) -> bool:
        """Save mission to file"""
        try:
            mission_data = {
                'items': [item.to_dict() for item in self.mission_items],
                'boundaries': {name: boundary.to_dict() 
                              for name, boundary in self.field_boundaries.items()}
            }
            
            with open(filename, 'w') as f:
                json.dump(mission_data, f, indent=2)
            
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
            
            self.mission_items.clear()
            self.field_boundaries.clear()
            
            for item_data in mission_data.get('items', []):
                item = MissionItem.from_dict(item_data)
                self.mission_items.append(item)
            
            for name, boundary_data in mission_data.get('boundaries', {}).items():
                boundary = FieldBoundary.from_dict(boundary_data)
                self.field_boundaries[name] = boundary
            
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
            'total_items': len(self.mission_items),
            'waypoints': len(waypoints),
            'boundaries': len(self.field_boundaries),
            'min_altitude': min(altitudes) if altitudes else 0,
            'max_altitude': max(altitudes) if altitudes else 0,
            'is_executing': self.is_executing,
            'current_index': self.current_mission_index,
        }
