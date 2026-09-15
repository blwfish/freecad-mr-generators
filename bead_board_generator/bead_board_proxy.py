"""
BeadBoardProxy — FeaturePython proxy for parametric bead board trim.

Change any property in the panel and the bead board regenerates automatically.
Face references stored as PropertyLinkSubList so they survive save/reload.

Bead board: vertical groove/gap pattern extruded proud of the wall face.
Each bead is a narrow gap flanked by flush boards, giving vertical shadow lines.

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import sys
from pathlib import Path

VERSION = "2.0.1"
GENERATOR_NAME = "bead_board_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

from bead_board_geometry import (  # noqa: E402
    validate_parameters,
    calculate_bead_positions,
    calculate_gap_positions,
    detect_face_orientation,
)
from freecad_utils import (  # noqa: E402
    resolve_sources_faces,
    face_normal_at_center as _face_normal,
    GenericViewProxy,
    add_property,
)


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
    bead_board_geometry.detect_face_orientation() with a strict `<`
    where the geometry module uses `<=` at the same 0.1mm tolerance
    boundary -- execution-confirmed to disagree at exactly that boundary,
    with no parity test to catch it. Now a thin FreeCAD-BoundBox-to-dict
    adapter around the tested geometry function."""
    return detect_face_orientation({
        'x_min': bbox.XMin, 'x_max': bbox.XMax,
        'y_min': bbox.YMin, 'y_max': bbox.YMax,
        'z_min': bbox.ZMin, 'z_max': bbox.ZMax,
    })


