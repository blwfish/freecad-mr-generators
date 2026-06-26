"""
Test suite for brick_geometry.py

Comprehensive tests covering all bond patterns, edge cases, and parameter validation.
Run with: python -m pytest test_brick_geometry.py -v
"""

import pytest
import math
from brick_geometry import BrickGeometry, BrickDef
from boundary_assertions import assert_overflows_boundary


def _brick_u_extent(b):
    """Extract (u_start, u_end) for boundary-overflow checks."""
    return (b.u, b.u + b.width)


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

    def test_english_wall_width_overflow(self):
        """Courses should fill the wall width plus a small TOPO_EPS overflow.

        v5.0.2 added ~10%-of-mortar overflow on both sides to avoid an OCCT
        common() segfault on coincident boundary faces.  Each course now spans
        [-TOPO_EPS, u_length + TOPO_EPS] instead of exactly [0, u_length].
        """
        bg = BrickGeometry(
            u_length=50, v_length=10,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='english'
        )
        result = bg.generate()
        TOPO_EPS = 0.011  # mortar * 0.1

        by_course = {}
        for brick in result['bricks']:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        for course_num, course_bricks in by_course.items():
            course_bricks.sort(key=lambda b: b.u)
            first, last = course_bricks[0], course_bricks[-1]
            assert first.u == pytest.approx(-TOPO_EPS, abs=1e-6), \
                f"Course {course_num} starts at {first.u}, expected -TOPO_EPS"
            total_end = last.u + last.width
            assert total_end == pytest.approx(50 + TOPO_EPS, abs=1e-6), \
                f"Course {course_num} ends at {total_end}, expected 50 + TOPO_EPS"


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

    def test_flemish_wall_width_overflow(self):
        """Both even and odd courses fill wall width plus a TOPO_EPS overflow.

        v5.0.2 added ~10%-of-mortar overflow on both sides to avoid an OCCT
        common() segfault on coincident boundary faces.  Each course now spans
        [-TOPO_EPS, u_length + TOPO_EPS] instead of exactly [0, u_length].
        """
        bg = BrickGeometry(
            u_length=50, v_length=10,
            brick_width=2.32, brick_height=0.65, brick_depth=1.09,
            mortar=0.11, bond_type='flemish'
        )
        result = bg.generate()
        TOPO_EPS = 0.011  # mortar * 0.1

        by_course = {}
        for brick in result['bricks']:
            if brick.course not in by_course:
                by_course[brick.course] = []
            by_course[brick.course].append(brick)

        for course_num, course_bricks in by_course.items():
            course_bricks.sort(key=lambda b: b.u)
            first, last = course_bricks[0], course_bricks[-1]
            assert first.u == pytest.approx(-TOPO_EPS, abs=1e-6), \
                f"Course {course_num} starts at {first.u}, expected -TOPO_EPS"
            total_end = last.u + last.width
            assert total_end == pytest.approx(50 + TOPO_EPS, abs=1e-6), \
                f"Course {course_num} ends at {total_end}, expected 50 + TOPO_EPS"

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


class TestCommonBondBoundaries:
    """Mutation guards and edge-case coverage for common bond."""

    BRICK = dict(brick_width=2.32, brick_height=0.65, brick_depth=1.09,
                 mortar=0.11, skin_depth=0.06)

    def test_common_bond_does_not_exceed_num_courses(self):
        """Mutation guard: `course >= num_courses` break — pin the upper-course boundary.

        With `>=` (correct), the loop breaks before emitting course num_courses.
        With `>` (mutant), one extra course is emitted.  Pinning the max course
        index catches that mutation.
        """
        bg = BrickGeometry(u_length=100, v_length=100, bond_type='common',
                           common_bond_count=3, **self.BRICK)
        result = bg.generate()
        max_course = max(b.course for b in result['bricks'])
        assert max_course < bg.num_courses, (
            f"max course {max_course} must be < num_courses {bg.num_courses} "
            f"(`>=`→`>` mutation would emit one extra course)"
        )

    def test_common_bond_count_1_minimum(self):
        """common_bond_count=1 is the legal minimum; every other course is a header."""
        bg = BrickGeometry(u_length=50, v_length=20, bond_type='common',
                           common_bond_count=1, **self.BRICK)
        result = bg.generate()
        by_course = {}
        for b in result['bricks']:
            by_course.setdefault(b.course, set()).add(b.brick_type)
        for c in sorted(by_course.keys()):
            if c % 2 == 0:
                assert 'stretcher' in by_course[c], f"Course {c} should be stretcher"
                assert 'header' not in by_course[c], f"Course {c} should not mix headers"
            else:
                assert 'header' in by_course[c], f"Course {c} should be header"
                assert 'stretcher' not in by_course[c], f"Course {c} should not mix stretchers"


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


