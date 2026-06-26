"""
Tests for quoin_geometry.py

Covers: column structure, alternating pattern, fill_start values,
TOPO_EPS positioning, num_courses boundary, all bond types accepted,
no overlap between quoin column and fill, OCCT invariants.
"""

import math
import pytest
from quoin_geometry import QuoinGeometry
from brick_geometry import BrickGeometry, BrickDef

# HO-scale defaults used throughout
HO = dict(brick_width=2.32, brick_height=0.65, brick_depth=1.09, mortar=0.11)
TOPO_EPS = HO['mortar'] * 0.1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_qg(wall_height=50.0, bond='stretcher', **overrides):
    p = {**HO, 'bond_type': bond, **overrides}
    return QuoinGeometry(wall_height=wall_height, **p)


def _quoin_right_edge(brick: BrickDef) -> float:
    """Right edge of a quoin brick (accounting for topo_eps start)."""
    return brick.u + brick.width


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestQuoinGeometryInit:
    def test_valid_defaults(self):
        qg = make_qg()
        assert qg.brick_width == 2.32
        assert qg.bond_type == 'stretcher'

    @pytest.mark.parametrize('bond', ['stretcher', 'english', 'flemish', 'common'])
    def test_all_bond_types_accepted(self, bond):
        qg = make_qg(bond=bond)
        assert qg.bond_type == bond

    def test_invalid_bond_type(self):
        with pytest.raises(ValueError, match="Unknown bond type"):
            make_qg(bond='herringbone')

    @pytest.mark.parametrize('bad_param', [
        dict(wall_height=0),
        dict(wall_height=-1),
        dict(brick_width=0),
        dict(brick_height=-0.1),
        dict(brick_depth=0),
        dict(mortar=0),
    ])
    def test_non_positive_dimensions_raise(self, bad_param):
        with pytest.raises(ValueError, match="All dimensions must be positive"):
            make_qg(**bad_param)

    def test_skin_depth_defaults_to_mortar(self):
        qg = make_qg()
        assert qg.skin_depth == qg.mortar

    def test_skin_depth_explicit(self):
        qg = make_qg(skin_depth=0.06)
        assert qg.skin_depth == 0.06


# ---------------------------------------------------------------------------
# num_courses boundary
# ---------------------------------------------------------------------------

class TestNumCourses:
    def test_exact_multiple_height(self):
        """Wall height exactly N courses — +2 overhead courses generated."""
        cs = HO['brick_height'] + HO['mortar']   # 0.76 mm
        for n in [1, 5, 10, 20]:
            h = n * cs
            qg = make_qg(wall_height=h)
            # ceil(h / cs) + 2 = n + 2
            assert qg.num_courses == n + 2, f"n={n}"

    def test_just_below_multiple(self):
        cs = HO['brick_height'] + HO['mortar']
        h = 5 * cs - 1e-6
        qg = make_qg(wall_height=h)
        assert qg.num_courses == 5 + 2  # ceil rounds up to 5, then +2

    def test_just_above_multiple(self):
        cs = HO['brick_height'] + HO['mortar']
        h = 5 * cs + 1e-6
        qg = make_qg(wall_height=h)
        assert qg.num_courses == 6 + 2  # ceil rounds up to 6


# ---------------------------------------------------------------------------
# Column structure — alternating pattern
# ---------------------------------------------------------------------------

class TestColumnPattern:
    def setup_method(self):
        self.qg = make_qg(wall_height=10.0)
        self.result = self.qg.generate()

    def test_one_brick_per_course_per_face(self):
        nc = self.qg.num_courses
        assert len(self.result['face_a_bricks']) == nc
        assert len(self.result['face_b_bricks']) == nc

    def test_even_courses_face_a_stretcher(self):
        for brick in self.result['face_a_bricks']:
            if brick.course % 2 == 0:
                assert brick.brick_type == 'stretcher'
                assert brick.width == pytest.approx(HO['brick_width'])

    def test_even_courses_face_b_header(self):
        for brick in self.result['face_b_bricks']:
            if brick.course % 2 == 0:
                assert brick.brick_type == 'header'
                assert brick.width == pytest.approx(HO['brick_depth'])

    def test_odd_courses_face_a_header(self):
        for brick in self.result['face_a_bricks']:
            if brick.course % 2 == 1:
                assert brick.brick_type == 'header'
                assert brick.width == pytest.approx(HO['brick_depth'])

    def test_odd_courses_face_b_stretcher(self):
        for brick in self.result['face_b_bricks']:
            if brick.course % 2 == 1:
                assert brick.brick_type == 'stretcher'
                assert brick.width == pytest.approx(HO['brick_width'])

    def test_face_a_and_b_always_opposite_type(self):
        a_bricks = self.result['face_a_bricks']
        b_bricks = self.result['face_b_bricks']
        for a, b in zip(a_bricks, b_bricks):
            assert a.brick_type != b.brick_type
            assert a.course == b.course

    def test_v_positions_increase_monotonically(self):
        cs = HO['brick_height'] + HO['mortar']
        for brick in self.result['face_a_bricks']:
            assert brick.v == pytest.approx(brick.course * cs, abs=1e-9)

    def test_sequential_indices(self):
        for i, b in enumerate(self.result['face_a_bricks']):
            assert b.index == i
        for i, b in enumerate(self.result['face_b_bricks']):
            assert b.index == i


