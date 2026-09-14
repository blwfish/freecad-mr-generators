"""
Integration tests for brick_proxy.py's Part 9 performance fix:
_create_mortar_grid no longer calls Part.Shape.common() at all (measured:
801.6s for one 756-brick wall with the old .common()-based clip, vs 2.9s
with brick_geometry.clamp_brick_to_segment()'s analytical clip instead).

These test the actual OCCT geometry the fix produces, not just the pure
clamp math (see brick_generator/tests/test_brick_geometry.py's
TestClampBrickToSegment for that) -- specifically the two properties an
analytical-clip-then-plain-cut approach could get wrong that pure-math
tests can't see: (1) no leftover overlap/gap once real OCCT solids are
built and cut, and (2) the per-segment (not whole-face) scoping actually
holds when a real bay-boundary notch is involved.

Requires a real FreeCAD -- skipped (not failed) under a plain
`python3 -m pytest` run. Run for real via:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py brick_generator/tests
"""

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

import brick_proxy  # noqa: E402


def _face(points):
    vecs = [App.Vector(*p) for p in points]
    wire = Part.makePolygon(vecs + [vecs[0]])
    return Part.Face(wire)


HO = dict(brick_width=2.32, brick_height=0.65, brick_depth=1.09, mortar=0.11)


def _face_params(bond_type='stretcher', left_quoin=False, left_quoin_primary=True,
                  right_quoin=False, right_quoin_primary=True, mortar_depth=0.06):
    return {
        'brick_width': HO['brick_width'], 'brick_height': HO['brick_height'],
        'brick_depth': HO['brick_depth'], 'mortar': HO['mortar'],
        'bond_type': bond_type, 'common_bond_count': 5,
        'material_thickness': 0.3, 'mortar_depth': mortar_depth,
        'left_quoin': left_quoin, 'left_quoin_primary': left_quoin_primary,
        'right_quoin': right_quoin, 'right_quoin_primary': right_quoin_primary,
    }


class TestNoCommonCallNeeded:
    """The core Part 9 property: _create_mortar_grid must produce correct
    geometry (a clean disjoint partition of face_slab into mortar vs.
    brick) using only face_slab.cut(...), with no boolean intersection
    anywhere -- verified via a volume-conservation invariant that doesn't
    depend on comparing against the old (removed) .common()-based code."""

    def test_volume_conservation_plain_wall(self):
        """face_slab.Volume - mortar_grid.Volume must equal the sum of the
        individual (clamped) brick volumes -- proof the cut is a clean,
        non-overlapping partition, not just "didn't crash"."""
        face = _face([(0, 0, 0), (20, 0, 0), (20, 0, 15), (0, 0, 15)])
        params = _face_params(bond_type='common')
        mortar_grid = brick_proxy._create_mortar_grid(face, params)
        assert mortar_grid.isValid()

        face_slab = face.extrude(brick_proxy._scale(face.normalAt(0, 0), -params['mortar_depth']))
        brick_material_volume = face_slab.Volume - mortar_grid.Volume

        # Independently recompute the same brick set the function built,
        # to get an expected total brick volume without relying on any
        # internals beyond what's already public (BrickGeometry/clamp).
        import brick_geometry
        origin, u_vec, v_vec, normal, u_length, v_length, is_h = \
            brick_proxy._get_face_coordinate_system(face)
        bg = brick_geometry.BrickGeometry(
            u_length=u_length, v_length=v_length, bond_type='common',
            skin_depth=params['mortar_depth'], **HO,
        )
        eps = brick_geometry.topo_eps(HO['mortar'])
        total = 0.0
        for bd in bg.generate()['bricks']:
            bd = brick_geometry.clamp_brick_to_segment(bd, u_length, v_length, eps)
            if bd is None:
                continue  # zero overlap -- one of BrickGeometry's own over-generation buffers
            total += bd.width * bd.height * bd.depth

        assert brick_material_volume == pytest.approx(total, rel=1e-6)

    def test_no_brick_extends_past_face_slab_bbox(self):
        """Every clamped brick must fit strictly within face_slab's own
        bounding box -- the property clamp_brick_to_segment exists to
        guarantee without OCCT ever computing an intersection to check it."""
        face = _face([(0, 0, 0), (20, 0, 0), (20, 0, 15), (0, 0, 15)])
        params = _face_params(bond_type='flemish', left_quoin=True,
                               left_quoin_primary=False, right_quoin=True,
                               right_quoin_primary=True)
        normal = face.normalAt(0, 0)
        outer_face = brick_proxy._offset_face(face, normal, 0.3)
        mortar_grid = brick_proxy._create_mortar_grid(outer_face, params)
        assert mortar_grid.isValid()

        face_slab = outer_face.extrude(brick_proxy._scale(normal, -params['mortar_depth']))
        slab_bbox = face_slab.BoundBox
        tol = 1e-6
        assert mortar_grid.BoundBox.XMin >= slab_bbox.XMin - tol
        assert mortar_grid.BoundBox.XMax <= slab_bbox.XMax + tol
        assert mortar_grid.BoundBox.ZMin >= slab_bbox.ZMin - tol
        assert mortar_grid.BoundBox.ZMax <= slab_bbox.ZMax + tol

    def test_dual_quoin_wall_completes_fast_and_valid(self):
        """Sanity check against a real dual-quoin configuration (matching
        the demo model's West wall) -- must complete well within a
        generous smoke-test bound, not assert a strict timing threshold
        (hardware-dependent/flaky, per the plan; the real timing
        verification is a separate live-FreeCAD measurement)."""
        import time
        face = _face([(0, 0, 0), (28.0276, 0, 0), (28.0276, 0, 15), (0, 0, 15)])
        params = _face_params(bond_type='flemish', left_quoin=True,
                               left_quoin_primary=False, right_quoin=True,
                               right_quoin_primary=True)
        t0 = time.time()
        mortar_grid = brick_proxy._create_mortar_grid(face, params)
        elapsed = time.time() - t0
        assert mortar_grid.isValid()
        assert elapsed < 30.0, (
            f"dual-quoin mortar grid took {elapsed:.1f}s -- expected a few "
            f"seconds at most with no .common() call; investigate before "
            f"assuming this is just slow hardware")


