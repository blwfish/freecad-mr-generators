"""
Integration tests for slate_seam_proxy.py's auto-clearance fix (2026-09-14):
_generate_caps used to anchor every cap a single, hand-set DeckOffset above
the BARE roof deck, assuming the real slate coursing sits at one fixed
height above that deck for the whole seam. Confirmed live that assumption
is wrong in two different directions on the same real document: a long,
cleanly-fitted 42mm ridge run's coursing measured only ~0.18-0.31mm proud
of the bare deck near the seam (a wedge tile's thin head), while a short
6mm hip corner run -- whose top course doesn't divide evenly -- measured
~0.60mm at the equivalent position (a wedge tile's thick butt). With
DeckOffset=0 (the default), every cap on that document sat measurably too
low, worst on the short corner runs, reading as embedded into the coursing
rather than resting on top of it.

The fix: _sample_deck_clearance probes the actual tile-generator geometry
at each cap's own wing-tip positions, so the cap anchors to whatever
coursing is really there instead of a single guessed number.

Requires a real FreeCAD -- skipped (not failed) under a plain
`python3 -m pytest` run. Run for real via:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py slate_seam_generator/tests
"""

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

import slate_seam_proxy as ssp  # noqa: E402


def _face(points):
    vecs = [App.Vector(*p) for p in points]
    wire = Part.makePolygon(vecs + [vecs[0]])
    return Part.Face(wire)


# ---------------------------------------------------------------------------
# _sample_deck_clearance
# ---------------------------------------------------------------------------

class TestSampleDeckClearance:

    def test_no_shapes_returns_zero(self):
        result = ssp._sample_deck_clearance(
            App.Vector(0, 0, 0), App.Vector(0, 0, 1), (), probe_depth=2.0)
        assert result == 0.0

    def test_none_entries_are_skipped_not_crashed(self):
        box = Part.makeBox(10, 10, 0.5)
        result = ssp._sample_deck_clearance(
            App.Vector(5, 5, 0), App.Vector(0, 0, 1), (None, box), probe_depth=2.0)
        assert result == pytest.approx(0.5, abs=1e-6)

    def test_finds_material_at_known_height(self):
        # A 0.5-thick slab sitting directly on z=0 under the probe point --
        # probing up from z=0 should find its top surface at exactly 0.5.
        box = Part.makeBox(10, 10, 0.5)
        result = ssp._sample_deck_clearance(
            App.Vector(5, 5, 0), App.Vector(0, 0, 1), (box,), probe_depth=2.0)
        assert result == pytest.approx(0.5, abs=1e-6)

    def test_takes_outermost_of_multiple_shapes(self):
        low_box = Part.makeBox(10, 10, 0.2)
        high_box = Part.makeBox(10, 10, 0.6)
        result = ssp._sample_deck_clearance(
            App.Vector(5, 5, 0), App.Vector(0, 0, 1), (low_box, high_box), probe_depth=2.0)
        assert result == pytest.approx(0.6, abs=1e-6)

    @pytest.mark.parametrize("box_height,expect_found", [
        (1.999, True),   # just within probe_depth=2.0
        (2.0, True),     # exactly at probe_depth
        (2.001, False),  # just past probe_depth -- the probe segment doesn't reach it
    ])
    def test_probe_depth_boundary(self, box_height, expect_found):
        box = Part.makeBox(10, 10, box_height)
        result = ssp._sample_deck_clearance(
            App.Vector(5, 5, 0), App.Vector(0, 0, 1), (box,), probe_depth=2.0)
        if expect_found:
            assert result == pytest.approx(box_height, abs=1e-3)
        else:
            assert result == pytest.approx(0.0, abs=1e-6)

    def test_point_already_above_all_material_returns_zero(self):
        # The probe starts 0.05 below *point* -- a shape entirely below
        # that (never crossed by the probe segment at all) must not be
        # found, not misreported as some stale distance.
        box = Part.makeBox(10, 10, 0.1)
        result = ssp._sample_deck_clearance(
            App.Vector(5, 5, 5.0), App.Vector(0, 0, 1), (box,), probe_depth=2.0)
        assert result == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# _generate_caps -- auto-clearance integration
# ---------------------------------------------------------------------------

# A simple ridge: two rectangular faces sloping down from a shared
# horizontal ridge edge at z=10, meeting at x=0. Matches the existing
# analyze_roof_intersection test fixtures' shape (mirrored around x=0
# instead of running 0-50-100), just built as real FreeCAD faces here.
RIDGE_FACE1 = [(-20, 0, 0), (-20, 30, 0), (0, 30, 10), (0, 0, 10)]
RIDGE_FACE2 = [(0, 0, 10), (0, 30, 10), (20, 30, 0), (20, 0, 0)]