# ---------------------------------------------------------------------------
# TOPO_EPS — bricks start slightly before u=0
# ---------------------------------------------------------------------------

class TestTopoEps:
    def test_face_a_u_start_negative(self):
        qg = make_qg(wall_height=10.0)
        result = qg.generate()
        eps = qg._topo_eps
        for brick in result['face_a_bricks']:
            assert brick.u == pytest.approx(-eps, abs=1e-9)

    def test_face_b_u_start_negative(self):
        qg = make_qg(wall_height=10.0)
        result = qg.generate()
        eps = qg._topo_eps
        for brick in result['face_b_bricks']:
            assert brick.u == pytest.approx(-eps, abs=1e-9)

    def test_topo_eps_is_10pct_mortar(self):
        qg = make_qg()
        assert qg._topo_eps == pytest.approx(qg.mortar * 0.1, abs=1e-12)


# ---------------------------------------------------------------------------
# fill_start values
# ---------------------------------------------------------------------------

class TestFillStart:
    def setup_method(self):
        self.qg = make_qg(wall_height=10.0)
        self.result = self.qg.generate()
        self.m = HO['mortar']
        self.S = HO['brick_width']
        self.H = HO['brick_depth']

    def test_face_a_fill_start_even_courses(self):
        """Even courses: face A quoin is stretcher → fill starts at S + m."""
        for course, fs in enumerate(self.result['face_a_fill_start']):
            if course % 2 == 0:
                assert fs == pytest.approx(self.S + self.m, abs=1e-9), \
                    f"course {course}"

    def test_face_a_fill_start_odd_courses(self):
        """Odd courses: face A quoin is header → fill starts at H + m."""
        for course, fs in enumerate(self.result['face_a_fill_start']):
            if course % 2 == 1:
                assert fs == pytest.approx(self.H + self.m, abs=1e-9), \
                    f"course {course}"

    def test_face_b_fill_start_even_courses(self):
        """Even courses: face B quoin is header → fill starts at H + m."""
        for course, fs in enumerate(self.result['face_b_fill_start']):
            if course % 2 == 0:
                assert fs == pytest.approx(self.H + self.m, abs=1e-9)

    def test_face_b_fill_start_odd_courses(self):
        """Odd courses: face B quoin is stretcher → fill starts at S + m."""
        for course, fs in enumerate(self.result['face_b_fill_start']):
            if course % 2 == 1:
                assert fs == pytest.approx(self.S + self.m, abs=1e-9)

    def test_fill_start_count_matches_num_courses(self):
        nc = self.qg.num_courses
        assert len(self.result['face_a_fill_start']) == nc
        assert len(self.result['face_b_fill_start']) == nc

    def test_fill_start_always_positive(self):
        for fs in self.result['face_a_fill_start'] + self.result['face_b_fill_start']:
            assert fs > 0.0


# ---------------------------------------------------------------------------
# No-overlap invariant: quoin bricks must not extend past fill_start
# ---------------------------------------------------------------------------

