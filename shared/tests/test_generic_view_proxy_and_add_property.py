"""
Integration tests for shared/freecad_utils.GenericViewProxy and
add_property(), against REAL FreeCAD -- not FreeCAD-shaped mocks.

Full-review finding freecad-mr-generators-20260915-e612#33/#34: these two
helpers replaced 15 independently-duplicated ~14-20 line ViewProvider
classes and 134 hand-copied `if not hasattr(obj, name): obj.addProperty(...)`
blocks across every proxy file in this repo. A bug in either helper would
now affect all 14/15 call sites at once instead of one -- so both are
worth verifying once, for real, rather than trusting the AST-based
structural audit that produced the consolidation (see git history on
shared/freecad_utils.py and each *_proxy.py for that audit) as sufficient
on its own.

Requires a real FreeCAD -- skipped (not failed) under a plain
`python3 -m pytest` run with no FreeCAD on sys.path. Run for real via
FreeCAD's own headless console binary:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py

Two things are genuinely NOT testable headless, confirmed live
(App.GuiUp == 0, obj.ViewObject is None under FreeCADCmd with no Gui
module loaded) -- true of every generator's original per-file ViewProxy
class too, not a limitation this consolidation introduced:
  - obj.ViewObject itself (there is none without a GUI session)
  - anything that would need a real Qt icon/Coin3d scene node

What IS tested here, against real FreeCAD objects:
  - add_property(): real App::Property* registration via a real
    Part::FeaturePython object, for every one of this repo's 15
    XxxProxy classes that use it, including idempotency (calling the
    property-setup method twice must add nothing new -- the entire
    point of the original hasattr guard).
  - GenericViewProxy: constructed with a minimal stand-in for FreeCAD's
    real ViewObject (settable .Proxy, an .Object back-reference -- the
    only two attributes any of GenericViewProxy's methods touch), for
    every one of this repo's 15 XxxViewProxy subclasses -- icon
    resolution via class-attribute inheritance, attach()/updateData()/
    onChanged() not raising, and the dumps()/loads()/__getstate__/
    __setstate__ persistence round-trip.
  - TestDegenerateEdgeValidationWiredIn: a related but separate fix
    (freecad-mr-generators-20260915-e612#08) verified here because it's
    the highest-severity thing in this pass that still had no FreeCAD-
    level coverage -- board_batten_proxy.py/bead_board_proxy.py's
    degenerate/duplicate-edge validation, ported from clapboard_proxy.py
    because it previously existed and was tested in the geometry modules
    but was never wired into either proxy's real execution path. Verified
    on real Part.Wire objects that a degenerate edge (length < 0.001mm)
    and a duplicate edge (two edges tracing the same segment) are both
    rejected, and that an ordinary valid wire is not (no false positive).
    The end-to-end _face_wires -> _validate_wire call path is exercised
    on a real Part.Face; a genuinely degenerate OUTER wire cannot be used
    for that specific test because Part.Face() itself refuses to build a
    face from one (confirmed live: OCCT raises "Failed to create face
    from wire" before this repo's own code runs) -- the negative case is
    covered at the _validate_wire level instead, which is where the fix
    logic actually lives.
"""

import os
import sys

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# (generator dir, proxy module name, Proxy class, ViewProxy class, expected icon)
GENERATORS = [
    ("bead_board_generator", "bead_board_proxy", "BeadBoardProxy", "BeadBoardViewProxy", ":/icons/Part_Box.svg"),
    ("board_batten_generator", "board_batten_proxy", "BoardBattenProxy", "BoardBattenViewProxy", ":/icons/Part_Box.svg"),
    ("brick_generator", "brick_proxy", "BrickProxy", "BrickViewProxy", ":/icons/Part_Box.svg"),
    ("clapboard_generator", "clapboard_proxy", "ClapboardProxy", "ClapboardViewProxy", ":/icons/Part_Box.svg"),
    ("label_generator", "label_proxy", "LabelProxy", "LabelViewProxy", ":/icons/Draft_ShapeString.svg"),
    ("radial_brick_generator", "radial_brick_proxy", "RadialBrickProxy", "RadialBrickViewProxy", ":/icons/Part_Box.svg"),
    ("roof_seam_generator", "roof_seam_proxy", "RoofSeamProxy", "RoofSeamViewProxy", ":/icons/Part_Box.svg"),
    ("shingle_generator", "shingle_proxy", "ShingleProxy", "ShingleViewProxy", ":/icons/Part_Box.svg"),
    ("slate_generator", "slate_proxy", "SlateProxy", "SlateViewProxy", ":/icons/Part_Box.svg"),
    ("slate_seam_generator", "slate_seam_proxy", "SlateSeamProxy", "SlateSeamViewProxy", ":/icons/Part_Box.svg"),
    ("smart_trim_generator", "smart_trim_proxy", "SmartTrimProxy", "SmartTrimViewProxy", ":/icons/Part_Box.svg"),
    ("snow_guard_generator", "snow_guard_proxy", "SnowGuardProxy", "SnowGuardViewProxy", ":/icons/Part_Box.svg"),
    ("standing_seam_generator", "standing_seam_proxy", "StandingSeamProxy", "StandingSeamViewProxy", ":/icons/Part_Box.svg"),
    ("standing_seam_snow_guard_generator", "standing_seam_snow_guard_proxy",
     "StandingSeamSnowGuardProxy", "StandingSeamSnowGuardViewProxy", ":/icons/Part_Box.svg"),
    ("station_sign_generator", "station_sign_proxy", "StationSignProxy", "StationSignViewProxy",
     ":/icons/Draft_ShapeString.svg"),
]
# ashlar_generator/ashlar_proxy.py and label_generator's *own* pre-existing
# addProperty-loop helper are deliberately excluded -- neither uses
# add_property()/GenericViewProxy (ashlar's ViewProxy has a genuinely
# different, shorter shape; ashlar's _add_properties doesn't use the
# hasattr guard at all), so there is nothing of this consolidation to
# verify for them.


