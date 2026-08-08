"""
Integration tests for freecad_utils.resolve_base_face / resolve_shared_edge
/ find_shared_edge, against REAL FreeCAD document objects and geometry.

These functions were extracted 2026-08-08 from roof_seam_proxy.py (854
lines, previously zero test coverage) and a vendored copy in
slate_seam_proxy.py, after a real bug: neither recognized the modern
`Sources` PropertyLinkSubList convention (shingle_proxy, slate_proxy,
brick_proxy, quoin_proxy), so selecting faces from any current tiled/
shingled output never unwrapped to the true source roof face.

Requires a real FreeCAD -- these tests are skipped (not failed) when
FreeCAD isn't importable, e.g. under a plain `python3 -m pytest` run with
no FreeCAD on sys.path. Run them for real with FreeCAD's own bundled
Python via its headless console binary, from the repo root:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py

See run_freecad_tests.py for the runner (pytest isn't invokable as
`FreeCADCmd -m pytest`; FreeCADCmd runs a single script, so the runner
just calls pytest.main() itself).
"""

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

from freecad_utils import (  # noqa: E402
    find_shared_edge,
    resolve_base_face,
    resolve_shared_edge,
)


@pytest.fixture
def doc():
    d = App.newDocument("FreecadUtilsTest")
    yield d
    App.closeDocument(d.Name)


def _feature(doc, name, shape):
    """Create a Part::Feature with the given shape -- no Proxy needed,
    just a plain document object with a real .Shape to test against."""
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    return obj


def _adjacent_face_pair(box_shape):
    """Return (i, j) indices of two faces of box_shape that genuinely
    share an edge, established via find_shared_edge itself against the
    real, unmoved box faces -- this is ground truth for the fixtures
    below, not the thing under test (the thing under test is whether
    *disjoint decoy* shapes resolve back to these same true faces)."""
    faces = box_shape.Faces
    for i in range(len(faces)):
        for j in range(i + 1, len(faces)):
            if find_shared_edge(faces[i], faces[j]) is not None:
                return i, j
    raise AssertionError("no adjacent face pair found on fixture box")


# ---------------------------------------------------------------------------
# find_shared_edge -- sanity against real geometry
# ---------------------------------------------------------------------------

class TestFindSharedEdgeReal:
    def test_adjacent_box_faces_share_an_edge(self):
        box = Part.makeBox(10, 10, 10)
        i, j = _adjacent_face_pair(box)
        edge = find_shared_edge(box.Faces[i], box.Faces[j])
        assert edge is not None
        assert edge.Length > 0

    def test_opposite_box_faces_share_no_edge(self):
        box = Part.makeBox(10, 10, 10)
        # Faces 0 and 1 of Part.makeBox are the opposite X faces (no shared edge).
        assert find_shared_edge(box.Faces[0], box.Faces[1]) is None


# ---------------------------------------------------------------------------
# resolve_base_face -- no wrapping detected
# ---------------------------------------------------------------------------

class TestResolveBaseFacePassthrough:
    def test_unwrapped_object_returns_input_unchanged(self, doc):
        box = Part.makeBox(10, 10, 10)
        plain = _feature(doc, "Plain", box)
        face = plain.Shape.Faces[0]
        resolved_face, resolved_obj = resolve_base_face(face, plain, doc=doc)
        assert resolved_face is face
        assert resolved_obj is plain


# ---------------------------------------------------------------------------
# resolve_base_face -- legacy conventions
# ---------------------------------------------------------------------------