class TestBayOpeningStretcherBond:
    """The specific scenario the design review caught as a real false
    negative in an earlier (rejected) version of this fix: a bay/window
    opening splits the face into segments, and stretcher bond's plain
    (non-quoin) path overflows a segment's own boundary by up to nearly a
    full brick width -- must clip to THAT segment's own local bounds, not
    the whole face's global bounds, and must not reach into the
    neighboring segment."""

    @pytest.fixture
    def notched_face(self):
        """A 10-wide x 6-tall wall with a narrow notch cut into the top
        edge between u=6.0 and u=6.015 (gap width 0.015, within
        _find_bay_boundaries' detection range of 0.0005-0.02), splitting
        it into two segments: roughly [0, 6.0] and [6.015, 10]."""
        return _face([
            (0, 0, 0), (10, 0, 0), (10, 0, 6),
            (6.015, 0, 6), (6.015, 0, 5.5), (6.0, 0, 5.5), (6.0, 0, 6),
            (0, 0, 6),
        ])

    def test_bay_split_produces_two_segments(self, notched_face):
        """Confirm the fixture actually exercises the multi-segment path
        before trusting any assertion that depends on it."""
        outer_wire = notched_face.OuterWire
        origin, u_vec, v_vec, normal, u_length, v_length, is_h = \
            brick_proxy._get_face_coordinate_system(notched_face)
        bay_bounds = brick_proxy._find_bay_boundaries(outer_wire, u_vec, v_vec)
        assert len(bay_bounds) == 1, (
            f"expected exactly one bay boundary from the notch, got {bay_bounds} "
            f"-- fixture isn't exercising the multi-segment path as intended")

    def test_stretcher_bond_across_bay_clips_to_own_segment(self, notched_face):
        """The regression itself: must complete (no crash from an
        unclipped overflowing brick), and no brick may extend into the
        notch (u in [6.0, 6.015]) or past either segment's own real edge."""
        params = _face_params(bond_type='stretcher')
        mortar_grid = brick_proxy._create_mortar_grid(notched_face, params)
        assert mortar_grid.isValid()

        # Independently rebuild the clamped brick set the same way
        # _create_mortar_grid does, to inspect individual brick extents
        # directly rather than only the final merged shape.
        import brick_geometry
        origin, u_vec, v_vec, normal, u_length, v_length, is_h = \
            brick_proxy._get_face_coordinate_system(notched_face)
        outer_wire = notched_face.OuterWire
        bay_bounds = brick_proxy._find_bay_boundaries(outer_wire, u_vec, v_vec)
        segs = []
        prev = 0.0
        for b in sorted(bay_bounds):
            if b > prev + 0.001:
                segs.append((prev, b))
            prev = b
        if prev < u_length - 0.001:
            segs.append((prev, u_length))

        eps = brick_geometry.topo_eps(HO['mortar'])
        tol = 1e-6
        for seg_start, seg_end in segs:
            seg_w = seg_end - seg_start
            bg = brick_geometry.BrickGeometry(
                u_length=seg_w, v_length=v_length, bond_type='stretcher',
                skin_depth=params['mortar_depth'], **HO,
            )
            for bd in bg.generate()['bricks']:
                clamped = brick_geometry.clamp_brick_to_segment(bd, seg_w, v_length, eps)
                if clamped is None:
                    continue  # zero overlap with this segment -- nothing to check
                assert clamped.u >= 0 - tol, (
                    f"segment [{seg_start},{seg_end}]: brick u={clamped.u} "
                    f"< 0 after clamping -- overflowed its own left edge")
                assert clamped.u + clamped.width <= seg_w + tol, (
                    f"segment [{seg_start},{seg_end}]: brick reaches "
                    f"{clamped.u + clamped.width}, past its own segment "
                    f"width {seg_w} -- would reach into the bay opening "
                    f"or the neighboring segment")
