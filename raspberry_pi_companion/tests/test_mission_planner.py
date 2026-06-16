"""
Basic tests for Companion Computer
"""

import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.missions.planner import (
    AltitudeFrame,
    FieldBoundary,
    GeoPoint,
    MissionPlanner,
    NavigationConfig,
    ObstacleAvoidanceMode,
    TerrainFollowingConfig,
)


class TestMissionPlanner:
    """Test mission planning functionality"""

    def setup_method(self):
        """Setup test fixtures"""
        self.planner = MissionPlanner(max_waypoints=100)

    def test_add_waypoint(self):
        """Test adding waypoints"""
        result = self.planner.add_waypoint(40.7128, -74.0060, 50.0)
        assert result is True
        assert len(self.planner.mission_items) == 1

    def test_add_multiple_waypoints(self):
        """Test adding multiple waypoints"""
        for i in range(5):
            self.planner.add_waypoint(40.7 + i*0.01, -74.0 + i*0.01, 50.0 + i*10)
        
        assert len(self.planner.mission_items) == 5

    def test_waypoint_sequence(self):
        """Test waypoint sequences are correct"""
        self.planner.add_waypoint(40.7, -74.0, 50.0)
        self.planner.add_waypoint(40.8, -74.1, 60.0)
        self.planner.add_waypoint(40.9, -74.2, 70.0)
        
        mission = self.planner.get_mission()
        assert mission[0]['sequence'] == 0
        assert mission[1]['sequence'] == 1
        assert mission[2]['sequence'] == 2

    def test_remove_waypoint(self):
        """Test removing waypoints"""
        self.planner.add_waypoint(40.7, -74.0, 50.0)
        self.planner.add_waypoint(40.8, -74.1, 60.0)
        self.planner.add_waypoint(40.9, -74.2, 70.0)
        
        result = self.planner.remove_waypoint(1)
        assert result is True
        assert len(self.planner.mission_items) == 2

    def test_remove_waypoint_adjusts_execution_index(self):
        """Test removing completed waypoints keeps execution cursor aligned."""
        self.planner.add_waypoint(40.7, -74.0, 50.0)
        self.planner.add_waypoint(40.8, -74.1, 60.0)
        self.planner.add_waypoint(40.9, -74.2, 70.0)
        self.planner.start_mission()
        self.planner.next_waypoint()
        self.planner.next_waypoint()

        assert self.planner.current_mission_index == 2
        assert self.planner.remove_waypoint(0) is True
        assert self.planner.current_mission_index == 1

    def test_max_waypoints_limit(self):
        """Test max waypoint limit"""
        planner = MissionPlanner(max_waypoints=3)
        
        assert planner.add_waypoint(40.7, -74.0, 50.0) is True
        assert planner.add_waypoint(40.8, -74.1, 60.0) is True
        assert planner.add_waypoint(40.9, -74.2, 70.0) is True
        assert planner.add_waypoint(41.0, -74.3, 80.0) is False

    def test_clear_mission(self):
        """Test clearing mission"""
        self.planner.add_waypoint(40.7, -74.0, 50.0)
        self.planner.add_waypoint(40.8, -74.1, 60.0)
        
        self.planner.clear_mission()
        assert len(self.planner.mission_items) == 0

    def test_field_boundary(self):
        """Test field boundary polygon"""
        vertices = [
            GeoPoint(40.7, -74.0),
            GeoPoint(40.7, -74.1),
            GeoPoint(40.8, -74.1),
            GeoPoint(40.8, -74.0),
        ]
        
        boundary = FieldBoundary("Test Field", vertices, altitude=50.0)
        result = self.planner.add_field_boundary(boundary)
        
        assert result is True
        assert "Test Field" in self.planner.field_boundaries

        assert self.planner.remove_field_boundary("Test Field") is True
        assert "Test Field" not in self.planner.field_boundaries
        assert self.planner.remove_field_boundary("Missing Field") is False

    def test_point_in_boundary(self):
        """Test point-in-polygon detection"""
        vertices = [
            GeoPoint(40.7, -74.0),
            GeoPoint(40.7, -74.1),
            GeoPoint(40.8, -74.1),
            GeoPoint(40.8, -74.0),
        ]
        
        boundary = FieldBoundary("Test", vertices)
        
        # Point inside
        inside_point = GeoPoint(40.75, -74.05)
        assert boundary.point_in_boundary(inside_point) is True
        
        # Point outside
        outside_point = GeoPoint(41.0, -75.0)
        assert boundary.point_in_boundary(outside_point) is False

    def test_mission_execution(self):
        """Test mission execution tracking"""
        self.planner.add_waypoint(40.7, -74.0, 50.0)
        self.planner.add_waypoint(40.8, -74.1, 60.0)
        
        assert self.planner.start_mission() is True
        assert self.planner.is_executing is True
        
        item = self.planner.next_waypoint()
        assert item is not None
        assert item.location.latitude == 40.7

    def test_complete_mission_state(self):
        """Test complete mission state for API clients."""
        self.planner.add_waypoint(40.7, -74.0, 50.0)
        self.planner.add_field_boundary(FieldBoundary("South Field", [
            GeoPoint(40.7, -74.0),
            GeoPoint(40.7, -74.1),
            GeoPoint(40.8, -74.1),
            GeoPoint(40.8, -74.0),
        ]))

        state = self.planner.get_state()

        assert list(state.keys()) == [
            "waypoints",
            "field_boundaries",
            "statistics",
            "execution",
            "navigation_config",
        ]
        assert len(state["waypoints"]) == 1
        assert "South Field" in state["field_boundaries"]
        assert state["statistics"]["total_item_count"] == 1
        assert state["execution"]["current_mission_index"] == -1
        assert state["navigation_config"]["terrain_following"]["enabled"] is False

    def test_navigation_config_controls_default_altitude_frame(self):
        """Terrain following makes new waypoints terrain-altitude by default."""
        planner = MissionPlanner(
            navigation_config=NavigationConfig(
                terrain_following=TerrainFollowingConfig(enabled=True)
            )
        )

        assert planner.add_waypoint(40.7, -74.0, 12.0) is True
        assert planner.mission_items[0].altitude_frame == AltitudeFrame.TERRAIN

        assert planner.add_waypoint(40.8, -74.1, 20.0, altitude_frame="relative") is True
        assert planner.mission_items[1].altitude_frame == AltitudeFrame.RELATIVE

    def test_navigation_config_persists(self, tmp_path):
        """Obstacle and terrain settings are restored with mission state."""
        storage_file = tmp_path / "mission.json"
        planner = MissionPlanner(max_waypoints=100, storage_file=str(storage_file))
        updated = planner.update_navigation_config(
            obstacle_avoidance={
                "enabled": True,
                "mode": "bendy_ruler",
                "margin_meters": 3.0,
            },
            terrain_following={
                "enabled": True,
                "source": "rangefinder",
                "target_agl_meters": 8.0,
            },
        )

        assert updated["obstacle_avoidance"]["mode"] == ObstacleAvoidanceMode.BENDY_RULER.value
        restored = MissionPlanner(max_waypoints=100, storage_file=str(storage_file))

        assert restored.navigation_config.obstacle_avoidance.enabled is True
        assert restored.navigation_config.obstacle_avoidance.mode == ObstacleAvoidanceMode.BENDY_RULER
        assert restored.navigation_config.terrain_following.target_agl_meters == 8.0

    def test_persistent_mission_state(self, tmp_path):
        """Test mission state is restored from storage."""
        storage_file = tmp_path / "mission.json"
        planner = MissionPlanner(max_waypoints=100, storage_file=str(storage_file))
        planner.add_waypoint(40.7, -74.0, 50.0)
        planner.add_waypoint(40.8, -74.1, 60.0)
        planner.add_field_boundary(FieldBoundary("North Field", [
            GeoPoint(40.7, -74.0),
            GeoPoint(40.7, -74.1),
            GeoPoint(40.8, -74.1),
            GeoPoint(40.8, -74.0),
        ]))
        planner.start_mission()
        planner.next_waypoint()

        restored = MissionPlanner(max_waypoints=100, storage_file=str(storage_file))

        assert len(restored.mission_items) == 2
        assert "North Field" in restored.field_boundaries
        assert restored.is_executing is True
        assert restored.current_mission_index == 1

        restored.remove_field_boundary("North Field")
        restored.remove_waypoint(0)

        updated = MissionPlanner(max_waypoints=100, storage_file=str(storage_file))
        assert len(updated.mission_items) == 1
        assert "North Field" not in updated.field_boundaries

    def test_load_mission_updates_persistent_state(self, tmp_path):
        """Test loading a mission updates the configured storage file."""
        export_file = tmp_path / "exported.json"
        storage_file = tmp_path / "mission.json"
        source = MissionPlanner(max_waypoints=100)
        source.add_waypoint(40.7, -74.0, 50.0)
        source.start_mission()
        assert source.save_mission(str(export_file)) is True

        planner = MissionPlanner(max_waypoints=100, storage_file=str(storage_file))
        assert planner.load_mission(str(export_file)) is True

        restored = MissionPlanner(max_waypoints=100, storage_file=str(storage_file))
        assert len(restored.mission_items) == 1
        assert restored.is_executing is True
        assert restored.current_mission_index == 0