class TestBoundaryOverflow:
    """Boundary-overflow invariant: placed bricks must overflow wall edges.

    Bonds that fit bricks *exactly* to the wall width (Flemish, English) trigger
    an OCCT common() segfault during _create_mortar_grid because brick boundary
    faces become coincident with the face_slab boundary faces.  Stretcher bond
    overflows naturally via the `while u < u_length + spacing` loop.

    These tests assert the invariant in pure Python so the bug can't regress
    without breaking the test suite — no FreeCAD/OCCT needed.
    """

    BRICK = dict(brick_width=2.32, brick_height=0.65, brick_depth=1.09,
                 mortar=0.11, skin_depth=0.06)

    @pytest.mark.parametrize('bond', ['stretcher', 'english', 'flemish', 'common'])
    @pytest.mark.parametrize('u_length', [
        52.55,         # the original demo-model wall that crashed
        50.0,          # round number
        100.0,         # wide wall, n maxes out
        2.32 + 2*0.11, # absolute minimum: just one stretcher + two mortar joints
        # Exact integer multiples — most likely to produce C0=0 in Flemish:
        14 * 2.32 + 13 * 0.11,
        20 * 2.32 + 19 * 0.11,
    ])
    def test_courses_overflow_wall_width(self, bond, u_length):
        """Every course must start before u=0 and end after u=u_length."""
        bg = BrickGeometry(u_length=u_length, v_length=20.0,
                           bond_type=bond, **self.BRICK)
        result = bg.generate()
        bricks = result['bricks']

        # Group bricks by course; check each course independently so we catch
        # the case where SOME courses overflow but others (e.g. odd vs even) don't.
        by_course = {}
        for b in bricks:
            by_course.setdefault(b.course, []).append(b)

        for course_idx, course_bricks in by_course.items():
            assert_overflows_boundary(
                course_bricks, lo=0.0, hi=u_length,
                get_extent=_brick_u_extent,
                label=f"bond={bond} u_length={u_length} course={course_idx}: ",
            )

    def test_flemish_closer_at_min_closer_boundary(self):
        """Mutation guard: `while closer_width < min_closer` — pin the exact-boundary case.

        Choose W so C0 comes out exactly equal to min_closer for n=1.  With the
        correct `<` the loop exits (n=1 is valid); with `<=` the loop reduces n
        to 0 and produces a different course layout.  Pinning the stretcher count
        catches that mutation without FreeCAD.
        """
        S, H, m = 2.32, 1.09, 0.11
        min_closer = m * 2  # 0.22
        n = 1
        W = 2 * min_closer + (n + 1) * S + n * H + 2 * (n + 1) * m
        bg = BrickGeometry(u_length=W, v_length=5.0,
                           brick_width=S, brick_height=0.65, brick_depth=H,
                           mortar=m, bond_type='flemish')
        result = bg.generate()
        by_course = {}
        for b in result['bricks']:
            by_course.setdefault(b.course, []).append(b)
        for course_idx, course_bricks in by_course.items():
            assert_overflows_boundary(
                course_bricks, lo=0.0, hi=W,
                get_extent=_brick_u_extent,
                label=f"closer_boundary course={course_idx}: ",
            )
        # With `<` (correct): loop exits when closer_width == min_closer so n=1 → 2 stretchers
        # With `<=` (mutant): loop reduces n to 0 → 1 stretcher
        even_stretchers = [b for b in result['bricks']
                           if b.course == 0 and b.brick_type == 'stretcher']
        assert len(even_stretchers) == n + 1, (
            f"Expected {n+1} stretchers in even course (closer_width==min_closer boundary), "
            f"got {len(even_stretchers)} — `<`→`<=` mutation would give {n}"
        )

    def test_flemish_zero_closer_overflow(self):
        """Wall sized so the Flemish closer math yields C0≈0 still overflows."""
        # Pick a width where n+1 stretchers + n headers + 2*(n+1) mortars
        # sums to almost exactly the wall width — closer would be ~0 without
        # the TOPO_EPS safety margin.
        S, H, m = 2.32, 1.09, 0.11
        for n in (5, 10, 20):
            # u_length = (n+1)*S + n*H + 2*(n+1)*m + 2*min_closer
            # Use min_closer slightly above the loop's exit threshold so the
            # last valid n is exactly this n.
            u_length = (n+1)*S + n*H + 2*(n+1)*m + 2 * (m * 2)
            bg = BrickGeometry(u_length=u_length, v_length=10.0,
                               bond_type='flemish', **self.BRICK)
            result = bg.generate()
            by_course = {}
            for b in result['bricks']:
                by_course.setdefault(b.course, []).append(b)
            for course_idx, course_bricks in by_course.items():
                assert_overflows_boundary(
                    course_bricks, lo=0.0, hi=u_length,
                    get_extent=_brick_u_extent,
                    label=f"flemish n={n} u_length={u_length:.4f} course={course_idx}: ",
                )