class TestResolveBaseFaceLegacy:
    def test_base_object_property(self, doc):
        base = _feature(doc, "Base", Part.makeBox(20, 20, 20))
        wrapped = _feature(doc, "Wrapped", Part.makeBox(1, 1, 1))
        wrapped.addProperty("App::PropertyLink", "BaseObject", "Test", "")
        wrapped.BaseObject = base

        resolved_face, resolved_obj = resolve_base_face(
            wrapped.Shape.Faces[0], wrapped, doc=doc)

        assert resolved_obj is base
        assert resolved_face.Area == pytest.approx(400.0)  # a 20x20 box face

    def test_shingleskin_backlink(self, doc):
        """A 'carrier' object's ShingleSkin property points at the skin
        object; the carrier's own BaseObject is the real source."""
        base = _feature(doc, "Base", Part.makeBox(20, 20, 20))
        skin = _feature(doc, "Skin", Part.makeBox(1, 1, 1))
        carrier = _feature(doc, "Carrier", Part.makeBox(1, 1, 1))
        carrier.addProperty("App::PropertyLink", "ShingleSkin", "Test", "")
        carrier.ShingleSkin = skin
        carrier.addProperty("App::PropertyLink", "BaseObject", "Test", "")
        carrier.BaseObject = base

        resolved_face, resolved_obj = resolve_base_face(
            skin.Shape.Faces[0], skin, doc=doc)

        assert resolved_obj is base

    def test_shingledroof_name_prefix(self, doc):
        base = _feature(doc, "MyRoof", Part.makeBox(20, 20, 20))
        wrapped = doc.addObject("Part::Feature", "ShingledRoof_MyRoof")
        wrapped.Shape = Part.makeBox(1, 1, 1)

        resolved_face, resolved_obj = resolve_base_face(
            wrapped.Shape.Faces[0], wrapped, doc=doc)

        assert resolved_obj is base

    def test_shingleskin_name_prefix(self, doc):
        base = _feature(doc, "MyRoof", Part.makeBox(20, 20, 20))
        wrapped = doc.addObject("Part::Feature", "ShingleSkin_MyRoof")
        wrapped.Shape = Part.makeBox(1, 1, 1)

        resolved_face, resolved_obj = resolve_base_face(
            wrapped.Shape.Faces[0], wrapped, doc=doc)

        assert resolved_obj is base

    def test_depth_limit_does_not_infinite_loop(self, doc):
        """A chain of BaseObject wraps longer than the depth cutoff must
        terminate, not loop or recurse without bound."""
        base = _feature(doc, "Base", Part.makeBox(20, 20, 20))
        current = base
        for i in range(8):  # longer than the 5-level cutoff
            wrapper = _feature(doc, f"Wrap{i}", Part.makeBox(1, 1, 1))
            wrapper.addProperty("App::PropertyLink", "BaseObject", "Test", "")
            wrapper.BaseObject = current
            current = wrapper

        # Must return without raising RecursionError or hanging.
        resolved_face, resolved_obj = resolve_base_face(
            current.Shape.Faces[0], current, doc=doc)
        assert resolved_face is not None
        assert resolved_obj is not None


# ---------------------------------------------------------------------------
# resolve_base_face -- modern Sources convention (the actual bug fix)
# ---------------------------------------------------------------------------

class TestResolveBaseFaceSources:
    def test_single_owner_sources(self, doc):
        base = _feature(doc, "Base", Part.makeBox(20, 20, 20))
        i, _j = _adjacent_face_pair(base.Shape)

        tile = doc.addObject("Part::Feature", "Tile")
        tile.Shape = base.Shape.Faces[i]  # the tile IS this exact face
        tile.addProperty("App::PropertyLinkSubList", "Sources", "Test", "")
        tile.Sources = [(base, (f"Face{i + 1}",))]

        resolved_face, resolved_obj = resolve_base_face(
            tile.Shape.Faces[0], tile, doc=doc)

        assert resolved_obj is base
        assert resolved_face.Area == pytest.approx(base.Shape.Faces[i].Area)

    def test_sources_spanning_multiple_owner_objects(self, doc):
        """Sources can reference faces from more than one object -- the
        winning candidate's OWNER must be tracked per-face, not assumed
        to be a single whole base object (unlike the legacy BaseObject
        path, where _closest_base_face searches one object's own faces)."""
        base_a = _feature(doc, "BaseA", Part.makeBox(20, 20, 20))
        base_b = _feature(doc, "BaseB", Part.makeBox(5, 5, 5))
        # Move base_b far away so its faces can never win the match.
        base_b.Placement = App.Placement(App.Vector(1000, 1000, 1000), App.Rotation())

        target_idx = 0
        tile = doc.addObject("Part::Feature", "Tile")
        tile.Shape = base_a.Shape.Faces[target_idx]
        tile.addProperty("App::PropertyLinkSubList", "Sources", "Test", "")
        tile.Sources = [
            (base_b, ("Face1", "Face2")),
            (base_a, (f"Face{target_idx + 1}",)),
        ]

        resolved_face, resolved_obj = resolve_base_face(
            tile.Shape.Faces[0], tile, doc=doc)

        assert resolved_obj is base_a
        assert resolved_face.Area == pytest.approx(base_a.Shape.Faces[target_idx].Area)


