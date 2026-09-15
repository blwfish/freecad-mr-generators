"""
Shingle FeaturePython proxy — parametric shingle generator for FreeCAD.

Change any property in the panel and the shingles regenerate automatically.
Face references are stored as PropertyLinkSubList so they survive save/reload.
Properties can be bound to spreadsheets or VarSets via expressions (right-click
→ Set expression).

This module must be importable by FreeCAD (lives on sys.path via Macro dir).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "6.0.0"

# Ensure geometry library is importable (same directory)
_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

from shingle_geometry import (
    validate_parameters,
    validate_stagger_pattern,
    calculate_shingle_placements,
    is_valid_clip_fragment,
)
from freecad_utils import (  # noqa: E402
    resolve_sources_faces, get_roof_face_coordinate_system, GenericViewProxy,
    add_property,
)


# =============================================================================
# Helpers (face coordinate system, clipping)
# =============================================================================

def _scale_vector(vec, scale):
    """Scale a FreeCAD Vector by a scalar."""
    return App.Vector(vec.x * scale, vec.y * scale, vec.z * scale)


def _get_face_coordinate_system(face):
    """
    Extract coordinate system from a planar roof face using bounding-box method.

    Returns (origin, u_vec, v_vec, normal, u_length, v_length).

    Full-review finding freecad-mr-generators-20260915-e612#11: thin
    wrapper around shared/freecad_utils.get_roof_face_coordinate_system,
    the single source of truth for this logic -- previously an
    independent copy-pasted-near-verbatim implementation here and in four
    sibling roof-facing proxies, with no shared function and no parity
    test.
    """
    return get_roof_face_coordinate_system(face)


def _build_clip_volumes(face):
    """Create dual-direction extrusion clip volumes from a face."""
    extrusion_depth = 100.0
    topo_normal = face.normalAt(0.5, 0.5)
    if topo_normal.Length > 1e-9:
        topo_normal.normalize()
    clip_pos = face.extrude(topo_normal * extrusion_depth)
    clip_neg = face.extrude(topo_normal * (-extrusion_depth))
    return [clip_pos, clip_neg]


def _clip_shape(shape, clip_volumes):
    """Clip a shape against dual clip volumes. Returns clipped shape or None.

    Survival is judged against the shape's own pre-clip volume (see
    is_valid_clip_fragment) rather than a fixed absolute threshold, so a
    razor-thin sliver at a face boundary is discarded instead of surviving
    as a stray fragment -- the same fix already applied to slate_proxy.py,
    slate_seam_proxy.py, and standing_seam_proxy.py after a documented real
    incident (a 0.02mm^3 sliver surviving as ~1% of a 1.8mm^3 tile on a hip
    roof); this proxy was missed by that fix.
    """
    full_volume = shape.Volume
    for cv in clip_volumes:
        try:
            result = shape.common(cv)
            if result.ShapeType == 'Compound' and len(result.Solids) == 1:
                result = result.Solids[0]
            if is_valid_clip_fragment(result.Volume, full_volume):
                return result
        except Exception:
            continue
    return None


# =============================================================================
# Shingle generation (from face + params dict)
# =============================================================================

def _generate_shingles_for_face(face, params):
    """Generate shingle shapes for a single face. Returns list of Solids."""
    shingle_width = params['shingle_width']
    shingle_height = params['shingle_height']
    material_thickness = params['material_thickness']
    exposure = params['shingle_exposure']
    stagger_pattern = params['stagger_pattern']
    wedge_thickness = params['wedge_thickness']
    chamfer = params['chamfer']

    origin, u_vec, v_vec, normal, u_length, v_length = \
        _get_face_coordinate_system(face)

    # Full-review finding freecad-mr-generators-20260915-e612#14: the
    # per-shingle position AND the row-skip/row-break survival logic
    # deciding which courses actually get placed used to be inlined here
    # directly, with no pure-Python form to write a boundary-overflow
    # test against. shingle_geometry.calculate_shingle_placements() is
    # now the single source of truth for both -- see its own docstring.
    placements = calculate_shingle_placements(
        u_length, v_length, shingle_width, shingle_height,
        exposure, stagger_pattern)

    # Build clip volumes
    try:
        clip_volumes = _build_clip_volumes(face)
    except Exception:
        clip_volumes = None

    # Build rotation matrix (right-handed, det=+1)
    rotation_matrix = App.Matrix(
        u_vec.x, v_vec.x, normal.x, 0,
        u_vec.y, v_vec.y, normal.y, 0,
        u_vec.z, v_vec.z, normal.z, 0,
        0, 0, 0, 1
    )
    final_rotation = App.Rotation(rotation_matrix)

    shingle_shapes = []

    for placement in placements:
        row, u, v, is_starter = (placement['row'], placement['u'],
                                  placement['v'], placement['is_starter'])

        top_position = (origin
                        + _scale_vector(u_vec, u)
                        + _scale_vector(v_vec, v))

        if is_starter:
            # Starter course: rectangular box
            shingle_shape = Part.makeBox(shingle_width, exposure,
                                         material_thickness)
            butt_position = top_position + _scale_vector(v_vec, -exposure)
        else:
            # Tapered trapezoidal cross-section
            top_thick = wedge_thickness * 0.2
            p0 = App.Vector(0, 0, 0)
            p1 = App.Vector(0, 0, wedge_thickness)
            p2 = App.Vector(0, shingle_height, top_thick)
            p3 = App.Vector(0, shingle_height, 0)

            profile_wire = Part.Wire([
                Part.LineSegment(p0, p1).toShape(),
                Part.LineSegment(p1, p2).toShape(),
                Part.LineSegment(p2, p3).toShape(),
                Part.LineSegment(p3, p0).toShape(),
            ])
            profile_face = Part.Face(profile_wire)
            shingle_shape = profile_face.extrude(
                App.Vector(shingle_width, 0, 0))
            butt_position = top_position + _scale_vector(v_vec,
                                                         -shingle_height)

        # Chamfer one vertical edge
            if chamfer > 0:
                try:
                    bb = shingle_shape.BoundBox
                    best_edge = None
                    best_score = -1
                    for edge in shingle_shape.Edges:
                        verts = edge.Vertexes
                        if len(verts) != 2:
                            continue
                        v0, v1 = verts[0].Point, verts[1].Point
                        avg_x = (v0.x + v1.x) / 2.0
                        avg_z = (v0.z + v1.z) / 2.0
                        score = avg_x / bb.XLength + avg_z / bb.ZLength
                        dy = abs(v1.y - v0.y)
                        if dy > edge.Length * 0.9 and score > best_score:
                            best_score = score
                            best_edge = edge
                    if best_edge is not None:
                        chamfered = shingle_shape.makeChamfer(chamfer,
                                                              [best_edge])
                        if (chamfered.ShapeType == 'Compound'
                                and len(chamfered.Solids) == 1):
                            shingle_shape = chamfered.Solids[0]
                        else:
                            shingle_shape = chamfered
                except Exception:
                    pass

            shingle_shape.Placement = App.Placement(butt_position,
                                                    final_rotation)

            # Clip to face boundary
            if clip_volumes is not None:
                clipped = _clip_shape(shingle_shape, clip_volumes)
                if clipped is not None:
                    shingle_shapes.append(clipped)
            else:
                shingle_shapes.append(shingle_shape)

    return shingle_shapes


# =============================================================================
# FeaturePython proxy
# =============================================================================

class ShingleProxy:
    """Parametric shingle object. Change a property -> shingles update."""

    Type = "ShingleGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    # -- property setup -------------------------------------------------------

    @staticmethod
    def _setup_properties(obj):
        grp = "Shingle"

        add_property(obj, "App::PropertyLinkSubList", 'Sources', grp,
            "Roof faces to apply shingles to")

        add_property(obj, "App::PropertyLength", 'ShingleWidth', grp, "Width of each shingle")
        add_property(obj, "App::PropertyLength", 'ShingleHeight', grp,
            "Height (length) of each shingle")
        add_property(obj, "App::PropertyLength", 'MaterialThickness', grp,
            "Material sheet thickness")
        add_property(obj, "App::PropertyLength", 'Exposure', grp, "Exposed portion per course")

        add_property(obj, "App::PropertyEnumeration", 'StaggerPattern', grp,
            "Horizontal stagger pattern", default=['half', 'third', 'none'])

        add_property(obj, "App::PropertyLength", 'WedgeThickness', grp,
            "Butt-edge wedge thickness (0 = auto: 1x material)")
        add_property(obj, "App::PropertyLength", 'Chamfer', grp,
            "V-groove chamfer at shingle edge (0 = auto: 1.5x material)")

        add_property(obj, "App::PropertyString", 'GeneratorVersion', grp,
            "Generator version (read-only)", editor_mode=1)

    # -- defaults -------------------------------------------------------------

    @staticmethod
    def set_defaults(obj, params=None):
        """Apply parameter values to the object's properties."""
        if params is None:
            params = {}
        obj.ShingleWidth = params.get('shingle_width', 3.5)
        obj.ShingleHeight = params.get('shingle_height', 2.0)
        obj.MaterialThickness = params.get('material_thickness', 0.25)
        obj.Exposure = params.get('shingle_exposure', 1.5)
        obj.StaggerPattern = params.get('stagger_pattern', 'half')
        obj.WedgeThickness = params.get('wedge_thickness', 0.0)
        obj.Chamfer = params.get('chamfer', 0.0)
        obj.GeneratorVersion = VERSION

    # -- execute (called on recompute) ----------------------------------------

    def execute(self, obj):
        if not obj.Sources:
            return

        # Resolve auto values
        mat_thick = float(obj.MaterialThickness)
        wedge = float(obj.WedgeThickness)
        if wedge == 0:
            # v5.4.0 fix (ported from the old macro): 1x, not 3x -- 3x
            # produced a ~17-degree visible tilt of the exposed face;
            # 1x gives the realistic ~6 degrees.
            wedge = mat_thick * 1
        chamfer = float(obj.Chamfer)
        if chamfer == 0:
            chamfer = mat_thick * 1.5

        params = {
            'shingle_width':      float(obj.ShingleWidth),
            'shingle_height':     float(obj.ShingleHeight),
            'material_thickness': mat_thick,
            'shingle_exposure':   float(obj.Exposure),
            'stagger_pattern':    str(obj.StaggerPattern),
            'wedge_thickness':    wedge,
            'chamfer':            chamfer,
        }

        # Validate
        valid, errors = validate_parameters(
            params['shingle_width'], params['shingle_height'],
            params['material_thickness'], params['shingle_exposure'])
        if not valid:
            App.Console.PrintError(
                f"ShingleGenerator: invalid parameters: {errors}\n")
            return

        valid, msg = validate_stagger_pattern(params['stagger_pattern'])
        if not valid:
            App.Console.PrintError(f"ShingleGenerator: {msg}\n")
            return

        # Resolve LinkSubList -> faces. resolve_sources_faces() calls
        # getElement() inside its own per-entry try/except, so a stale
        # sub_name after a topology change skips just that face instead of
        # aborting the whole loop (this proxy previously called getElement()
        # directly, outside any try/except -- the same bug a same-day fix
        # already covered in 8 sibling proxies but missed here).
        all_shingles = []
        for face, link_obj, sub_name in resolve_sources_faces(obj.Sources, "ShingleGenerator"):
            try:
                pieces = _generate_shingles_for_face(face, params)
                all_shingles.extend(pieces)
            except Exception as e:
                App.Console.PrintError(
                    f"  {link_obj.Label}.{sub_name}: {e}\n")

        if not all_shingles:
            App.Console.PrintWarning("ShingleGenerator: no shingles generated\n")
            return

        obj.Shape = Part.Compound(all_shingles)

    # -- serialisation --------------------------------------------------------

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "ShingleGenerator")

    # Legacy names (FreeCAD < 0.21.2)
    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class ShingleViewProxy(GenericViewProxy):
    ICON = ":/icons/Part_Box.svg"
