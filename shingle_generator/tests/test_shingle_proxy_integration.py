"""
Integration tests for shingle_proxy's V-groove chamfer, against real OCCT.

Regression for the "fused shingle strip" bug (2026-10-06): the old auto
chamfer (1.5x material = 0.375) was larger than the wedge it cuts (1x
material = 0.25), makeChamfer raised, the exception was swallowed, and the
shingles came out groove-free and fused on 3D-print export.  These pin that
(a) the auto chamfer actually cuts a groove and (b) a chamfer that cannot be
cut is COUNTED and REPORTED, never swallowed.

Requires a real FreeCAD; skipped under a plain `python3 -m pytest`.  Run for
real with FreeCADCmd (absolute script path; it eats pytest CLI flags), e.g. a
one-line wrapper script calling pytest.main on this file -- see
shared/tests/run_freecad_tests.py for the pattern.
"""

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

import shingle_proxy as sp  # noqa: E402

MATERIAL = 0.25
WEDGE = MATERIAL * 1          # auto WedgeThickness = 1x material


def _params(chamfer):
    return dict(shingle_width=3.5, shingle_height=2.0,
                material_thickness=MATERIAL, shingle_exposure=1.5,
                stagger_pattern='half', wedge_thickness=WEDGE, chamfer=chamfer)


@pytest.fixture
def wall_face():
    return Part.Face(Part.makePolygon([
        App.Vector(0, 0, 0), App.Vector(40, 0, 0),
        App.Vector(40, 0, 30), App.Vector(0, 0, 30), App.Vector(0, 0, 0)]))


@pytest.fixture
def doc():
    d = App.newDocument("ShingleChamferTest")
    yield d
    App.closeDocument(d.Name)


def _face_count(shapes):
    return sum(len(s.Faces) for s in shapes)


def test_auto_chamfer_fraction_is_under_the_wedge():
    # The invariant the whole fix rests on: auto chamfer must stay below the
    # auto wedge, or makeChamfer fails again.
    assert MATERIAL * sp.AUTO_CHAMFER_FRACTION < WEDGE


def test_auto_chamfer_cuts_a_groove_and_reports_no_failures(wall_face):
    auto = MATERIAL * sp.AUTO_CHAMFER_FRACTION
    shapes, stats = sp._generate_shingles_for_face(wall_face, _params(auto))
    ungrooved, _ = sp._generate_shingles_for_face(wall_face, _params(0.0))
    assert stats['attempted'] > 0
    assert stats['failed'] == 0
    assert stats['first_error'] is None
    # A groove adds a face per shingle; zero chamfer adds none.
    assert _face_count(shapes) > _face_count(ungrooved)


def test_zero_chamfer_is_not_attempted(wall_face):
    _, stats = sp._generate_shingles_for_face(wall_face, _params(0.0))
    assert stats['attempted'] == 0 and stats['failed'] == 0


@pytest.mark.parametrize("chamfer", [0.25, 0.26, 0.375])
def test_chamfer_at_or_above_wedge_is_counted_not_swallowed(wall_face, chamfer):
    shapes, stats = sp._generate_shingles_for_face(wall_face, _params(chamfer))
    assert stats['attempted'] > 0
    assert stats['failed'] == stats['attempted']      # every one fails, none hidden
    assert stats['first_error']                       # and the reason is kept
    assert len(shapes) > 0                            # geometry still produced


def test_chamfer_just_below_wedge_succeeds(wall_face):
    # Observed on OCCT 8.x (26.3): 0.2 cuts, 0.25 does not.  Pinned so an OCCT
    # change to this boundary shows up as a test failure, not a fused print.
    _, stats = sp._generate_shingles_for_face(wall_face, _params(0.2))
    assert stats['failed'] == 0


def test_execute_reports_failure_to_the_console(doc, monkeypatch):
    src = doc.addObject("Part::Feature", "Src")
    src.Shape = Part.makeBox(40, 1, 30)
    face_no = next(i for i, f in enumerate(src.Shape.Faces, 1)
                   if abs(f.CenterOfMass.y) < 1e-6)
    obj = doc.addObject("Part::FeaturePython", "R")
    sp.ShingleProxy(obj)
    sp.ShingleProxy.set_defaults(obj)
    obj.Chamfer = 0.375          # larger than the 0.25 wedge -> must fail loudly
    obj.Sources = [(src, ("Face%d" % face_no,))]

    errors = []
    monkeypatch.setattr(App.Console, "PrintError", errors.append)
    doc.recompute()
    assert any("chamfer FAILED" in e for e in errors), errors
    assert len(obj.Shape.Solids) > 0


def test_execute_with_default_chamfer_prints_no_chamfer_error(doc, monkeypatch):
    src = doc.addObject("Part::Feature", "Src")
    src.Shape = Part.makeBox(40, 1, 30)
    face_no = next(i for i, f in enumerate(src.Shape.Faces, 1)
                   if abs(f.CenterOfMass.y) < 1e-6)
    obj = doc.addObject("Part::FeaturePython", "R")
    sp.ShingleProxy(obj)
    sp.ShingleProxy.set_defaults(obj)       # Chamfer stays 0 -> auto
    obj.Sources = [(src, ("Face%d" % face_no,))]

    errors = []
    monkeypatch.setattr(App.Console, "PrintError", errors.append)
    doc.recompute()
    assert not [e for e in errors if "chamfer" in e.lower()], errors