# =============================================================================
# left_quoin feature tests
# =============================================================================

HO = dict(brick_width=2.32, brick_height=0.65, brick_depth=1.09, mortar=0.11)


def _make_bg(bond, primary=True, W=30.0, H=20.0, **extra):
    return BrickGeometry(
        u_length=W, v_length=H,
        left_quoin=True, left_quoin_primary=primary,
        bond_type=bond, **HO, **extra,
    )


class TestLeftQuoinFillStart:
    """_quoin_fill_start returns the correct u-offset per course and face."""

    @pytest.mark.parametrize('course,primary,expected', [
        (0, True,  2.32 + 0.11),   # even, primary   → S quoin → S+m
        (1, True,  1.09 + 0.11),   # odd,  primary   → H quoin → H+m
        (0, False, 1.09 + 0.11),   # even, return    → H quoin → H+m
        (1, False, 2.32 + 0.11),   # odd,  return    → S quoin → S+m
    ])
    def test_fill_start_value(self, course, primary, expected):
        bg = _make_bg('stretcher', primary=primary)
        assert bg._quoin_fill_start(course) == pytest.approx(expected, abs=1e-9)

    def test_no_quoin_returns_zero(self):
        bg = BrickGeometry(u_length=30, v_length=20, bond_type='stretcher', **HO)
        for course in range(5):
            assert bg._quoin_fill_start(course) == 0.0


class TestLeftQuoinStretcherBond:
    """Stretcher bond with left_quoin: fill tiles from quoin_width + mortar."""

    @pytest.mark.parametrize('primary,course', [
        (True,  0), (True,  1), (False, 0), (False, 1),
    ])
    def test_no_fill_bricks_in_quoin_region(self, primary, course):
        bg = _make_bg('stretcher', primary=primary, W=30.0)
        result = bg.generate()
        S, H, m = HO['brick_width'], HO['brick_depth'], HO['mortar']
        # quoin occupies [0, quoin_width]; fill must start after it
        is_s = (course % 2 == 0) == primary
        quoin_w = S if is_s else H
        course_bricks = [b for b in result['bricks'] if b.course == course]
        for brick in course_bricks:
            # Left edge of each fill brick must be ≥ quoin_width (with small tolerance)
            assert brick.u >= quoin_w - 1e-6, (
                f"primary={primary} course={course}: "
                f"fill brick at u={brick.u:.4f} inside quoin region [0,{quoin_w}]"
            )

    def test_fill_covers_full_wall_width(self):
        """At least one fill brick extends past the right wall edge."""
        bg = _make_bg('stretcher', W=30.0)
        result = bg.generate()
        by_course = {}
        for b in result['bricks']:
            by_course.setdefault(b.course, []).append(b)
        for course, bricks in by_course.items():
            rightmost = max(b.u + b.width for b in bricks)
            assert rightmost > 30.0 - 1e-6, \
                f"course {course}: fill does not reach right wall edge"

    @pytest.mark.parametrize('W', [
        4 * (2.32 + 0.11),   # exact multiple of stretcher spacing
        2.32 + 0.11 + 0.5,   # single stretcher + small remainder
        30.0,                  # real-world width
    ])
    def test_exact_multiples_generate_without_error(self, W):
        bg = _make_bg('stretcher', W=W)
        result = bg.generate()
        assert len(result['bricks']) > 0


