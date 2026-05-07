"""
Test suite for radial_brick_geometry.py

Comprehensive tests covering cylindrical and conical surfaces, running bond
pattern, convex/concave surfaces, edge cases, and parameter validation.

Run with: python -m pytest test_radial_brick_geometry.py -v
"""

import pytest
import math
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from radial_brick_geometry import RadialBrickGeometry, RadialBrickDef


class TestRadialBrickGeometryInit:
    """Test initialization and validation."""

    def test_init_valid_cylinder(self):
        """Valid cylinder initialization (constant radius)."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.z_min == 0
        assert rbg.z_max == 100
        assert rbg.radius_at_z_min == 50
        assert rbg.radius_at_z_max == 50
        assert rbg.taper_rate == 0  # Cylinder has no taper

    def test_init_valid_cone(self):
        """Valid cone initialization (varying radius)."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=60, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.radius_at_z_min == 60
        assert rbg.radius_at_z_max == 40
        assert rbg.taper_rate == pytest.approx(-0.2)  # (40-60)/100

    def test_init_reverse_taper(self):
        """Reverse taper (corbelling) - radius increases with height."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=30, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.taper_rate == pytest.approx(0.2)  # Positive taper

    def test_init_concave_surface(self):
        """Initialize for inner (concave) surface."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11,
            is_concave=True
        )
        assert rbg.is_concave is True

    def test_init_invalid_z_range(self):
        """z_max <= z_min raises error."""
        with pytest.raises(ValueError, match="z_max.*must be greater than z_min"):
            RadialBrickGeometry(
                z_min=100, z_max=50,  # Invalid: z_max < z_min
                radius_at_z_min=50, radius_at_z_max=50,
                brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
                mortar_thickness=0.11
            )

    def test_init_negative_dimension(self):
        """Negative dimensions raise error."""
        with pytest.raises(ValueError, match="All dimensions must be positive"):
            RadialBrickGeometry(
                z_min=0, z_max=100,
                radius_at_z_min=50, radius_at_z_max=50,
                brick_length=-2.32, brick_height=0.65, brick_thickness=1.09,
                mortar_thickness=0.11
            )

    def test_init_zero_dimension(self):
        """Zero dimensions raise error."""
        with pytest.raises(ValueError, match="All dimensions must be positive"):
            RadialBrickGeometry(
                z_min=0, z_max=100,
                radius_at_z_min=0, radius_at_z_max=50,  # Zero radius
                brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
                mortar_thickness=0.11
            )

    def test_init_invalid_bond_offset(self):
        """Bond offset outside [0,1] raises error."""
        with pytest.raises(ValueError, match="bond_offset must be between 0 and 1"):
            RadialBrickGeometry(
                z_min=0, z_max=100,
                radius_at_z_min=50, radius_at_z_max=50,
                brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
                mortar_thickness=0.11,
                bond_offset=1.5
            )

    def test_init_radius_too_small(self):
        """Radius too small for minimum bricks raises error."""
        with pytest.raises(ValueError, match="Radius too small"):
            RadialBrickGeometry(
                z_min=0, z_max=100,
                radius_at_z_min=1, radius_at_z_max=1,  # Very small radius
                brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
                mortar_thickness=0.11
            )

    def test_course_spacing_calculation(self):
        """Course spacing calculated correctly."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.course_spacing == pytest.approx(0.65 + 0.11)


class TestRadiusInterpolation:
    """Test radius_at_z interpolation."""

    def test_cylinder_constant_radius(self):
        """Cylinder returns constant radius at all Z."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.radius_at_z(0) == 50
        assert rbg.radius_at_z(50) == 50
        assert rbg.radius_at_z(100) == 50

    def test_cone_linear_interpolation(self):
        """Cone interpolates radius linearly."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=60, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.radius_at_z(0) == pytest.approx(60)
        assert rbg.radius_at_z(50) == pytest.approx(50)  # Midpoint
        assert rbg.radius_at_z(100) == pytest.approx(40)

    def test_radius_clamped_below_z_min(self):
        """Radius at z < z_min returns radius_at_z_min."""
        rbg = RadialBrickGeometry(
            z_min=10, z_max=100,
            radius_at_z_min=60, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.radius_at_z(0) == 60  # Below z_min

    def test_radius_clamped_above_z_max(self):
        """Radius at z > z_max returns radius_at_z_max."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=60, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        assert rbg.radius_at_z(150) == 40  # Above z_max