class TestGeoPoint:
    """Test geographic point functionality"""

    def test_geopoint_creation(self):
        """Test creating geo points"""
        point = GeoPoint(40.7128, -74.0060, 50.0)
        assert point.latitude == 40.7128
        assert point.longitude == -74.0060
        assert point.altitude == 50.0

    def test_geopoint_serialization(self):
        """Test geo point to dict"""
        point = GeoPoint(40.7128, -74.0060, 50.0)
        point_dict = point.to_dict()
        
        assert point_dict['latitude'] == 40.7128
        assert point_dict['longitude'] == -74.0060
        assert point_dict['altitude'] == 50.0

    def test_geopoint_deserialization(self):
        """Test geo point from dict"""
        data = {
            'latitude': 40.7128,
            'longitude': -74.0060,
            'altitude': 50.0
        }
        
        point = GeoPoint.from_dict(data)
        assert point.latitude == 40.7128
        assert point.longitude == -74.0060


class TestMissionStatistics:
    """Test mission statistics"""

    def test_mission_stats(self):
        """Test getting mission statistics"""
        planner = MissionPlanner()
        
        for i in range(5):
            planner.add_waypoint(40.7 + i*0.01, -74.0 + i*0.01, 50.0 + i*10)
        
        stats = planner.get_statistics()
        
        assert stats['total_item_count'] == 5
        assert stats['waypoint_count'] == 5
        assert stats['min_altitude'] == 50.0
        assert stats['max_altitude'] == 90.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