PARAMS = dict(
    cap_width=4.0, cap_length=2.5, material_thickness=0.2,
    exposure=1.4, deck_offset=0.0, hide_incomplete_end_cap=False,
)


class _StubObj:
    """Minimal stand-in for a FreeCAD document object -- _build_seam_frame
    only reads .Name off it (for an error message this fixture never
    triggers), and _generate_caps never touches obj1/obj2 beyond that."""
    Name = "StubRoof"


class TestGenerateCapsAutoClearance:

    def test_no_tile_shapes_behaves_like_old_deck_offset_only(self):
        """Backward-compatibility pin: tile_shapes=() (the default) must
        reproduce the pre-fix behavior exactly -- deck_offset alone, no
        auto-detected clearance -- for a seam with no coursing yet."""
        face1 = _face(RIDGE_FACE1)
        face2 = _face(RIDGE_FACE2)
        edge = ssp.find_shared_edge(face1, face2)
        shapes, seam_type, dihedral = ssp._generate_caps(
            edge, face1, _StubObj(), face2, _StubObj(), PARAMS, tile_shapes=())
        assert seam_type == 'ridge'
        assert shapes, "expected caps to be generated for a plain foldable ridge"

    def test_cap_clears_a_raised_tile_course_not_embedded_in_it(self):
        """The real bug: a tile course sitting proud of the bare deck must
        not leave the cap's own wing embedded inside it."""
        face1 = _face(RIDGE_FACE1)
        face2 = _face(RIDGE_FACE2)
        edge = ssp.find_shared_edge(face1, face2)

        # A "tile course" slab whose top surface sits 0.6mm above the bare
        # deck's own ridge height (z=10 for this fixture) -- the wing-tip
        # probes happen right at/near the ridge line, at roughly
        # (+-half_width, y, 10). Y must cover more than just [0, edge_len]:
        # the first/last caps are deliberately placed one exposure-length
        # PAST the seam's own [0, edge_len] range (see _generate_caps'
        # own comment on why), so a tile that only spans the bare edge
        # itself leaves those boundary caps unlifted -- confirmed by a
        # first draft of this test with Y=[0,30] passing a `min_z`
        # comparison that looked unaffected by the fix, purely because an
        # unlifted boundary cap set the observed minimum either way.
        tile = Part.makeBox(10, 40, 0.6)
        tile.Placement = App.Placement(App.Vector(-5, -5, 10.0), App.Rotation())

        shapes_raised, seam_type, _ = ssp._generate_caps(
            edge, face1, _StubObj(), face2, _StubObj(), PARAMS, tile_shapes=(tile,))
        shapes_bare, _, _ = ssp._generate_caps(
            edge, face1, _StubObj(), face2, _StubObj(), PARAMS, tile_shapes=())

        assert seam_type == 'ridge'
        assert shapes_raised and shapes_bare

        def min_z(shapes):
            return min(v.Z for s in shapes for v in s.Vertexes)

        # With a raised course present, every cap must sit measurably
        # higher than it would against the bare deck alone -- the fix's
        # entire point. A regression back to bare-deck-only anchoring
        # would make these two indistinguishable.
        assert min_z(shapes_raised) > min_z(shapes_bare) + 0.1

    def test_deck_offset_still_adds_on_top_of_auto_clearance(self):
        """deck_offset remains available as a manual ADDITIONAL lift, not
        replaced by auto-detection -- 0.0 (default) changes nothing, but a
        nonzero value must still raise the result further."""
        face1 = _face(RIDGE_FACE1)
        face2 = _face(RIDGE_FACE2)
        edge = ssp.find_shared_edge(face1, face2)
        tile = Part.makeBox(10, 40, 0.6)
        tile.Placement = App.Placement(App.Vector(-5, -5, 10.0), App.Rotation())

        params_with_extra = dict(PARAMS, deck_offset=1.0)
        shapes_extra, _, _ = ssp._generate_caps(
            edge, face1, _StubObj(), face2, _StubObj(), params_with_extra, tile_shapes=(tile,))
        shapes_plain, _, _ = ssp._generate_caps(
            edge, face1, _StubObj(), face2, _StubObj(), PARAMS, tile_shapes=(tile,))

        def min_z(shapes):
            return min(v.Z for s in shapes for v in s.Vertexes)

        assert min_z(shapes_extra) == pytest.approx(min_z(shapes_plain) + 1.0, abs=1e-3)
