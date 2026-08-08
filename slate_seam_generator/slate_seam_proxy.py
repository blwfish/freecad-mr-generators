"""
Slate Seam Cap FeaturePython proxy — parametric slate hip/ridge cap generator
for FreeCAD.

Straddles the seam where two independently-coursed slate roof faces meet at
a hip or ridge, with a bent-V cap cross-section that matches the seam's own
actual dihedral angle (not a fixed, pitch-agnostic angle) -- covering the
residual gap/mismatch left by each face's own independent coursing.

Valleys are explicitly out of scope: real slate roofs use metal flashing in
valleys, not slate caps -- select roof_seam_generator's valley flashing for
that case instead.

Change any property in the Properties panel and the cap run regenerates.

Version History:
- 1.1.0: Shared-edge resolution (find_shared_edge/resolve_shared_edge) moved
         to shared/freecad_utils.py and extended to recognize the Sources
         PropertyLinkSubList convention (this repo's modern standard, used
         by slate_proxy/shingle_proxy/brick_proxy/quoin_proxy) alongside the
         legacy BaseObject/ShingledRoof_/ShingleSkin_ convention it already
         had. Previously, selecting faces from a SlateTiles output (which
         uses Sources) never got unwrapped to the real roof panel -- the
         classifier saw individual clipped tile fragments instead, causing
         spurious "no shared edge" / "ambiguous" results near hip seams.
- 1.0.0: Initial release.
"""

import FreeCAD as App
import Part
import sys
from pathlib import Path

VERSION = "1.1.0"
GENERATOR_NAME = "slate_seam_generator"