def _import_proxy_module(gen_dir, mod_name):
    gen_path = os.path.join(REPO_ROOT, gen_dir)
    shared_path = os.path.join(REPO_ROOT, "shared")
    for p in (gen_path, shared_path):
        if p not in sys.path:
            sys.path.insert(0, p)
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return __import__(mod_name)


class _MockDocObject:
    """Stand-in for the Part::FeaturePython object a real ViewObject's
    .Object would point back to -- content doesn't matter, only identity."""
    pass


class _MockViewObject:
    """Minimal stand-in for FreeCAD's real ViewObject. Settable .Proxy
    (what GenericViewProxy.__init__ sets) plus an .Object back-reference
    (what attach() reads) -- the only two attributes any GenericViewProxy
    method touches. Deliberately NOT a real FreeCAD ViewObject: those
    don't exist headless (see module docstring)."""
    def __init__(self):
        self.Object = _MockDocObject()


@pytest.fixture
def doc():
    d = App.newDocument("TestGenericViewProxyAddProperty")
    yield d
    App.closeDocument(d.Name)


@pytest.mark.parametrize(
    "gen_dir,mod_name,proxy_cls,view_cls,expected_icon", GENERATORS,
    ids=[g[0] for g in GENERATORS],
)
class TestAddPropertyAndGenericViewProxy:

    def test_add_property_registers_real_properties(
            self, doc, gen_dir, mod_name, proxy_cls, view_cls, expected_icon):
        mod = _import_proxy_module(gen_dir, mod_name)
        ProxyClass = getattr(mod, proxy_cls)

        obj = doc.addObject("Part::FeaturePython", f"Test_{proxy_cls}")
        ProxyClass(obj)

        # Every generator has more than a handful of properties -- this
        # also catches the case where _setup_properties silently did
        # nothing (e.g. a typo'd condition that always short-circuits).
        assert len(obj.PropertiesList) > 5

    def test_add_property_is_idempotent(
            self, doc, gen_dir, mod_name, proxy_cls, view_cls, expected_icon):
        """The entire point of the original `if not hasattr(...)` guard:
        calling property setup a second time must add nothing new and
        must not raise (FreeCAD's own addProperty raises if you register
        the same name twice without the guard)."""
        mod = _import_proxy_module(gen_dir, mod_name)
        ProxyClass = getattr(mod, proxy_cls)

        obj = doc.addObject("Part::FeaturePython", f"Test_{proxy_cls}")
        ProxyClass(obj)
        before = set(obj.PropertiesList)

        ProxyClass(obj)  # must not raise
        after = set(obj.PropertiesList)

        assert before == after

    def test_view_proxy_icon_resolves_via_inheritance(
            self, doc, gen_dir, mod_name, proxy_cls, view_cls, expected_icon):
        mod = _import_proxy_module(gen_dir, mod_name)
        ViewProxyClass = getattr(mod, view_cls)

        mock_vobj = _MockViewObject()
        vp = ViewProxyClass(mock_vobj)

        assert mock_vobj.Proxy is vp
        assert vp.getIcon() == expected_icon

    def test_view_proxy_lifecycle_methods_do_not_raise(
            self, doc, gen_dir, mod_name, proxy_cls, view_cls, expected_icon):
        mod = _import_proxy_module(gen_dir, mod_name)
        ViewProxyClass = getattr(mod, view_cls)

        mock_vobj = _MockViewObject()
        vp = ViewProxyClass(mock_vobj)

        vp.attach(mock_vobj)
        assert vp.Object is mock_vobj.Object

        vp.updateData(None, "SomeProp")
        vp.onChanged(mock_vobj, "SomeProp")

    def test_view_proxy_persistence_round_trips(
            self, doc, gen_dir, mod_name, proxy_cls, view_cls, expected_icon):
        mod = _import_proxy_module(gen_dir, mod_name)
        ViewProxyClass = getattr(mod, view_cls)

        mock_vobj = _MockViewObject()
        vp = ViewProxyClass(mock_vobj)

        state = vp.__getstate__()
        assert state is None  # GenericViewProxy.dumps() always returns None
        vp.__setstate__(state)  # must not raise