class TestCylinderGeneration:
    """Test brick generation on cylindrical surfaces."""

    def test_generate_basic_cylinder(self):
        """Basic cylinder generates bricks."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        assert 'bricks' in result
        assert 'metadata' in result
        assert len(result['bricks']) > 0

    def test_cylinder_constant_bricks_per_course(self):
        """Cylinder has same number of bricks in each course."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()
        meta = result['metadata']

        assert meta['min_bricks_per_course'] == meta['max_bricks_per_course']
        assert meta['is_tapered'] is False

    def test_running_bond_offset(self):
        """Odd courses are offset by half brick."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11,
            bond_offset=0.5
        )
        result = rbg.generate()
        bricks = result['bricks']

        # Group by course
        by_course = {}
        for brick in bricks:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        # Check offset between consecutive courses
        if len(by_course) >= 2:
            course_0_start = by_course[0][0].angle_start
            course_1_start = by_course[1][0].angle_start

            # They should have different starting angles
            assert course_0_start != pytest.approx(course_1_start, abs=0.01)

    def test_all_bricks_same_radius(self):
        """All bricks on cylinder have same radius."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        for brick in result['bricks']:
            assert brick.radius == pytest.approx(50)


class TestConeGeneration:
    """Test brick generation on conical surfaces."""

    def test_generate_basic_cone(self):
        """Basic cone generates bricks."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=60, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        assert len(result['bricks']) > 0
        assert result['metadata']['is_tapered'] is True

    def test_cone_fewer_bricks_at_top(self):
        """Tapered cone has fewer bricks per course at top (smaller radius)."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=60, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()
        meta = result['metadata']

        # Smaller radius at top means fewer bricks
        assert meta['min_bricks_per_course'] < meta['max_bricks_per_course']

    def test_cone_radius_varies_by_course(self):
        """Each course has radius appropriate for its Z position."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=60, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()
        bricks = result['bricks']

        # Group by course and check radius decreases with height
        by_course = {}
        for brick in bricks:
            if brick.course not in by_course:
                by_course[brick.course] = brick.radius

        courses = sorted(by_course.keys())
        for i in range(len(courses) - 1):
            # Radius should decrease as course increases
            assert by_course[courses[i]] >= by_course[courses[i + 1]]


class TestConcaveVsConvex:
    """Test inner (concave) vs outer (convex) surfaces."""

    def test_convex_surface_default(self):
        """Default is convex (outer) surface."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        for brick in result['bricks']:
            assert brick.is_concave is False

    def test_concave_surface(self):
        """Concave surface bricks marked correctly."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11,
            is_concave=True
        )
        result = rbg.generate()

        for brick in result['bricks']:
            assert brick.is_concave is True

    def test_convex_vertices_project_outward(self):
        """Convex surface brick vertices project outward from radius."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11,
            is_concave=False
        )
        result = rbg.generate()
        brick = result['bricks'][0]

        vertices = rbg.get_brick_vertices(brick)
        # For convex, outer vertices should be at radius + thickness
        outer_vertex = vertices[3]  # bottom-outer-start
        distance = math.sqrt(outer_vertex[0]**2 + outer_vertex[1]**2)
        assert distance == pytest.approx(50 + 1.09)  # radius + thickness

    def test_concave_vertices_project_inward(self):
        """Concave surface brick vertices project inward from radius."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11,
            is_concave=True
        )
        result = rbg.generate()
        brick = result['bricks'][0]

        vertices = rbg.get_brick_vertices(brick)
        # For concave, inner vertices should be at radius - thickness
        inner_vertex = vertices[0]  # bottom-inner-start
        distance = math.sqrt(inner_vertex[0]**2 + inner_vertex[1]**2)
        assert distance == pytest.approx(50 - 1.09)  # radius - thickness


class TestBrickVertices:
    """Test brick vertex calculations."""

    def test_get_brick_vertices_returns_8(self):
        """get_brick_vertices returns 8 vertices."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()
        brick = result['bricks'][0]

        vertices = rbg.get_brick_vertices(brick)
        assert len(vertices) == 8

    def test_vertices_correct_z_positions(self):
        """Vertices have correct Z positions (bottom and top)."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()
        brick = result['bricks'][0]

        vertices = rbg.get_brick_vertices(brick)

        # Bottom 4 vertices (indices 0-3)
        for i in range(4):
            assert vertices[i][2] == pytest.approx(brick.z)

        # Top 4 vertices (indices 4-7)
        for i in range(4, 8):
            assert vertices[i][2] == pytest.approx(brick.z + brick.height)

    def test_get_outer_face_vertices_returns_4(self):
        """get_outer_face_vertices returns 4 vertices."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()
        brick = result['bricks'][0]

        face_vertices = rbg.get_outer_face_vertices(brick)
        assert len(face_vertices) == 4


