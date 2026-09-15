"""
Slate Tile FeaturePython proxy — parametric slate roof generator for FreeCAD.

Flat rectangular tiles of uniform thickness, laid in staggered courses.
The butt-step shadow at each course comes from the overlap geometry alone
(no wedge taper as in wood shingles).

Change any property in the Properties panel and the tiles regenerate.
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "1.0.0"

_here = Path(__file__).parent
for _p in (str(_here), str(_here / '_lib')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from slate_geometry import (
    validate_parameters,
    validate_stagger_pattern,
    calculate_layout,
    calculate_stagger_offset,
    calculate_course_v_position,
    is_valid_clip_fragment,
    calculate_fitted_exposure,
)
from freecad_utils import (  # noqa: E402
    resolve_sources_faces, get_roof_face_coordinate_system, GenericViewProxy,
    add_property,
)


# ---------------------------------------------------------------------------
# FreeCAD geometry helpers (shared pattern with shingle_proxy.py)
# ---------------------------------------------------------------------------

def _sv(vec, scale):
    """Scale a FreeCAD Vector."""
    return App.Vector(vec.x * scale, vec.y * scale, vec.z * scale)


def _get_face_coordinate_system(face):
    """
    Extract U/V/normal coordinate system from a roof face.
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
    """Dual-direction extrusion clip volumes from a face."""
    depth = 100.0
    n = face.normalAt(0.5, 0.5)
    if n.Length > 1e-9:
        n.normalize()
    return [face.extrude(n * depth), face.extrude(n * (-depth))]