def _make_gap(gap_start, gap_end, v_min, v_max, depth, horiz_axis, vert_axis, bbox, normal):
    """Extrude a rectangular gap outward from the wall face."""
    if vert_axis == 'z':
        if horiz_axis == 'x':
            by = bbox.YMin
            off = depth if normal.y > 0 else -depth
            w = Part.makePolygon([
                App.Vector(gap_start, by, v_min), App.Vector(gap_end, by, v_min),
                App.Vector(gap_end, by, v_max), App.Vector(gap_start, by, v_max),
                App.Vector(gap_start, by, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(0, off, 0))
        else:
            bx = bbox.XMin
            off = depth if normal.x > 0 else -depth
            w = Part.makePolygon([
                App.Vector(bx, gap_start, v_min), App.Vector(bx, gap_end, v_min),
                App.Vector(bx, gap_end, v_max), App.Vector(bx, gap_start, v_max),
                App.Vector(bx, gap_start, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(off, 0, 0))
    else:  # vert_axis == 'y'
        # Normal axis is always 'z' here (see _detect_orientation): the
        # constant coordinate must come from the face's actual bounding
        # box, not a hardcoded 0 (full-review finding #06) -- mirrors how
        # the vert_axis == 'z' branch above uses bbox.YMin/bbox.XMin for
        # its own normal-axis constant.
        bz = bbox.ZMin
        off = depth if normal.z > 0 else -depth
        w = Part.makePolygon([
            App.Vector(gap_start, v_min, bz), App.Vector(gap_end, v_min, bz),
            App.Vector(gap_end, v_max, bz), App.Vector(gap_start, v_max, bz),
            App.Vector(gap_start, v_min, bz),
        ])
        return Part.Face(w).extrude(App.Vector(0, 0, off))


def generate_bead_board_skin(face, bead_spacing=101.6, bead_depth=0.20, bead_gap=0.20):
    """
    Generate bead board trim for one face.
    Returns additive skin shape (gap solids to be merged with the wall, or used as overlay).

    bead_spacing: distance between bead centers (mm)
    bead_depth:   extrusion depth of gap above face (mm)
    bead_gap:     width of each gap (mm)
    """
    outer_wire, hole_wires = _face_wires(face)
    bbox = face.BoundBox
    vert_axis, horiz_axis, _ = _detect_orientation(bbox)
    normal = _face_normal(face)

    if horiz_axis == 'x':
        h_min, h_max = bbox.XMin, bbox.XMax
    else:
        h_min, h_max = bbox.YMin, bbox.YMax

    if vert_axis == 'z':
        v_min = bbox.ZMin - 0.1
        v_max = bbox.ZMax + 0.1
    else:
        v_min = bbox.YMin - 0.1
        v_max = bbox.YMax + 0.1

    # Delegates to bead_board_geometry so this proxy and the pytest-verified
    # math can never diverge (previously an inlined, independently-drifting
    # copy -- see CLAUDE.md's "Testing rule: proxy/geometry parity" and
    # full-review finding #04). calculate_gap_positions' h_min/h_max/topo_eps
    # args reproduce this proxy's existing TOPO_EPS boundary-overflow
    # behavior exactly.
    bead_centers = calculate_bead_positions(h_min, h_max, bead_spacing)
    gap_positions = calculate_gap_positions(
        bead_centers, bead_gap, h_min=h_min, h_max=h_max, topo_eps=1e-3)

    gaps = []
    for i, (gs, ge) in enumerate(gap_positions):
        try:
            g = _make_gap(gs, ge,
                          v_min, v_max, bead_depth,
                          horiz_axis, vert_axis, bbox, normal)
            gaps.append(g)
        except Exception as e:
            App.Console.PrintWarning(f"  Gap {i}: {e}\n")

    if not gaps:
        raise RuntimeError("No gaps created!")

    fused = gaps[0] if len(gaps) == 1 else gaps[0].fuse(gaps[1:])

    # Trim to face boundary
    try:
        clip_out = face.extrude(normal * (bead_depth + 1.0))
        clip_in  = face.extrude(normal * -1.0)
        trimmed  = fused.common(clip_out.fuse(clip_in))
        if trimmed.Volume > 0.001:
            fused = trimmed
    except Exception as e:
        App.Console.PrintWarning(f"  Trim failed: {e}\n")

    # Cut holes
    for i, hw in enumerate(hole_wires):
        try:
            hf = Part.Face(hw)
            hv = hf.extrude(normal * (bead_depth + 1.0)).fuse(
                 hf.extrude(normal * -1.0))
            fused = fused.cut(hv)
        except Exception as e:
            App.Console.PrintWarning(f"  Hole {i}: {e}\n")

    return fused


# =============================================================================
# FeaturePython proxy
# =============================================================================

class BeadBoardProxy:
    """Parametric bead board trim. Change a property → shape updates."""

    Type = "BeadBoard"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "BeadBoard"
        add_property(obj, "App::PropertyLinkSubList", 'Sources', grp,
            "Wall faces to apply bead board trim to")
        add_property(obj, "App::PropertyLength", 'BeadSpacing', grp,
            "Center-to-center spacing between beads (mm)")
        add_property(obj, "App::PropertyLength", 'BeadDepth', grp,
            "Depth each gap is extruded above the face (mm)")
        add_property(obj, "App::PropertyLength", 'BeadGap', grp,
            "Width of each gap/groove (mm)")
        add_property(obj, "App::PropertyString", 'GeneratorVersion', grp,
            "Generator version (read-only)", editor_mode=1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.BeadSpacing      = p.get('bead_spacing', 101.6)
        obj.BeadDepth        = p.get('bead_depth',   0.20)
        obj.BeadGap          = p.get('bead_gap',     0.20)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        spacing = float(obj.BeadSpacing)
        depth   = float(obj.BeadDepth)
        gap     = float(obj.BeadGap)

        # Full-review finding #05: validate up front (matching
        # board_batten_proxy.py's parameter-validation pattern) so an
        # invalid combination (e.g. bead_gap >= bead_spacing) produces one
        # clear PrintError instead of failing per-face deep inside geometry
        # construction.
        valid, errors = validate_parameters(spacing, depth, gap)
        if not valid:
            App.Console.PrintError(
                f"BeadBoardProxy: invalid parameters: {'; '.join(errors)}\n")
            return

        skins = []
        for face, link_obj, sub_name in resolve_sources_faces(obj.Sources, "BeadBoardProxy"):
            try:
                skin = generate_bead_board_skin(face, spacing, depth, gap)
                skins.append(skin)
                App.Console.PrintMessage(f"  ✓ {link_obj.Label}/{sub_name}\n")
            except Exception as e:
                App.Console.PrintError(
                    f"BeadBoardProxy: {link_obj.Label}/{sub_name}: {e}\n")

        if not skins:
            return
        obj.Shape = skins[0] if len(skins) == 1 else Part.Compound(skins)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "BeadBoard")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class BeadBoardViewProxy(GenericViewProxy):
    ICON = ":/icons/Part_Box.svg"