class TestMetadata:
    """Test metadata generation."""

    def test_metadata_present(self):
        """Metadata includes all expected fields."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=100,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()
        meta = result['metadata']

        assert 'num_courses' in meta
        assert 'total_bricks' in meta
        assert 'avg_bricks_per_course' in meta
        assert 'min_bricks_per_course' in meta
        assert 'max_bricks_per_course' in meta
        assert 'z_min' in meta
        assert 'z_max' in meta
        assert 'radius_at_z_min' in meta
        assert 'radius_at_z_max' in meta
        assert 'is_tapered' in meta
        assert 'is_concave' in meta

    def test_metadata_values_correct(self):
        """Metadata values match input parameters."""
        rbg = RadialBrickGeometry(
            z_min=10, z_max=110,
            radius_at_z_min=50, radius_at_z_max=40,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11,
            is_concave=True
        )
        result = rbg.generate()
        meta = result['metadata']

        assert meta['z_min'] == 10
        assert meta['z_max'] == 110
        assert meta['radius_at_z_min'] == 50
        assert meta['radius_at_z_max'] == 40
        assert meta['surface_height'] == 100
        assert meta['is_tapered'] is True
        assert meta['is_concave'] is True

    def test_sequential_indices(self):
        """Brick indices are sequential from 0."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=50,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        indices = sorted([b.index for b in result['bricks']])
        assert indices[0] == 0
        assert indices[-1] == len(result['bricks']) - 1
        assert indices == list(range(len(result['bricks'])))


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_course(self):
        """Very short surface generates at least one course."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=0.5,  # Very short
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        assert result['metadata']['num_courses'] >= 1
        assert len(result['bricks']) > 0

    def test_many_courses(self):
        """Tall surface generates many courses."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=500,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        # 500 / (0.65 + 0.11) = ~657 courses
        assert result['metadata']['num_courses'] > 600

    def test_large_radius(self):
        """Large radius generates many bricks per course."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=500, radius_at_z_max=500,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11
        )
        result = rbg.generate()

        # Circumference ~3142, bricks per course ~1290
        assert result['metadata']['avg_bricks_per_course'] > 1000

    def test_bond_offset_zero(self):
        """Zero bond offset means no stagger."""
        rbg = RadialBrickGeometry(
            z_min=0, z_max=10,
            radius_at_z_min=50, radius_at_z_max=50,
            brick_length=2.32, brick_height=0.65, brick_thickness=1.09,
            mortar_thickness=0.11,
            bond_offset=0.0
        )
        result = rbg.generate()
        bricks = result['bricks']

        # Group by course
        by_course = {}
        for brick in bricks:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        # All courses should start at same angle (approximately 0)
        if len(by_course) >= 2:
            course_0_start = by_course[0][0].angle_start
            course_1_start = by_course[1][0].angle_start
            assert course_0_start == pytest.approx(course_1_start, abs=0.01)


class TestRadialBrickDefNamedTuple:
    """Test RadialBrickDef namedtuple."""

    def test_brick_def_creation(self):
        """RadialBrickDef can be created and accessed."""
        brick = RadialBrickDef(
            index=0, course=5, brick_in_course=10,
            z=25.0, angle_start=0.5, angle_end=0.6,
            radius=50.0, height=0.65, thickness=1.09,
            is_concave=False
        )
        assert brick.index == 0
        assert brick.course == 5
        assert brick.brick_in_course == 10
        assert brick.z == 25.0
        assert brick.radius == 50.0

    def test_brick_def_immutable(self):
        """RadialBrickDef is immutable."""
        brick = RadialBrickDef(
            index=0, course=5, brick_in_course=10,
            z=25.0, angle_start=0.5, angle_end=0.6,
            radius=50.0, height=0.65, thickness=1.09,
            is_concave=False
        )
        with pytest.raises(AttributeError):
            brick.index = 1

    def test_brick_def_replace(self):
        """RadialBrickDef._replace() works correctly."""
        brick1 = RadialBrickDef(
            index=0, course=5, brick_in_course=10,
            z=25.0, angle_start=0.5, angle_end=0.6,
            radius=50.0, height=0.65, thickness=1.09,
            is_concave=False
        )
        brick2 = brick1._replace(index=99)
        assert brick1.index == 0
        assert brick2.index == 99


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