def _clip_shape(shape, clip_volumes):
    """Clip *shape* against dual clip volumes. Returns clipped solid or None.

    Survival is judged against the shape's own pre-clip volume (see
    is_valid_clip_fragment) rather than a fixed absolute threshold, so a
    razor-thin sliver at a ridge/hip boundary is discarded instead of
    surviving as a stray fragment.
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


# ---------------------------------------------------------------------------
# Tile generation
# ---------------------------------------------------------------------------

def _generate_tiles_for_face(face, params):
    """Generate slate tile solids for one roof face."""
    tile_width   = params['tile_width']
    tile_height  = params['tile_height']
    mat_thick    = params['material_thickness']
    butt_thick   = params['butt_thickness']
    exposure     = params['exposure']
    stagger_pat  = params['stagger_pattern']

    origin, u_vec, v_vec, normal, u_length, v_length = \
        _get_face_coordinate_system(face)

    # Rack the exposure so an integer number of courses spans exactly to
    # the ridge/hip line -- the last course's head then lands exactly at
    # v_length instead of leaving a remainder that would otherwise produce
    # a clipped partial/sliver fragment (or, before 2026-09-14, a
    # redundant extra course past it -- see the stop_tolerance check
    # below).
    exposure = calculate_fitted_exposure(v_length, exposure)

    layout = calculate_layout(u_length, v_length, tile_width, exposure, stagger_pat)
    num_courses     = layout['num_courses']
    tiles_per_course = layout['tiles_per_course']
    max_stagger     = layout['max_stagger']

    try:
        clip_volumes = _build_clip_volumes(face)
    except Exception:
        clip_volumes = None

    rotation_matrix = App.Matrix(
        u_vec.x, v_vec.x, normal.x, 0,
        u_vec.y, v_vec.y, normal.y, 0,
        u_vec.z, v_vec.z, normal.z, 0,
        0, 0, 0, 1,
    )
    rotation = App.Rotation(rotation_matrix)

    # Tolerance for the "should we stop generating rows" decision below --
    # deliberately looser than is_top_course_complete()'s own exact `<=`
    # (used as-is by the optional hide_incomplete_top_course feature,
    # untouched here). calculate_fitted_exposure() computes exposure so
    # that MATHEMATICALLY an integer number of courses lands exactly on
    # v_length, but the actual float arithmetic in calculate_course_v_
    # position (row * exposure - exposure) can land a few ULPs above the
    # true value (confirmed live: row*exposure-exposure computed
    # 15.400000000000002 for an intended-exact 15.4) -- is_top_course_
    # complete()'s strict `<=` would then misclassify the intended-exact
    # top course itself as "incomplete" and skip it, leaving a real gap
    # at the ridge instead of eliminating a redundant stub. Same
    # magnitude convention as calculate_course_v_position's own nudge.
    stop_tolerance = abs(exposure) * 0.001

    shapes = []
    for row in range(num_courses):
        raw_v = calculate_course_v_position(row, exposure)

        # Skip this course entirely (never generate it) rather than
        # generate-then-clip-then-maybe-discard, once its head already
        # pokes past the face's own top edge (ridge/hip line at
        # V=v_length) by more than stop_tolerance. Rows increase v
        # monotonically, so once this trips, every subsequent row would
        # too -- but check explicitly rather than break, in case that
        # assumption ever stops holding. Uses the raw (un-nudged)
        # position -- the boundary-safety nudge below must not change
        # whether a course counts as complete.
        #
        # Unconditional as of 2026-09-14 (previously gated behind the
        # optional hide_incomplete_top_course flag, generating every "+3
        # buffer" row past the ridge by default and relying on clipping to
        # trim them). Since exposure is *always* fitted just above,
        # calculate_fitted_exposure() guarantees an integer number of
        # courses lands the top course exactly on the ridge/hip line --
        # every course past that one is therefore pure redundant overlap
        # with zero legitimate new coverage, never a genuinely-needed
        # partial course. For a flat tile that redundancy used to clip to
        # a harmless thin sliver (caught by is_valid_clip_fragment's
        # volume-ratio threshold). For a WEDGE tile (butt_thickness >
        # material_thickness, the default whenever ButtThickness=0) it
        # was NOT harmless: confirmed live on a real hip roof, the clip
        # boundary can fall near the wedge's THICK butt end instead of its
        # thin head, so a substantial, visually prominent stub survived
        # well above the 5% discard threshold -- sitting right on top of
        # the already-complete course below it, unhidden, at the ridge/hip
        # line. hide_incomplete_top_course's own distinct behavior is now
        # moot in practice (there is no longer a "genuinely incomplete"
        # top course left for it to hide, since fitting always makes one
        # exact) -- the property is left in place rather than removed, in
        # case some future caller ever reaches this code without fitting.
        if raw_v > v_length + stop_tolerance:
            continue

        # calculate_fitted_exposure() (above) deliberately makes an
        # integer number of courses divide v_length exactly, so the top
        # complete course's head can land EXACTLY on the ridge/hip
        # boundary -- coincident with the same boundary _clip_shape()
        # clips against below. calculate_course_v_position() nudges that
        # one course's placement strictly past the boundary so it always
        # overflows, never coincides (the OCCT crash class
        # shared/boundary_assertions.py exists to prevent).
        v = calculate_course_v_position(row, exposure, v_length)

        stagger = calculate_stagger_offset(row, stagger_pat, tile_width)
        for col in range(tiles_per_course):
            u = col * tile_width + stagger - max_stagger

            top_pos  = origin + _sv(u_vec, u) + _sv(v_vec, v)
            butt_pos = top_pos + _sv(v_vec, -tile_height)

            if row == 0 or butt_thick <= mat_thick:
                # Starter course or no wedge: flat box
                tile = Part.makeBox(tile_width, tile_height, mat_thick)
            else:
                # Wedge cross-section: thick at butt, tapers to near-zero at head.
                # Local space: X=u_vec, Y=v_vec (up-slope), Z=normal (outward).
                # The butt sits elevated above the tile below; the head rests near
                # the deck so the next tile above can sit on this one's face.
                top_thick = butt_thick * 0.2
                p0 = App.Vector(0, 0, 0)
                p1 = App.Vector(0, 0, butt_thick)
                p2 = App.Vector(0, tile_height, top_thick)
                p3 = App.Vector(0, tile_height, 0)
                profile = Part.Wire([
                    Part.LineSegment(p0, p1).toShape(),
                    Part.LineSegment(p1, p2).toShape(),
                    Part.LineSegment(p2, p3).toShape(),
                    Part.LineSegment(p3, p0).toShape(),
                ])
                tile = Part.Face(profile).extrude(App.Vector(tile_width, 0, 0))

            tile.Placement = App.Placement(butt_pos, rotation)

            if clip_volumes is not None:
                clipped = _clip_shape(tile, clip_volumes)
                if clipped is not None:
                    shapes.append(clipped)
            else:
                shapes.append(tile)

    return shapes


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class SlateProxy:
    """Parametric slate tile object. Change a property → tiles update."""

    Type = "SlateGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "Slate"
        add_property(obj, "App::PropertyLinkSubList", 'Sources', grp,
            "Roof faces to apply slate to")
        add_property(obj, "App::PropertyLength", 'TileWidth', grp, "Width of each slate tile")
        add_property(obj, "App::PropertyLength", 'TileHeight', grp,
            "Height (length) of each slate tile")
        add_property(obj, "App::PropertyLength", 'MaterialThickness', grp, "Slate thickness")
        add_property(obj, "App::PropertyLength", 'Exposure', grp, "Exposed portion per course")
        add_property(obj, "App::PropertyLength", 'ButtThickness', grp,
            "Tile thickness at butt edge (0 = auto: 3× MaterialThickness)")
        add_property(obj, "App::PropertyEnumeration", 'StaggerPattern', grp,
            "Horizontal stagger pattern", default=['half', 'third', 'none'])
        add_property(
            obj,
            "App::PropertyBool",
            'HideIncompleteTopCourse',
            grp,
            "Skip the top course entirely if the ridge/hip "
                            "line would cut through it, instead of showing "
                            "a partial (possibly sliver) fragment there")
        add_property(obj, "App::PropertyString", 'GeneratorVersion', grp,
            "Generator version (read-only)", editor_mode=1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.TileWidth         = p.get('tile_width',          2.0)
        obj.TileHeight        = p.get('tile_height',          2.5)
        obj.MaterialThickness = p.get('material_thickness',   0.2)
        obj.ButtThickness     = p.get('butt_thickness',       0.0)
        # Exposure close to TileHeight (ratio ~1.14, was 1.2 -> ~2.08) gives
        # single-thickness coverage with just enough overlap for the
        # butt-shadow line -- these tiles sit on an already-solid roof face,
        # so full double-lap (real-slate) coverage isn't needed on the model.
        obj.Exposure          = p.get('exposure',             2.2)
        obj.StaggerPattern    = p.get('stagger_pattern',     'half')
        obj.HideIncompleteTopCourse = p.get('hide_incomplete_top_course', False)
        obj.GeneratorVersion  = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        mat_thick  = float(obj.MaterialThickness)
        butt_thick = float(obj.ButtThickness)
        if butt_thick == 0:
            butt_thick = mat_thick * 3
        elif butt_thick <= mat_thick:
            # Every non-starter course falls back to a flat box at
            # mat_thick (see the row == 0 or butt_thick <= mat_thick
            # branch in _generate_tiles_for_face) instead of the wedge
            # profile ButtThickness implies. Warn once per execute() so
            # the user isn't silently shown geometry that doesn't match
            # the property panel's ButtThickness value.
            App.Console.PrintWarning(
                f"SlateGenerator: ButtThickness ({butt_thick}mm) <= "
                f"MaterialThickness ({mat_thick}mm) -- building tile at "
                "MaterialThickness instead; increase ButtThickness for a "
                "stepped course profile.\n")

        params = {
            'tile_width':         float(obj.TileWidth),
            'tile_height':        float(obj.TileHeight),
            'material_thickness': mat_thick,
            'butt_thickness':     butt_thick,
            'exposure':           float(obj.Exposure),
            'stagger_pattern':    str(obj.StaggerPattern),
            'hide_incomplete_top_course': bool(obj.HideIncompleteTopCourse),
        }

        valid, errors = validate_parameters(
            params['tile_width'], params['tile_height'],
            params['material_thickness'], params['exposure'])
        if not valid:
            App.Console.PrintError(f"SlateGenerator: invalid parameters: {errors}\n")
            return

        valid, msg = validate_stagger_pattern(params['stagger_pattern'])
        if not valid:
            App.Console.PrintError(f"SlateGenerator: {msg}\n")
            return

        all_tiles = []
        for face, link_obj, sub_name in resolve_sources_faces(obj.Sources, "SlateGenerator"):
            try:
                all_tiles.extend(_generate_tiles_for_face(face, params))
            except Exception as e:
                App.Console.PrintError(
                    f"  {link_obj.Label}.{sub_name}: {e}\n")

        if not all_tiles:
            App.Console.PrintWarning("SlateGenerator: no tiles generated\n")
            return

        obj.Shape = Part.Compound(all_tiles)

    def onDocumentRestored(self, obj):
        """Backfill any properties added since this object was saved (e.g.
        HideIncompleteTopCourse) -- _setup_properties' hasattr guards make
        it safe to call again on an object that already has some/all of
        these properties."""
        self._setup_properties(obj)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "SlateGenerator")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class SlateViewProxy(GenericViewProxy):
    ICON = ":/icons/Part_Box.svg"