class TestDegenerateEdgeValidationWiredIn:
    """Full-review finding freecad-mr-generators-20260915-e612#08: the
    degenerate/duplicate-edge wire validation existed and was tested in
    board_batten_geometry.py/bead_board_geometry.py, but board_batten_proxy.py
    and bead_board_proxy.py never called it (or an equivalent) on their real
    execution path -- confirmed via grep at review time, zero references.
    The fix ported clapboard_proxy.py's own _validate_wire pattern into
    both. This class verifies the check actually FIRES on real FreeCAD
    wire geometry, not just that the function exists -- a wiring mistake
    (e.g. calling the check but discarding its result) would pass a
    "does this raise ImportError" smoke test while still leaving the
    OCCT-crash class unguarded.
    """

    @pytest.mark.parametrize("mod_name", ["board_batten_proxy", "bead_board_proxy"])
    def test_degenerate_edge_is_rejected(self, mod_name):
        gen_dir = "board_batten_generator" if mod_name == "board_batten_proxy" else "bead_board_generator"
        mod = _import_proxy_module(gen_dir, mod_name)

        # A "rectangle" with one edge only 0.0001mm long -- below the
        # 0.001mm degenerate-edge threshold both _check_for_degenerate_edges
        # implementations use.
        pts = [
            App.Vector(0, 0, 0),
            App.Vector(0, 0, 0.0001),  # degenerate: length 0.0001 < 0.001
            App.Vector(10, 0, 0),
            App.Vector(10, 10, 0),
            App.Vector(0, 0, 0),
        ]
        wire = Part.makePolygon(pts)

        with pytest.raises(ValueError, match="degenerate edge"):
            mod._validate_wire(wire, "Test wire")

    @pytest.mark.parametrize("mod_name", ["board_batten_proxy", "bead_board_proxy"])
    def test_duplicate_edge_is_rejected(self, mod_name):
        gen_dir = "board_batten_generator" if mod_name == "board_batten_proxy" else "bead_board_generator"
        mod = _import_proxy_module(gen_dir, mod_name)

        # A wire that goes out and back along the same segment twice --
        # edges 0 and 2 are the same line, opposite direction (duplicate).
        pts = [
            App.Vector(0, 0, 0),
            App.Vector(10, 0, 0),
            App.Vector(0, 0, 0),
            App.Vector(0, 10, 0),
            App.Vector(0, 0, 0),
        ]
        wire = Part.makePolygon(pts)

        with pytest.raises(ValueError, match="duplicate edge"):
            mod._validate_wire(wire, "Test wire")

    @pytest.mark.parametrize("mod_name", ["board_batten_proxy", "bead_board_proxy"])
    def test_valid_wire_is_accepted(self, mod_name):
        """Sanity check: a genuinely valid rectangle must NOT raise --
        confirms the fix doesn't false-positive on ordinary geometry."""
        gen_dir = "board_batten_generator" if mod_name == "board_batten_proxy" else "bead_board_generator"
        mod = _import_proxy_module(gen_dir, mod_name)

        pts = [
            App.Vector(0, 0, 0),
            App.Vector(10, 0, 0),
            App.Vector(10, 10, 0),
            App.Vector(0, 10, 0),
            App.Vector(0, 0, 0),
        ]
        wire = Part.makePolygon(pts)

        mod._validate_wire(wire, "Test wire")  # must not raise

    @pytest.mark.parametrize("mod_name", ["board_batten_proxy", "bead_board_proxy"])
    def test_face_wires_calls_validate_wire_on_a_real_face(self, mod_name):
        """End-to-end sanity check that _face_wires (the actual call site
        used by generate_*_skin) reaches _validate_wire at all on a real,
        ordinary Part.Face -- i.e. the wiring itself (not just the
        validation logic in isolation) executes without error on the
        common case. A genuinely degenerate outer wire can't be used
        here: Part.Face() itself refuses to build a face from one
        (confirmed live -- OCCT rejects it as "Failed to create face from
        wire" before this repo's own code ever runs), so the negative
        case is exercised at the _validate_wire level above instead,
        which is the actual site of the fix logic."""
        gen_dir = "board_batten_generator" if mod_name == "board_batten_proxy" else "bead_board_generator"
        mod = _import_proxy_module(gen_dir, mod_name)

        pts = [
            App.Vector(0, 0, 0),
            App.Vector(10, 0, 0),
            App.Vector(10, 10, 0),
            App.Vector(0, 10, 0),
            App.Vector(0, 0, 0),
        ]
        wire = Part.makePolygon(pts)
        face = Part.Face(wire)

        outer, holes = mod._face_wires(face)
        assert outer is not None
        assert holes == []