class TestLeftQuoinFlemishBond:
    """Flemish bond with left_quoin: uniform n and C_right across all courses."""

    def _flemish_bricks_by_course(self, primary=True, W=30.0):
        bg = _make_bg('flemish', primary=primary, W=W)
        result = bg.generate()
        by_course = {}
        for b in result['bricks']:
            by_course.setdefault(b.course, []).append(b)
        return by_course

    def test_no_fill_bricks_in_quoin_region_primary(self):
        S, H, m = HO['brick_width'], HO['brick_depth'], HO['mortar']
        by_course = self._flemish_bricks_by_course(primary=True, W=30.0)
        for course, bricks in by_course.items():
            is_s = (course % 2 == 0)   # primary → S on even
            quoin_w = S if is_s else H
            for brick in bricks:
                assert brick.u >= quoin_w - 1e-6, (
                    f"primary course {course}: fill brick at u={brick.u:.4f} "
                    f"inside quoin [0,{quoin_w:.3f}]"
                )

    def test_no_fill_bricks_in_quoin_region_return(self):
        S, H, m = HO['brick_width'], HO['brick_depth'], HO['mortar']
        by_course = self._flemish_bricks_by_course(primary=False, W=30.0)
        for course, bricks in by_course.items():
            is_h = (course % 2 == 0)   # return → H on even
            quoin_w = H if is_h else S
            for brick in bricks:
                assert brick.u >= quoin_w - 1e-6

    def test_right_closer_formula(self):
        """C_right = W - (n+1)(S+H+2m) holds for all courses."""
        S, H, m = HO['brick_width'], HO['brick_depth'], HO['mortar']
        W = 30.0
        by_course = self._flemish_bricks_by_course(primary=True, W=W)
        min_closer = m * 2

        # Derive n from brick count (n+1 of first type, n of second type per course)
        # Find n from how many bricks appear (excluding the right closer)
        for course, bricks in by_course.items():
            non_closer = [b for b in bricks if b.brick_type != 'closer']
            closer = [b for b in bricks if b.brick_type == 'closer']
            # There should be exactly 1 right closer
            assert len(closer) == 1, f"course {course}: expected 1 closer, got {len(closer)}"
            C_right = closer[0].width
            # Determine n from non-closer count: n+1 of first, n of second = 2n+1 total
            total_non_closer = len(non_closer)
            assert total_non_closer % 2 == 1, f"course {course}: expected odd brick count"
            n = (total_non_closer - 1) // 2
            expected_C = W - (n + 1) * (S + H + 2 * m)
            # C_right includes TOPO_EPS
            TOPO_EPS = m * 0.1
            assert C_right == pytest.approx(expected_C + TOPO_EPS, abs=1e-6), \
                f"course {course}: C_right={C_right:.6f} expected={expected_C+TOPO_EPS:.6f}"

    def test_uniform_n_across_courses(self):
        """n (brick count minus closer) is the same for all courses."""
        by_course = self._flemish_bricks_by_course(primary=True, W=30.0)
        n_values = set()
        for course, bricks in by_course.items():
            non_closer = [b for b in bricks if b.brick_type != 'closer']
            n_values.add(len(non_closer))
        assert len(n_values) == 1, f"n varies across courses: {n_values}"

    def test_fill_sequence_even_course_primary(self):
        """Primary face, even course: fill starts with H (after S quoin)."""
        by_course = self._flemish_bricks_by_course(primary=True, W=30.0)
        for course, bricks in by_course.items():
            if course % 2 == 0:   # even: S quoin → fill leads with H
                non_closer = [b for b in bricks if b.brick_type != 'closer']
                assert non_closer[0].brick_type == 'header', \
                    f"course {course}: first fill brick should be header"

    def test_fill_sequence_odd_course_primary(self):
        """Primary face, odd course: fill starts with S (after H quoin)."""
        by_course = self._flemish_bricks_by_course(primary=True, W=30.0)
        for course, bricks in by_course.items():
            if course % 2 == 1:   # odd: H quoin → fill leads with S
                non_closer = [b for b in bricks if b.brick_type != 'closer']
                assert non_closer[0].brick_type == 'stretcher', \
                    f"course {course}: first fill brick should be stretcher"

    def test_return_face_parity_reversed(self):
        """Return face (primary=False) has reversed course parity vs primary."""
        by_course_a = self._flemish_bricks_by_course(primary=True,  W=30.0)
        by_course_b = self._flemish_bricks_by_course(primary=False, W=30.0)
        # Courses that primary leads with H, return should lead with S, and vice versa
        for course in by_course_a:
            if course not in by_course_b:
                continue
            a_first = [b for b in by_course_a[course] if b.brick_type != 'closer']
            b_first = [b for b in by_course_b[course] if b.brick_type != 'closer']
            assert a_first[0].brick_type != b_first[0].brick_type, \
                f"course {course}: primary={a_first[0].brick_type} " \
                f"return={b_first[0].brick_type} should differ"

    @pytest.mark.parametrize('W', [
        3 * (2.32 + 1.09 + 2 * 0.11),  # exact multiple of (S+H+2m)
        2.32 + 1.09 + 2 * 0.11 + 0.5,  # single pair + small remainder
        30.0,
        20.0,
        50.0,
    ])
    def test_exact_multiples_and_real_widths(self, W):
        bg = _make_bg('flemish', W=W)
        result = bg.generate()
        assert len(result['bricks']) > 0

    def test_right_closer_always_positive(self):
        """C_right must be ≥ min_closer for valid layouts."""
        W = 30.0
        m = HO['mortar']
        by_course = self._flemish_bricks_by_course(primary=True, W=W)
        for course, bricks in by_course.items():
            closers = [b for b in bricks if b.brick_type == 'closer']
            for c in closers:
                assert c.width >= m * 2 - 1e-6, \
                    f"course {course}: closer width {c.width:.4f} below min_closer"


