"""
Test suite for brick_geometry.py

Comprehensive tests covering all bond patterns, edge cases, and parameter validation.
Run with: python -m pytest test_brick_geometry.py -v
"""

import pytest
import math
from brick_geometry import BrickGeometry, BrickDef


class TestBrickGeometryInit:
    """Test initialization and validation."""
    
    def test_init_valid_stretcher(self):
        """Valid stretcher bond initialization."""
        bg = BrickGeometry(
            u_length=100, v_length=150,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        assert bg.bond_type == 'stretcher'
        assert bg.u_length == 100
        assert bg.v_length == 150
    
    def test_init_valid_all_bonds(self):
        """Valid initialization for all bond types."""
        for bond in ['stretcher', 'english', 'flemish', 'common']:
            bg = BrickGeometry(
                u_length=100, v_length=150,
                brick_width=2.32, brick_height=0.65, brick_depth=1.09,
                mortar=0.11, bond_type=bond
            )
            assert bg.bond_type == bond
    
    def test_init_case_insensitive(self):
        """Bond type is case-insensitive."""
        bg = BrickGeometry(
            u_length=100, v_length=150,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='STRETCHER'
        )
        assert bg.bond_type == 'stretcher'
    
    def test_init_invalid_bond_type(self):
        """Invalid bond type raises error."""
        with pytest.raises(ValueError, match="Unknown bond type"):
            BrickGeometry(
                u_length=100, v_length=150,
                brick_width=2.32, brick_height=0.65, brick_depth=1.09,
                mortar=0.11, bond_type='invalid'
            )
    
    def test_init_negative_dimension(self):
        """Negative dimensions raise error."""
        with pytest.raises(ValueError, match="All dimensions must be positive"):
            BrickGeometry(
                u_length=-100, v_length=150,
                brick_width=2.32, brick_height=0.65, brick_depth=1.09,
                mortar=0.11
            )
    
    def test_init_zero_dimension(self):
        """Zero dimensions raise error."""
        with pytest.raises(ValueError, match="All dimensions must be positive"):
            BrickGeometry(
                u_length=100, v_length=150,
                brick_width=0, brick_height=0.65, brick_depth=1.09,
                mortar=0.11
            )
    
    def test_init_common_bond_invalid_count(self):
        """Common bond with invalid count raises error."""
        with pytest.raises(ValueError, match="common_bond_count must be at least 1"):
            BrickGeometry(
                u_length=100, v_length=150,
                brick_width=2.32, brick_height=0.65, brick_depth=1.09,
                mortar=0.11, bond_type='common', common_bond_count=0
            )
    
    def test_spacing_calculation(self):
        """Spacing values calculated correctly."""
        bg = BrickGeometry(
            u_length=100, v_length=150,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        assert bg.stretcher_spacing_u == pytest.approx(2.32 + 0.11)
        assert bg.header_spacing_u == pytest.approx(1.09 + 0.11)
        assert bg.course_spacing_v == pytest.approx(0.65 + 0.11)


class TestStretcherBond:
    """Test stretcher (running) bond pattern."""
    
    def test_stretcher_basic(self):
        """Basic stretcher bond generation."""
        bg = BrickGeometry(
            u_length=50, v_length=50,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        assert 'bricks' in result
        assert 'metadata' in result
        assert len(result['bricks']) > 0
        assert result['metadata']['bond_type'] == 'stretcher'
    
    def test_stretcher_all_stretchers(self):
        """All bricks in stretcher bond are stretchers."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        for brick in result['bricks']:
            assert brick.brick_type == 'stretcher'
            assert brick.width == 2.32
            assert brick.depth == 1.09
    
    def test_stretcher_offset_pattern(self):
        """Even/odd courses have correct offset."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        bricks = result['bricks']
        
        # Group by course
        by_course = {}
        for brick in bricks:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)
        
        # Check offsets exist and differ between courses
        course_nums = sorted(by_course.keys())
        for i in range(len(course_nums) - 1):
            course1_bricks = by_course[course_nums[i]]
            course2_bricks = by_course[course_nums[i+1]]
            
            # Get the first brick u position in each course
            u1 = course1_bricks[0].u
            u2 = course2_bricks[0].u
            
            # They should have different offsets (either both offset or not)
            # The offset should be approximately half the brick spacing
            offset_diff = abs((u1 % bg.stretcher_spacing_u) - (u2 % bg.stretcher_spacing_u))
            assert offset_diff > 0.1  # Significant difference in offsets
    
    def test_stretcher_coverage(self):
        """Bricks cover the full wall height with overlap."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        
        # Find max V position
        max_v = max(brick.v for brick in result['bricks'])
        # Should extend beyond wall height
        assert max_v >= bg.v_length


class TestEnglishBond:
    """Test English bond pattern."""

    def test_english_basic(self):
        """Basic English bond generation."""
        bg = BrickGeometry(
            u_length=50, v_length=50,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='english'
        )
        result = bg.generate()
        assert len(result['bricks']) > 0
        assert result['metadata']['bond_type'] == 'english'

    def test_english_alternating_courses(self):
        """Alternating stretcher and header courses (ignoring closers)."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='english'
        )
        result = bg.generate()
        bricks = result['bricks']

        # Group by course, excluding closers
        by_course = {}
        for brick in bricks:
            if brick.brick_type == 'closer':
                continue  # Skip closers for pattern check
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        # Check alternation
        for course_num, course_bricks in by_course.items():
            brick_type = course_bricks[0].brick_type
            assert all(b.brick_type == brick_type for b in course_bricks), \
                f"Course {course_num} has mixed brick types"

            if course_num % 2 == 0:
                assert brick_type == 'stretcher'
            else:
                assert brick_type == 'header'

    def test_english_header_dimensions(self):
        """Header bricks have correct rotated dimensions."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='english'
        )
        result = bg.generate()

        for brick in result['bricks']:
            if brick.brick_type == 'header':
                assert brick.width == 1.09  # header width = brick_depth (rotated 90°)
                assert brick.depth == 1.09  # engraved mortar groove depth = brick_depth (uniform)
            elif brick.brick_type == 'stretcher':
                assert brick.width == 2.32
                assert brick.depth == 1.09
            # Closers have variable width, so we don't check them

    def test_english_has_closers(self):
        """English bond should have queen closers at ends."""
        bg = BrickGeometry(
            u_length=50, v_length=50,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='english'
        )
        result = bg.generate()
        closers = [b for b in result['bricks'] if b.brick_type == 'closer']
        assert len(closers) > 0, "English bond should have queen closers"

    def test_english_wall_width_exact(self):
        """Courses should exactly fill the wall width."""
        bg = BrickGeometry(
            u_length=50, v_length=10,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='english'
        )
        result = bg.generate()

        # Check each course fills the wall exactly
        by_course = {}
        for brick in result['bricks']:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        for course_num, course_bricks in by_course.items():
            course_bricks.sort(key=lambda b: b.u)
            last = course_bricks[-1]
            total_width = last.u + last.width
            assert total_width == pytest.approx(50, abs=0.01), \
                f"Course {course_num} width {total_width} != 50"


class TestFlemishBond:
    """Test Flemish bond pattern."""

    def test_flemish_basic(self):
        """Basic Flemish bond generation."""
        bg = BrickGeometry(
            u_length=50, v_length=50,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='flemish'
        )
        result = bg.generate()
        assert len(result['bricks']) > 0
        assert result['metadata']['bond_type'] == 'flemish'

    def test_flemish_alternating_per_course(self):
        """Each course alternates stretchers and headers (excluding closers)."""
        bg = BrickGeometry(
            u_length=100, v_length=50,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='flemish'
        )
        result = bg.generate()
        bricks = result['bricks']

        # Group by course, excluding closers
        by_course = {}
        for brick in bricks:
            if brick.brick_type == 'closer':
                continue
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        # Each course should have alternating pattern
        for course_num, course_bricks in by_course.items():
            course_bricks.sort(key=lambda b: b.u)
            types = [b.brick_type for b in course_bricks]
            # Should alternate between stretcher and header
            for i in range(len(types) - 1):
                assert types[i] != types[i+1], \
                    f"Flemish bond course {course_num} should alternate: {types}"

    def test_flemish_has_closers(self):
        """Flemish bond should have queen closers at ends."""
        bg = BrickGeometry(
            u_length=50, v_length=50,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='flemish'
        )
        result = bg.generate()
        closers = [b for b in result['bricks'] if b.brick_type == 'closer']
        assert len(closers) > 0, "Flemish bond should have queen closers"

    def test_flemish_wall_width_exact(self):
        """Both even and odd courses should exactly fill the wall width."""
        bg = BrickGeometry(
            u_length=50, v_length=10,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='flemish'
        )
        result = bg.generate()

        by_course = {}
        for brick in result['bricks']:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        for course_num, course_bricks in by_course.items():
            course_bricks.sort(key=lambda b: b.u)
            last = course_bricks[-1]
            total_width = last.u + last.width
            assert total_width == pytest.approx(50, abs=0.01), \
                f"Course {course_num} width {total_width} != 50"

    def test_flemish_header_alignment(self):
        """Headers in odd courses should center over stretchers in even courses."""
        bg = BrickGeometry(
            u_length=100, v_length=10,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='flemish'
        )
        result = bg.generate()

        # Get stretcher centers from course 0
        stretchers_c0 = [b for b in result['bricks']
                        if b.course == 0 and b.brick_type == 'stretcher']
        stretcher_centers = [(b.u + b.width / 2) for b in stretchers_c0]

        # Get header centers from course 1
        headers_c1 = [b for b in result['bricks']
                     if b.course == 1 and b.brick_type == 'header']
        header_centers = [(b.u + b.width / 2) for b in headers_c1]

        # Each header should align with a stretcher
        for hc in header_centers:
            aligned = any(abs(hc - sc) < 0.1 for sc in stretcher_centers)
            assert aligned, f"Header at {hc} not aligned with any stretcher"


class TestCommonBond:
    """Test common bond pattern."""
    
    def test_common_basic(self):
        """Basic common bond generation."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='common', common_bond_count=3
        )
        result = bg.generate()
        assert len(result['bricks']) > 0
        assert result['metadata']['bond_type'] == 'common'
    
    def test_common_pattern_5_1(self):
        """5 stretcher courses followed by 1 header course."""
        bg = BrickGeometry(
            u_length=100, v_length=500,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='common', common_bond_count=5
        )
        result = bg.generate()
        bricks = result['bricks']
        
        # Group by course
        by_course = {}
        for brick in bricks:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)
        
        # Check pattern: every 6th course (0-indexed 5, 11, 17...) should be headers
        courses_sorted = sorted(by_course.keys())
        for i, course_num in enumerate(courses_sorted):
            if course_num % 6 == 5:  # Every 6th course (0-indexed)
                brick_type = by_course[course_num][0].brick_type
                assert brick_type == 'header', f"Course {course_num} should be header"
    
    def test_common_pattern_3_1(self):
        """3 stretcher courses followed by 1 header course."""
        bg = BrickGeometry(
            u_length=100, v_length=200,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='common', common_bond_count=3
        )
        result = bg.generate()
        bricks = result['bricks']
        
        # Group by course
        by_course = {}
        for brick in bricks:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)
        
        # Every 4th course (0-indexed 3, 7, 11...) should be headers
        courses_sorted = sorted(by_course.keys())
        for i, course_num in enumerate(courses_sorted):
            if course_num % 4 == 3:
                brick_type = by_course[course_num][0].brick_type
                assert brick_type == 'header', f"Course {course_num} should be header"