_here = Path(__file__).parent
for _p in (str(_here), str(_here / '_lib'), str(_here.parent / 'shared')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from freecad_utils import find_shared_edge, resolve_shared_edge, resolve_sources_faces  # noqa: E402

from slate_seam_geometry import (
    validate_parameters,
    resolve_cap_eligibility,
    is_dihedral_foldable,
    calculate_dihedral_fold,
    calculate_wing_profile_2d,
    calculate_cap_count,
    is_valid_clip_fragment,
    is_top_course_complete,
    calculate_fitted_exposure,
    analyze_roof_intersection,
)

# Wire point order for calculate_wing_profile_2d's 7-point cross-section --
# single source of truth for both the cap face and the OCCT edge-length
# invariant test, so the two never drift apart.
PROFILE_ORDER = ('bl', 'bc', 'br', 'tr', 'tc2', 'tc1', 'tl')


# ---------------------------------------------------------------------------
# FreeCAD geometry helpers
# ---------------------------------------------------------------------------

def _face_normal_at_center(face):
    uv = face.ParameterRange
    return face.normalAt((uv[0] + uv[1]) / 2, (uv[2] + uv[3]) / 2)

def _face_to_tuples(face):
    """Extract plain-tuple vertices/normal/edges from a FreeCAD face, for
    the pure-Python roof_geometry/slate_seam_geometry analysis functions."""
    vertices = [(v.Point.x, v.Point.y, v.Point.z) for v in face.Vertexes]
    n = _face_normal_at_center(face)
    if n.Length > 1e-9:
        n.normalize()
    if n.z < 0:
        n = App.Vector(-n.x, -n.y, -n.z)
    edges = []
    for e in face.Edges:
        p0 = e.Vertexes[0].Point
        p1 = e.Vertexes[-1].Point
        edges.append(((p0.x, p0.y, p0.z), (p1.x, p1.y, p1.z)))
    return vertices, (n.x, n.y, n.z), edges


def _build_seam_frame(shared_edge, face1, face2, obj):
    """Build the along-seam / across-seam / bisector-up local coordinate
    frame for cap placement, in FreeCAD vector space.

    Returns (start_pt, edge_dir, edge_len, local_x, local_z, n1_out, n2_out).
    Only DIRECTIONS are computed here -- the dihedral ANGLE itself is never
    recomputed from n1_out/n2_out in this module; the caller must take it
    from analyze_roof_intersection's single dihedral_angle result instead,
    to avoid two independently-drifting sources of truth for one angle.
    """
    v0, v1 = shared_edge.Vertexes[0].Point, shared_edge.Vertexes[-1].Point
    start_pt, end_pt = (v0, v1) if v0.z <= v1.z else (v1, v0)
    edge_vec = end_pt - start_pt
    edge_len = edge_vec.Length
    edge_dir = edge_vec * (1.0 / edge_len)

    n1 = _face_normal_at_center(face1)
    n2 = _face_normal_at_center(face2)
    n1_out = n1 * -1.0 if n1.z < 0 else App.Vector(n1.x, n1.y, n1.z)
    n2_out = n2 * -1.0 if n2.z < 0 else App.Vector(n2.x, n2.y, n2.z)

    bisector_raw = n1_out + n2_out
    if bisector_raw.Length < 1e-9:
        bisector = App.Vector(0, 0, 1)
    else:
        bisector = bisector_raw * (1.0 / bisector_raw.Length)

    local_x = edge_dir.cross(bisector)
    if local_x.Length < 1e-9:
        local_x = App.Vector(1, 0, 0)
    else:
        local_x = local_x * (1.0 / local_x.Length)
    local_z = bisector

    return start_pt, edge_dir, edge_len, local_x, local_z, n1_out, n2_out


def _build_seam_clip_volume(start_pt, edge_dir, local_x, local_z, edge_len,
                             cap_width, h_center, mat_thick, deck_offset):
    """Box spanning exactly [0, edge_len] along edge_dir from start_pt, wide
    enough in local_x/local_z to fully contain every cap's cross-section --
    the caps are only ever clipped along the seam axis, never across it.

    z is measured relative to start_pt (a point on the real shared edge),
    matching the anchor convention in _generate_caps: the wing tips sit
    BELOW the real edge by h_center, and the top surface sits at most
    mat_thick + deck_offset above it."""
    wx = cap_width + 2.0 * mat_thick + 1.0
    z_lo = -(h_center + mat_thick + 1.0)
    z_hi = mat_thick + deck_offset + 2.0

    p0 = start_pt + local_x * (-wx) + local_z * z_lo
    p1 = start_pt + local_x * (wx) + local_z * z_lo
    p2 = start_pt + local_x * (wx) + local_z * z_hi
    p3 = start_pt + local_x * (-wx) + local_z * z_hi
    wire = Part.Wire([
        Part.makeLine(p0, p1), Part.makeLine(p1, p2),
        Part.makeLine(p2, p3), Part.makeLine(p3, p0),
    ])
    return Part.Face(wire).extrude(edge_dir * edge_len)


def _clip_shape(shape, clip_volume):
    """Clip *shape* against clip_volume. Returns clipped solid or None.

    Survival is judged against the shape's own pre-clip volume (see
    is_valid_clip_fragment) rather than a fixed absolute threshold, so a
    razor-thin sliver at the seam's start/end margin is discarded instead
    of surviving as a stray fragment.
    """
    full_volume = shape.Volume
    try:
        result = shape.common(clip_volume)
        if result.ShapeType == 'Compound' and len(result.Solids) == 1:
            result = result.Solids[0]
        if is_valid_clip_fragment(result.Volume, full_volume):
            return result
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Cap generation
# ---------------------------------------------------------------------------

def _generate_caps(shared_edge, face1, obj1, face2, obj2, params):
    """Generate slate seam cap solids for one resolved hip/ridge seam.

    Returns (shapes, seam_type, dihedral_degrees). shapes is empty (not an
    error) when the seam is correctly classified but ineligible (valley,
    none, ambiguous) or the dihedral angle isn't foldable -- the caller is
    responsible for reporting that clearly via SeamType/DihedralDegrees and
    a console message, not this function.
    """
    f1_verts, f1_normal, f1_edges = _face_to_tuples(face1)
    f2_verts, f2_normal, f2_edges = _face_to_tuples(face2)

    analysis = analyze_roof_intersection(
        f1_verts, f1_normal, f1_edges, f2_verts, f2_normal, f2_edges)

    seam_type = analysis['classification']
    dihedral_degrees = (analysis['dihedral_angle']['angle_degrees']
                         if analysis['dihedral_angle'] else 0.0)

    eligible, message = resolve_cap_eligibility(seam_type)
    if not eligible:
        App.Console.PrintMessage(f"  {message}\n")
        return [], seam_type, dihedral_degrees

    if not is_dihedral_foldable(dihedral_degrees):
        App.Console.PrintMessage(
            f"  Dihedral angle {dihedral_degrees:.1f} deg is too close to "
            f"180 deg to fold into a cap cross-section -- no geometry generated.\n")
        return [], seam_type, dihedral_degrees

    dihedral_radians = analysis['dihedral_angle']['angle_radians']

    start_pt, edge_dir, edge_len, local_x, local_z, n1_out, n2_out = \
        _build_seam_frame(shared_edge, face1, face2, obj1)

    cap_width   = params['cap_width']
    cap_length  = params['cap_length']
    mat_thick   = params['material_thickness']
    deck_offset = params.get('deck_offset', 0.0)
    hide_incomplete_end = params.get('hide_incomplete_end_cap', False)

    exposure = calculate_fitted_exposure(edge_len, params['exposure'])
    cap_count = calculate_cap_count(edge_len, exposure)

    dihedral_fold = calculate_dihedral_fold(dihedral_radians, cap_width)
    profile_2d = calculate_wing_profile_2d(dihedral_fold, mat_thick)
    h_center = dihedral_fold['h_center']

    # calculate_wing_profile_2d's own z=0 is the wing-TIP baseline, but the
    # real hip/ridge line (start_pt/pt below) is at the wing-PEAK (bc),
    # which sits at local z=h_center in that convention. Shifting the
    # anchor down by h_center puts bc exactly on the real seam instead of
    # floating h_center above it -- the fix for a real bug (2026-07-29):
    # the first build anchored bl/br (the wing tips, sitting BELOW the
    # ridge on the actual roof) at the seam's own height, leaving the
    # whole cap floating h_center above the roof surface with nothing
    # visibly supporting it. deck_offset then lifts the (now correctly
    # anchored) cross-section a small additional amount to clear the
    # underlying coursing's own material thickness, if any.
    anchor_shift = local_z * (deck_offset - h_center)

    clip_volume = _build_seam_clip_volume(
        start_pt, edge_dir, local_x, local_z, edge_len,
        cap_width, h_center, mat_thick, deck_offset)

    shapes = []
    for i in range(cap_count):
        # First cap starts one exposure-length before the seam origin, so
        # the run always overflows the [0, edge_len] clip box's start
        # boundary too -- landing exactly at t=0 would put this cap's own
        # edge exactly coincident with the clip box's lower face, the
        # OCCT-segfault failure mode assert_overflows_boundary exists to
        # catch (see this repo's boundary_assertions.py).
        t = -exposure + i * exposure

        if hide_incomplete_end and not is_top_course_complete(t + cap_length, edge_len):
            continue

        pt = start_pt + edge_dir * t + anchor_shift
        pts3d = {k: pt + local_x * x + local_z * z
                  for k, (x, z) in profile_2d.items()}
        try:
            wire = Part.Wire([
                Part.makeLine(pts3d[PROFILE_ORDER[j]],
                               pts3d[PROFILE_ORDER[(j + 1) % len(PROFILE_ORDER)]])
                for j in range(len(PROFILE_ORDER))
            ])
            cap_shape = Part.Face(wire).extrude(edge_dir * cap_length)
        except Exception as e:
            App.Console.PrintMessage(f"  cap at t={t:.2f}: build failed: {e}\n")
            continue

        clipped = _clip_shape(cap_shape, clip_volume)
        if clipped is not None:
            shapes.append(clipped)

    return shapes, seam_type, dihedral_degrees


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class SlateSeamProxy:
    """Parametric slate hip/ridge seam cap. Change a property -> caps update."""

    Type = "SlateSeamGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "SlateSeam"
        if not hasattr(obj, 'Sources'):
            obj.addProperty("App::PropertyLinkSubList", "Sources", grp,
                            "Exactly two adjacent roof faces sharing a hip/ridge seam")
        if not hasattr(obj, 'CapWidth'):
            obj.addProperty("App::PropertyLength", "CapWidth", grp,
                            "Total cap width across the seam (both wings)")
        if not hasattr(obj, 'CapLength'):
            obj.addProperty("App::PropertyLength", "CapLength", grp,
                            "Length of each cap along the seam")
        if not hasattr(obj, 'MaterialThickness'):
            obj.addProperty("App::PropertyLength", "MaterialThickness", grp,
                            "Slate thickness")
        if not hasattr(obj, 'Exposure'):
            obj.addProperty("App::PropertyLength", "Exposure", grp,
                            "Spacing between caps along the seam")
        if not hasattr(obj, 'DeckOffset'):
            obj.addProperty("App::PropertyLength", "DeckOffset", grp,
                            "Extra lift above the bare roof faces, to clear "
                            "the thickness of an underlying slate/shingle "
                            "course the cap sits on top of (0 = cap rests "
                            "directly on the bare roof faces)")
        if not hasattr(obj, 'HideIncompleteEndCap'):
            obj.addProperty("App::PropertyBool", "HideIncompleteEndCap", grp,
                            "Skip a cap entirely if it would poke past the "
                            "seam's far end, instead of showing a partial "
                            "(possibly sliver) fragment there")
        if not hasattr(obj, 'SeamType'):
            obj.addProperty("App::PropertyString", "SeamType", grp,
                            "Detected seam classification: ridge, valley, "
                            "none, or ambiguous (read-only)")
            obj.setEditorMode("SeamType", 1)
        if not hasattr(obj, 'DihedralDegrees'):
            obj.addProperty("App::PropertyFloat", "DihedralDegrees", grp,
                            "Detected dihedral angle between the two faces, "
                            "in degrees (read-only)")
            obj.setEditorMode("DihedralDegrees", 1)
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.CapWidth             = p.get('cap_width',              4.0)
        obj.CapLength            = p.get('cap_length',              2.5)
        obj.MaterialThickness    = p.get('material_thickness',      0.2)
        obj.Exposure             = p.get('exposure',                1.4)
        obj.DeckOffset           = p.get('deck_offset',              0.0)
        obj.HideIncompleteEndCap = p.get('hide_incomplete_end_cap', False)
        obj.SeamType             = ''
        obj.DihedralDegrees      = 0.0
        obj.GeneratorVersion     = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        face_entries = [(face, link_obj) for face, link_obj, _sub_name
                         in resolve_sources_faces(obj.Sources, "SlateSeamGenerator")]

        if len(face_entries) != 2:
            App.Console.PrintError(
                f"SlateSeamGenerator: need exactly 2 faces, got {len(face_entries)}\n")
            return

        face1, obj1 = face_entries[0]
        face2, obj2 = face_entries[1]

        params = {
            'cap_width':              float(obj.CapWidth),
            'cap_length':             float(obj.CapLength),
            'material_thickness':     float(obj.MaterialThickness),
            'exposure':               float(obj.Exposure),
            'deck_offset':            float(obj.DeckOffset),
            'hide_incomplete_end_cap': bool(obj.HideIncompleteEndCap),
        }

        valid, errors = validate_parameters(
            params['cap_width'], params['cap_length'],
            params['material_thickness'], params['exposure'])
        if not valid:
            App.Console.PrintError(f"SlateSeamGenerator: invalid parameters: {errors}\n")
            return

        shared_edge, r_face1, r_obj1, r_face2, r_obj2 = resolve_shared_edge(
            face1, obj1, face2, obj2, doc=obj.Document)

        if shared_edge is None:
            App.Console.PrintError(
                "SlateSeamGenerator: no shared edge found between the two "
                "faces (or their BaseObjects). Select two adjacent roof "
                "faces sharing a hip/ridge seam.\n")
            obj.SeamType = 'none'
            obj.DihedralDegrees = 0.0
            return

        try:
            shapes, seam_type, dihedral_degrees = _generate_caps(
                shared_edge, r_face1, r_obj1, r_face2, r_obj2, params)
        except Exception as e:
            App.Console.PrintError(f"SlateSeamGenerator execute error: {e}\n")
            return

        obj.SeamType = seam_type
        obj.DihedralDegrees = dihedral_degrees

        if not shapes:
            App.Console.PrintWarning(
                f"SlateSeamGenerator: no caps generated (SeamType={seam_type}, "
                f"DihedralDegrees={dihedral_degrees:.1f})\n")
            return

        obj.Shape = Part.Compound(shapes)
        App.Console.PrintMessage(
            f"SlateSeamGenerator: {len(shapes)} caps generated "
            f"(SeamType={seam_type}, DihedralDegrees={dihedral_degrees:.1f})\n")

    def onDocumentRestored(self, obj):
        """Backfill any properties added since this object was saved --
        _setup_properties' hasattr guards make it safe to call again on an
        object that already has some/all of these properties."""
        self._setup_properties(obj)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "SlateSeamGenerator")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class SlateSeamViewProxy:
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