class TestLeftQuoinCommonBond:
    """Common bond with left_quoin: stretcher courses start from quoin offset."""

    def test_stretcher_courses_no_bricks_in_quoin_region(self):
        bg = _make_bg('common', primary=True, W=30.0)
        result = bg.generate()
        S, H, m = HO['brick_width'], HO['brick_depth'], HO['mortar']
        cbc = 5  # default
        # Identify stretcher vs header courses: header every (cbc+1)th course
        for b in result['bricks']:
            is_header = (b.course % (cbc + 1)) == cbc
            if is_header:
                continue  # header courses get no quoin treatment
            is_s = (b.course % 2 == 0)   # primary face parity
            quoin_w = S if is_s else H
            assert b.u >= quoin_w - 1e-6, (
                f"stretcher course {b.course}: brick at u={b.u:.4f} "
                f"inside quoin [0,{quoin_w}]"
            )

    def test_header_courses_tile_full_width(self):
        """Header courses are unchanged — they should span from before 0 to past W."""
        W = 30.0
        bg = _make_bg('common', primary=True, W=W)
        result = bg.generate()
        cbc = 5
        by_course = {}
        for b in result['bricks']:
            by_course.setdefault(b.course, []).append(b)
        for course, bricks in by_course.items():
            is_header = (course % (cbc + 1)) == cbc
            if not is_header:
                continue
            leftmost  = min(b.u for b in bricks)
            rightmost = max(b.u + b.width for b in bricks)
            assert leftmost < 0.0, \
                f"header course {course}: should start before 0, got {leftmost}"
            assert rightmost > W, \
                f"header course {course}: should extend past {W}, got {rightmost}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