class TestMetadata:
    """Test metadata generation."""
    
    def test_metadata_present(self):
        """Metadata includes all expected fields."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        meta = result['metadata']
        
        assert 'bond_type' in meta
        assert 'num_courses' in meta
        assert 'total_bricks' in meta
        assert 'u_length' in meta
        assert 'v_length' in meta
        assert meta['u_length'] == 100
        assert meta['v_length'] == 100
    
    def test_brick_count_reasonable(self):
        """Brick count is reasonable for wall size."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        
        # Rough estimate: (100 / 2.43) * (100 / 0.76) ≈ 1600-2000 with overlap
        count = result['metadata']['total_bricks']
        assert count > 100  # Definitely more than this
        assert count < 10000  # Probably less than this
    
    def test_sequential_indices(self):
        """Brick indices are sequential from 0."""
        bg = BrickGeometry(
            u_length=100, v_length=100,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        
        indices = sorted([b.index for b in result['bricks']])
        assert indices[0] == 0
        assert indices[-1] == len(result['bricks']) - 1
        assert indices == list(range(len(result['bricks'])))


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_very_small_wall(self):
        """Small wall still generates bricks."""
        bg = BrickGeometry(
            u_length=5, v_length=5,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        assert len(result['bricks']) > 0
    
    def test_very_large_wall(self):
        """Large wall generates reasonable number of bricks."""
        bg = BrickGeometry(
            u_length=5000, v_length=5000,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        # Should be roughly (5000/2.43) * (5000/0.76) = ~4.3 million
        # But with overlap we might have less
        assert len(result['bricks']) > 100000
    
    def test_narrow_tall_wall(self):
        """Narrow tall wall."""
        bg = BrickGeometry(
            u_length=10, v_length=1000,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        assert len(result['bricks']) > 0
        # Should have many courses
        max_course = max(b.course for b in result['bricks'])
        assert max_course > 500
    
    def test_wide_short_wall(self):
        """Wide short wall."""
        bg = BrickGeometry(
            u_length=1000, v_length=10,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='stretcher'
        )
        result = bg.generate()
        assert len(result['bricks']) > 0
        # Should have few courses
        max_course = max(b.course for b in result['bricks'])
        assert max_course < 50


class TestBrickDefNamedTuple:
    """Test BrickDef namedtuple."""
    
    def test_brick_def_creation(self):
        """BrickDef can be created and accessed."""
        brick = BrickDef(
            index=0, u=10.5, v=20.3, course=5,
            brick_type='stretcher',
            width=2.32, height=0.65, depth=1.09
        )
        assert brick.index == 0
        assert brick.u == 10.5
        assert brick.course == 5
        assert brick.brick_type == 'stretcher'
    
    def test_brick_def_immutable(self):
        """BrickDef is immutable."""
        brick = BrickDef(
            index=0, u=10.5, v=20.3, course=5,
            brick_type='stretcher',
            width=2.32, height=0.65, depth=1.09
        )
        with pytest.raises(AttributeError):
            brick.index = 1
    
    def test_brick_def_replace(self):
        """BrickDef._replace() works correctly."""
        brick1 = BrickDef(
            index=0, u=10.5, v=20.3, course=5,
            brick_type='stretcher',
            width=2.32, height=0.65, depth=1.09
        )
        brick2 = brick1._replace(index=99)
        assert brick1.index == 0
        assert brick2.index == 99


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