class TestNoOverlap:
    """
    The quoin brick right edge (u + width) must be ≤ fill_start for that course.
    This ensures the quoin column and fill regions are disjoint.
    (We compare at abs=1e-6 — tighter than the mortar joint, loose enough
    to tolerate the topo_eps offset on the quoin brick's left edge.)
    """

    def _check_no_overlap(self, qg, result, face, fill_key):
        bricks = result[f'face_{face}_bricks']
        fills  = result[f'face_{face}_fill_start']
        for brick, fill_start in zip(bricks, fills):
            right_edge = brick.u + brick.width
            # right_edge ≈ width - topo_eps; fill_start = width + mortar
            # gap ≈ mortar + topo_eps > 0
            assert right_edge <= fill_start + 1e-6, (
                f"Face {face} course {brick.course}: quoin right edge "
                f"{right_edge:.6f} overlaps fill start {fill_start:.6f}"
            )

    @pytest.mark.parametrize('bond', ['stretcher', 'flemish', 'english', 'common'])
    def test_face_a_no_overlap(self, bond):
        qg = make_qg(wall_height=10.0, bond=bond)
        result = qg.generate()
        self._check_no_overlap(qg, result, 'a', 'face_a_fill_start')

    @pytest.mark.parametrize('bond', ['stretcher', 'flemish', 'english', 'common'])
    def test_face_b_no_overlap(self, bond):
        qg = make_qg(wall_height=10.0, bond=bond)
        result = qg.generate()
        self._check_no_overlap(qg, result, 'b', 'face_b_fill_start')


# ---------------------------------------------------------------------------
# Parity: QuoinGeometry fill_start consistent with BrickGeometry left_quoin
# ---------------------------------------------------------------------------

class TestFillStartParity:
    """
    fill_start[course] from QuoinGeometry must equal the u-start that
    BrickGeometry._quoin_fill_start(course) would produce when left_quoin=True.
    Tests the coupling point between the two modules.
    """

    @pytest.mark.parametrize('bond', ['stretcher', 'flemish'])
    @pytest.mark.parametrize('primary', [True, False])
    def test_face_a_fill_start_matches_brick_geometry(self, bond, primary):
        W = 30.0
        qg = make_qg(wall_height=10.0, bond=bond)
        result = qg.generate()

        bg = BrickGeometry(
            u_length=W, v_length=10.0,
            left_quoin=True, left_quoin_primary=True,
            **HO, bond_type=bond,
        )
        for course, fs in enumerate(result['face_a_fill_start']):
            bg_start = bg._quoin_fill_start(course)
            assert fs == pytest.approx(bg_start, abs=1e-9), \
                f"course {course}: QG fill_start={fs} vs BG fill_start={bg_start}"

    @pytest.mark.parametrize('bond', ['stretcher', 'flemish'])
    def test_face_b_fill_start_matches_brick_geometry_return_face(self, bond):
        W = 30.0
        qg = make_qg(wall_height=10.0, bond=bond)
        result = qg.generate()

        bg = BrickGeometry(
            u_length=W, v_length=10.0,
            left_quoin=True, left_quoin_primary=False,  # return face
            **HO, bond_type=bond,
        )
        for course, fs in enumerate(result['face_b_fill_start']):
            bg_start = bg._quoin_fill_start(course)
            assert fs == pytest.approx(bg_start, abs=1e-9), \
                f"course {course}: QG fill_start={fs} vs BG fill_start={bg_start}"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_metadata_keys(self):
        qg = make_qg()
        result = qg.generate()
        md = result['metadata']
        for key in ('bond_type', 'num_courses', 'brick_width',
                    'brick_height', 'brick_depth', 'mortar'):
            assert key in md

    def test_num_courses_in_result(self):
        qg = make_qg(wall_height=10.0)
        result = qg.generate()
        assert result['num_courses'] == qg.num_courses

    def test_metadata_bond_type_propagated(self):
        for bond in ('stretcher', 'flemish', 'english', 'common'):
            qg = make_qg(bond=bond)
            assert qg.generate()['metadata']['bond_type'] == bond


# ---------------------------------------------------------------------------
# Real-world wall height (Ashland shed approx)
# ---------------------------------------------------------------------------

class TestRealWorldParams:
    """Ashland shed approximate dims at HO scale: ~40mm tall, 30-50mm wide."""

    def test_ashland_shed_height(self):
        qg = make_qg(wall_height=40.0, bond='flemish')
        result = qg.generate()
        assert result['num_courses'] >= 2
        assert len(result['face_a_bricks']) == result['num_courses']

    def test_height_single_course_minimum(self):
        """Wall just barely one course tall."""
        cs = HO['brick_height'] + HO['mortar']
        qg = make_qg(wall_height=cs * 0.5)  # half a course — still generates
        result = qg.generate()
        assert result['num_courses'] >= 2   # always at least the +2 overhead
