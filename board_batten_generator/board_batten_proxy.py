"""
BoardBattenProxy — FeaturePython proxy for parametric board-and-batten siding.

Change any property in the panel and the siding regenerates automatically.
Face references stored as PropertyLinkSubList so they survive save/reload.

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import sys
from pathlib import Path

VERSION = "2.0.1"
GENERATOR_NAME = "board_batten_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

from freecad_utils import (  # noqa: E402
    resolve_sources_faces,
    face_normal_at_center as _face_normal,
)
from board_batten_geometry import (
    validate_parameters,
    calculate_board_positions,
    calculate_batten_positions,
    detect_face_orientation,
)  # noqa: E402


# =============================================================================
# Geometry helpers
# =============================================================================

def _check_for_degenerate_edges(wire):
    return [(i, e.Length) for i, e in enumerate(wire.Edges) if e.Length < 0.001]


def _check_for_duplicate_edges(wire):
    edges = wire.Edges
    dupes = []
    tol = 0.001
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            e1, e2 = edges[i], edges[j]
            s1 = e1.valueAt(e1.FirstParameter)
            t1 = e1.valueAt(e1.LastParameter)
            s2 = e2.valueAt(e2.FirstParameter)
            t2 = e2.valueAt(e2.LastParameter)
            if ((s1.distanceToPoint(s2) < tol and t1.distanceToPoint(t2) < tol) or
                    (s1.distanceToPoint(t2) < tol and t1.distanceToPoint(s2) < tol)):
                dupes.append((i, j))
    return dupes


def _validate_wire(wire, name="Wire"):
    """Full-review finding freecad-mr-generators-20260915-e612#08: this
    generator previously extracted the source face's wires without ever
    checking them for degenerate (near-zero-length) or duplicate edges --
    the exact OCCT-crash class this repo's CLAUDE.md flags for
    Part.Solid(Part.Shell(faces)) -- despite the sibling clapboard_proxy.py
    already doing this check (see its own _validate_wire). Ported that
    same check here rather than leaving it unwired."""
    degen = _check_for_degenerate_edges(wire)
    if degen:
        msgs = [f"  Edge {i}: length={l:.6f}mm" for i, l in degen]
        raise ValueError(f"{name} has degenerate edge(s):\n" + "\n".join(msgs))
    dupes = _check_for_duplicate_edges(wire)
    if dupes:
        msgs = [f"  Edges {i} and {j}" for i, j in dupes]
        raise ValueError(f"{name} has duplicate edge(s):\n" + "\n".join(msgs))


def _face_wires(face):
    wires = face.Wires
    if not wires:
        raise ValueError("Face has no wires!")
    outer = max(wires, key=lambda w: abs(Part.Face(w).Area))
    holes = [w for w in wires if w is not outer]
    if not outer.isClosed():
        raise ValueError("Outer wire is not closed!")
    _validate_wire(outer, "Outer wire")
    for i, hw in enumerate(holes):
        if not hw.isClosed():
            raise ValueError(f"Hole wire {i} not closed!")
        _validate_wire(hw, f"Hole wire {i}")
    return outer, holes


def _detect_orientation(bbox):
    """Full-review finding freecad-mr-generators-20260915-e612#10: this
    used to be an independent inline reimplementation of
    board_batten_geometry.detect_face_orientation() with a strict `<`
    where the geometry module uses `<=` at the same 0.1mm tolerance
    boundary -- execution-confirmed to disagree at exactly that boundary,
    with no parity test to catch it. Now a thin FreeCAD-BoundBox-to-dict
    adapter around the tested geometry function."""
    return detect_face_orientation({
        'x_min': bbox.XMin, 'x_max': bbox.XMax,
        'y_min': bbox.YMin, 'y_max': bbox.YMax,
        'z_min': bbox.ZMin, 'z_max': bbox.ZMax,
    })


def _make_rect_solid(h_start, h_end, v_min, v_max, thickness, offset_dir,
                     horiz_axis, vert_axis, bbox, normal):
    """Extrude a rectangular face along the wall normal."""
    if vert_axis == 'z':
        if horiz_axis == 'x':
            by = bbox.YMin
            off = thickness if normal.y > 0 else -thickness
            w = Part.makePolygon([
                App.Vector(h_start, by, v_min), App.Vector(h_end, by, v_min),
                App.Vector(h_end, by, v_max), App.Vector(h_start, by, v_max),
                App.Vector(h_start, by, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(0, off, 0))
        else:
            bx = bbox.XMin
            off = thickness if normal.x > 0 else -thickness
            w = Part.makePolygon([
                App.Vector(bx, h_start, v_min), App.Vector(bx, h_end, v_min),
                App.Vector(bx, h_end, v_max), App.Vector(bx, h_start, v_max),
                App.Vector(bx, h_start, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(off, 0, 0))
    else:  # vert_axis == 'y'
        # Normal axis is always 'z' here (see _detect_orientation): the
        # constant coordinate must come from the face's actual bounding
        # box, not a hardcoded 0 (full-review finding #06) -- mirrors how
        # the vert_axis == 'z' branch above uses bbox.YMin/bbox.XMin for
        # its own normal-axis constant.
        bz = bbox.ZMin
        off = thickness if normal.z > 0 else -thickness
        w = Part.makePolygon([
            App.Vector(h_start, v_min, bz), App.Vector(h_end, v_min, bz),
            App.Vector(h_end, v_max, bz), App.Vector(h_start, v_max, bz),
            App.Vector(h_start, v_min, bz),
        ])
        return Part.Face(w).extrude(App.Vector(0, 0, off))


def generate_board_batten_skin(face, board_width=7.0, batten_width=0.6,
                               board_thickness=0.2, batten_projection=0.12):
    """Generate board-and-batten siding for one face. Returns additive skin shape."""
    valid, errors = validate_parameters(
        board_width, batten_width, board_thickness, batten_projection)
    if not valid:
        raise ValueError(f"Invalid board-and-batten parameters: {'; '.join(errors)}")

    outer_wire, hole_wires = _face_wires(face)
    bbox = face.BoundBox
    vert_axis, horiz_axis, _ = _detect_orientation(bbox)
    normal = _face_normal(face)
    total_thick = board_thickness + batten_projection

    if horiz_axis == 'x':
        h_min = bbox.XMin - 0.1
        h_max = bbox.XMax + 0.1
    else:
        h_min = bbox.YMin - 0.1
        h_max = bbox.YMax + 0.1

    if vert_axis == 'z':
        v_min = bbox.ZMin - 0.1
        v_max = bbox.ZMax + 0.1
    else:
        v_min = bbox.YMin - 0.1
        v_max = bbox.YMax + 0.1

    # Delegates to board_batten_geometry so this proxy and the
    # pytest-verified math can never diverge (previously an inlined,
    # independently-drifting copy -- see CLAUDE.md's "Testing rule:
    # proxy/geometry parity" and full-review finding #07). This also
    # fixes finding #35's single-board TOPO_EPS overwrite bug (previously
    # dead code in the geometry module, now live). center_align=False
    # preserves this proxy's existing shipped visual behavior
    # (left-aligned boards) rather than silently switching to the
    # geometry module's own center_align=True default, which would be a
    # visible change for existing models.
    board_positions = calculate_board_positions(
        h_min, h_max, board_width, center_align=False)
    batten_centers = calculate_batten_positions(board_positions)

    # Boards
    boards = []
    for i, (h_s, h_e) in enumerate(board_positions):
        try:
            boards.append(_make_rect_solid(h_s, h_e, v_min, v_max,
                                           board_thickness, None,
                                           horiz_axis, vert_axis, bbox, normal))
        except Exception as e:
            App.Console.PrintWarning(f"  Board {i}: {e}\n")

    if not boards:
        raise RuntimeError("No boards created!")

    # Battens at seams
    battens = []
    for i, h_seam in enumerate(batten_centers):
        h_s = h_seam - batten_width / 2
        h_e = h_seam + batten_width / 2
        try:
            battens.append(_make_rect_solid(h_s, h_e, v_min, v_max,
                                            total_thick, None,
                                            horiz_axis, vert_axis, bbox, normal))
        except Exception as e:
            App.Console.PrintWarning(f"  Batten {i}: {e}\n")

    # Combine
    fused = boards[0] if len(boards) == 1 else boards[0].fuse(boards[1:])
    if battens:
        fused_b = battens[0] if len(battens) == 1 else battens[0].fuse(battens[1:])
        fused = fused.fuse(fused_b)

    # Trim to face boundary (handles gable/diagonal edges)
    try:
        clip_out = face.extrude(normal * (total_thick + 1.0))
        clip_in  = face.extrude(normal * -(board_thickness + 1.0))
        fused = fused.common(clip_out.fuse(clip_in))
    except Exception as e:
        App.Console.PrintWarning(f"  Trim failed: {e}\n")

    # Cut holes (windows/doors)
    for i, hw in enumerate(hole_wires):
        try:
            hf = Part.Face(hw)
            hv = hf.extrude(normal * (total_thick + 1.0)).fuse(
                 hf.extrude(normal * -(board_thickness + 1.0)))
            fused = fused.cut(hv)
        except Exception as e:
            App.Console.PrintWarning(f"  Hole {i}: {e}\n")

    return fused


# =============================================================================
# FeaturePython proxy
# =============================================================================

class BoardBattenProxy:
    """Parametric board-and-batten siding. Change a property → shape updates."""

    Type = "BoardBatten"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "BoardBatten"
        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Wall faces to apply board-and-batten siding to")
        if not hasattr(obj, 'BoardWidth'):
            obj.addProperty("App::PropertyLength", "BoardWidth", grp,
                            "Width of each vertical board (mm)")
        if not hasattr(obj, 'BattenWidth'):
            obj.addProperty("App::PropertyLength", "BattenWidth", grp,
                            "Width of each batten strip (mm)")
        if not hasattr(obj, 'BoardThickness'):
            obj.addProperty("App::PropertyLength", "BoardThickness", grp,
                            "Board material thickness (mm)")
        if not hasattr(obj, 'BattenProjection'):
            obj.addProperty("App::PropertyLength", "BattenProjection", grp,
                            "How far battens project above the boards (mm)")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.BoardWidth       = p.get('board_width',       7.0)
        obj.BattenWidth      = p.get('batten_width',      0.6)
        obj.BoardThickness   = p.get('board_thickness',   0.2)
        obj.BattenProjection = p.get('batten_projection', 0.12)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        bw  = float(obj.BoardWidth)
        baw = float(obj.BattenWidth)
        bt  = float(obj.BoardThickness)
        bp  = float(obj.BattenProjection)

        skins = []
        for face, link_obj, sub_name in resolve_sources_faces(obj.Sources, "BoardBattenProxy"):
            try:
                skin = generate_board_batten_skin(face, bw, baw, bt, bp)
                skins.append(skin)
                App.Console.PrintMessage(f"  ✓ {link_obj.Label}/{sub_name}\n")
            except Exception as e:
                App.Console.PrintError(
                    f"BoardBattenProxy: {link_obj.Label}/{sub_name}: {e}\n")

        if not skins:
            return
        obj.Shape = skins[0] if len(skins) == 1 else Part.Compound(skins)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "BoardBatten")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class BoardBattenViewProxy:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return ":/icons/Part_Box.svg"

    def attach(self, vobj):
        self.Object = vobj.Object

    def updateData(self, obj, prop):
        pass

    def onChanged(self, vobj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)