# ---------------------------------------------------------------------------
# resolve_shared_edge -- end to end, mirroring the real bug
# ---------------------------------------------------------------------------

class TestResolveSharedEdgeEndToEnd:
    def test_disjoint_tiles_resolve_to_real_shared_edge(self, doc):
        """The actual bug scenario: two 'tile' objects whose own geometry
        is small and disjoint (as real clipped slate/shingle tiles near a
        hip seam are) don't share an edge directly, but their Sources
        both point back to genuinely adjacent faces of the same real roof
        object -- resolve_shared_edge must find that true shared edge."""
        base = _feature(doc, "Base", Part.makeBox(20, 20, 20))
        i, j = _adjacent_face_pair(base.Shape)

        # Decoy shapes: small boxes far from the real faces and from each
        # other -- guaranteed not to share an edge on their own.
        tile1 = doc.addObject("Part::Feature", "Tile1")
        tile1.Shape = Part.makeBox(0.5, 0.5, 0.5)
        tile1.Placement = App.Placement(App.Vector(500, 0, 0), App.Rotation())
        tile1.addProperty("App::PropertyLinkSubList", "Sources", "Test", "")
        tile1.Sources = [(base, (f"Face{i + 1}",))]

        tile2 = doc.addObject("Part::Feature", "Tile2")
        tile2.Shape = Part.makeBox(0.5, 0.5, 0.5)
        tile2.Placement = App.Placement(App.Vector(-500, 0, 0), App.Rotation())
        tile2.addProperty("App::PropertyLinkSubList", "Sources", "Test", "")
        tile2.Sources = [(base, (f"Face{j + 1}",))]

        # Confirm the premise: the decoys really don't share an edge as-is.
        assert find_shared_edge(tile1.Shape.Faces[0], tile2.Shape.Faces[0]) is None

        edge, f1, o1, f2, o2 = resolve_shared_edge(
            tile1.Shape.Faces[0], tile1, tile2.Shape.Faces[0], tile2, doc=doc)

        assert edge is not None
        expected_edge = find_shared_edge(base.Shape.Faces[i], base.Shape.Faces[j])
        assert edge.Length == pytest.approx(expected_edge.Length)
        assert o1 is base
        assert o2 is base

    def test_directly_shared_edge_needs_no_unwrap(self, doc):
        """When the faces as selected already share an edge, no unwrap
        should be attempted -- the objects are returned unchanged."""
        base = _feature(doc, "Base", Part.makeBox(20, 20, 20))
        i, j = _adjacent_face_pair(base.Shape)

        edge, f1, o1, f2, o2 = resolve_shared_edge(
            base.Shape.Faces[i], base, base.Shape.Faces[j], base, doc=doc)

        assert edge is not None
        assert o1 is base
        assert o2 is base

    def test_no_shared_edge_and_no_sources_returns_none(self, doc):
        """Two genuinely unrelated objects with no wrapping convention at
        all and no geometric intersection: must return None, not raise."""
        a = _feature(doc, "A", Part.makeBox(1, 1, 1))
        b = doc.addObject("Part::Feature", "B")
        b.Shape = Part.makeBox(1, 1, 1)
        b.Placement = App.Placement(App.Vector(500, 500, 500), App.Rotation())

        edge, f1, o1, f2, o2 = resolve_shared_edge(
            a.Shape.Faces[0], a, b.Shape.Faces[0], b, doc=doc)

        assert edge is None
