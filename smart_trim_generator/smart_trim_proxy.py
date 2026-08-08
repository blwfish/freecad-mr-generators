"""
SmartTrim FeaturePython proxy — parametric trim object for FreeCAD.

Change any property in the panel and the trim regenerates automatically.
Face references are stored as PropertyLinkSubList so they survive save/reload.

This module must be importable by FreeCAD (lives on sys.path via Macro dir).
"""

import FreeCAD as App
import Part

VERSION = "1.5.0"

# Ensure trim_geometry is importable (same directory)
import sys
from pathlib import Path
_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

import trim_geometry as tg
from smart_trim_geometry import validate_trim_parameters  # noqa: E402
from freecad_utils import resolve_sources_faces  # noqa: E402


# =============================================================================
# Helper functions (outward-face detection)
# =============================================================================

def _get_document_centroid(doc, exclude_names=None):
    """Return centroid of all solid objects (visibility-independent)."""
    centers = []
    for obj in doc.Objects:
        if exclude_names and obj.Name in exclude_names:
            continue
        if hasattr(obj, 'Shape') and obj.Shape.BoundBox.isValid():
            try:
                centers.append(obj.Shape.CenterOfMass)
            except Exception:
                centers.append(App.Vector(obj.Shape.BoundBox.Center))
    if not centers:
        return App.Vector(0, 0, 0)
    avg = App.Vector(0, 0, 0)
    for c in centers:
        avg += c
    return avg * (1.0 / len(centers))


def _resolve_outward_face(selected_face, parent_shape, doc=None):
    """Return the outward-facing face of the wall, given any face on it."""
    sel_area = selected_face.Area
    uv = selected_face.Surface.parameter(selected_face.CenterOfMass)
    sel_normal = selected_face.normalAt(uv[0], uv[1])

    # Find opposite face (same area ±5%, opposite normal)
    opposite = None
    for f in parent_shape.Faces:
        if f.CenterOfMass.distanceToPoint(selected_face.CenterOfMass) < 0.01:
            continue
        if abs(f.Area - sel_area) / max(sel_area, 0.01) > 0.05:
            continue
        uv2 = f.Surface.parameter(f.CenterOfMass)
        if sel_normal.dot(f.normalAt(uv2[0], uv2[1])) < -0.9:
            opposite = f
            break

    # Reference point for "outward" direction
    if doc is not None:
        ref_center = _get_document_centroid(doc)
    else:
        try:
            ref_center = parent_shape.CenterOfMass
        except AttributeError:
            ref_center = App.Vector(parent_shape.BoundBox.Center)

    if opposite is None:
        away = selected_face.CenterOfMass - ref_center
        if sel_normal.dot(away) < 0:
            return selected_face.reversed()
        return selected_face

    # Score both faces — pick the one whose normal points most away
    best, best_score = selected_face, -1e9
    for candidate in (selected_face, opposite):
        uvc = candidate.Surface.parameter(candidate.CenterOfMass)
        n = candidate.normalAt(uvc[0], uvc[1])
        score = n.dot(candidate.CenterOfMass - ref_center)
        if score > best_score:
            best, best_score = candidate, score
    return best


def _bbox_corners(bb):
    """Return the 8 corners of a bounding box."""
    return [
        App.Vector(bb.XMin, bb.YMin, bb.ZMin),
        App.Vector(bb.XMax, bb.YMin, bb.ZMin),
        App.Vector(bb.XMin, bb.YMax, bb.ZMin),
        App.Vector(bb.XMax, bb.YMax, bb.ZMin),
        App.Vector(bb.XMin, bb.YMin, bb.ZMax),
        App.Vector(bb.XMax, bb.YMin, bb.ZMax),
        App.Vector(bb.XMin, bb.YMax, bb.ZMax),
        App.Vector(bb.XMax, bb.YMax, bb.ZMax),
    ]



# =============================================================================
# Trim generation (from face_entries + params dict)
# =============================================================================

def generate_trim(face_entries, params, doc=None):
    """Generate a compound of trim pieces for the given faces."""
    all_trim_pieces = []

    # Build profile
    w, h = params['trim_width'], params['trim_height']
    valid, errors = validate_trim_parameters(w, h)
    if not valid:
        raise ValueError(f"Invalid trim parameters: {'; '.join(errors)}")

    if params.get('trim_style') == 'beveled':
        profile = tg.create_beveled_profile(w, h, params.get('bevel_size', 0.5))
    else:
        profile = tg.create_simple_rectangular_profile(w, h)

    for i, entry in enumerate(face_entries, 1):
        # Support both (face, parent_shape) and (face, parent_shape, parent_obj)
        if len(entry) == 3:
            face, parent_shape, parent_obj = entry
        else:
            face, parent_shape = entry
            parent_obj = None
        outward_hint = None
        trim_offset = None

        # Everything for this face lives in one try/except: previously
        # _resolve_outward_face()/analyze_face_for_trim() below ran
        # outside it, so an exception there (e.g. a non-planar or
        # degenerate face breaking Surface.parameter/detect_corners)
        # propagated out of the whole loop and aborted trim generation
        # for every selected face, not just the offending one (full-review
        # finding #25, 2026-08-08).
        try:
            if parent_shape is not None:
                original_face = face
                face = _resolve_outward_face(face, parent_shape, doc=doc)

                # Outward hint from document centroid
                if doc is not None:
                    ref_center = _get_document_centroid(doc)
                    hint_vec = face.CenterOfMass - ref_center
                    if hint_vec.Length > 1e-6:
                        outward_hint = hint_vec

                # Wall offset for reversed faces
                if (face is not original_face
                        and face.CenterOfMass.distanceToPoint(
                            original_face.CenterOfMass) < 0.01):
                    uv = face.Surface.parameter(face.CenterOfMass)
                    outward_normal = face.normalAt(uv[0], uv[1])
                    corners = _bbox_corners(parent_shape.BoundBox)
                    face_pos = face.CenterOfMass
                    max_proj = max(
                        (c - face_pos).dot(outward_normal) for c in corners)
                    if max_proj > 0.01:
                        trim_offset = outward_normal * max_proj

            # Fix reversed faces (all-internal-270° heuristic)
            analysis = tg.analyze_face_for_trim(face)
            if (analysis['num_internal'] == analysis['num_corners']
                    and analysis['num_corners'] > 0):
                avg_angle = (sum(c.angle for c in analysis['all_corners'])
                             / len(analysis['all_corners']))
                if 260 < avg_angle < 280:
                    face = face.reversed()
                    analysis = tg.analyze_face_for_trim(face)

            # Generate trim segments
            pieces = tg.generate_trim_for_face(
                face, profile,
                outward_hint=outward_hint,
                skip_bottom=params.get('skip_bottom', True),
                perimeter_only=params.get('perimeter_only', True),
                edge_types=params.get('edge_types', None),
            )

            # Filter to a single edge if requested (1-based index)
            only = params.get('only_edge', 0)
            if only > 0:
                if only <= len(pieces):
                    pieces = [pieces[only - 1]]
                else:
                    # Previously silently left `pieces` unfiltered (showing
                    # every edge) instead of erroring or warning when
                    # OnlyEdge pointed past the actual piece count -- e.g.
                    # because skip_bottom/perimeter_only filtering produced
                    # fewer pieces than expected (finding #37, 2026-08-08).
                    App.Console.PrintWarning(
                        f"  Face {i}: OnlyEdge={only} but only {len(pieces)} "
                        f"trim piece(s) available -- showing all edges\n")

            if trim_offset is not None:
                pieces = [p.translated(trim_offset) for p in pieces]

            # Flip to opposite side
            if params.get('flip', False) and parent_shape is not None:
                face_normal = tg._get_face_normal(face)
                face_normal = tg._ensure_outward_normal(
                    face, face_normal, outward_hint)
                corners = _bbox_corners(
                    parent_shape.BoundBox if parent_shape else face.BoundBox)
                face_pos = face.CenterOfMass
                max_proj = max(
                    (c - face_pos).dot(face_normal) for c in corners)
                min_proj = min(
                    (c - face_pos).dot(face_normal) for c in corners)
                wall_thickness = max_proj - min_proj
                flip_dist = wall_thickness + 2 * params['trim_width']
                pieces = [p.translated(face_normal * (-flip_dist))
                          for p in pieces]

            all_trim_pieces.extend(pieces)
        except Exception as e:
            App.Console.PrintError(f"  Face {i}: {e}\n")
            import traceback
            traceback.print_exc()

    if not all_trim_pieces:
        raise RuntimeError("No trim pieces were generated")

    return Part.makeCompound(all_trim_pieces)


# =============================================================================
# FeaturePython proxy
# =============================================================================

class SmartTrimProxy:
    """Parametric trim object.  Change a property → shape updates."""

    Type = "SmartTrim"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    # -- property setup -------------------------------------------------------

    @staticmethod
    def _setup_properties(obj):
        grp = "Trim"

        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Wall faces to apply trim to")

        if not hasattr(obj, 'TrimWidth'):
            obj.addProperty(
                "App::PropertyLength", "TrimWidth", grp,
                "Trim width perpendicular to wall")
        if not hasattr(obj, 'TrimHeight'):
            obj.addProperty(
                "App::PropertyLength", "TrimHeight", grp,
                "Trim height parallel to wall surface")

        if not hasattr(obj, 'TrimStyle'):
            obj.addProperty(
                "App::PropertyEnumeration", "TrimStyle", grp,
                "Profile style")
            obj.TrimStyle = ['rectangular', 'beveled']
        if not hasattr(obj, 'BevelSize'):
            obj.addProperty(
                "App::PropertyLength", "BevelSize", grp,
                "Bevel size (if beveled style)")

        if not hasattr(obj, 'SkipBottom'):
            obj.addProperty(
                "App::PropertyBool", "SkipBottom", grp,
                "Skip bottom (foundation) edge")
        if not hasattr(obj, 'PerimeterOnly'):
            obj.addProperty(
                "App::PropertyBool", "PerimeterOnly", grp,
                "Skip internal construction joints")
        if not hasattr(obj, 'Flip'):
            obj.addProperty(
                "App::PropertyBool", "Flip", grp,
                "Flip trim to opposite side of wall")

        if not hasattr(obj, 'OnlyEdge'):
            obj.addProperty(
                "App::PropertyInteger", "OnlyEdge", grp,
                "Only trim edge N (0=all, 1=first, 2=second, ...)")

        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty(
                "App::PropertyString", "GeneratorVersion", grp,
                "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    # -- defaults -------------------------------------------------------------

    @staticmethod
    def set_defaults(obj, params=None):
        """Apply parameter values to the object's properties."""
        if params is None:
            params = {}
        obj.TrimWidth = params.get('trim_width', 0.5)
        obj.TrimHeight = params.get('trim_height', 2.0)
        obj.TrimStyle = params.get('trim_style', 'rectangular')
        obj.BevelSize = params.get('bevel_size', 0.5)
        obj.SkipBottom = params.get('skip_bottom', True)
        obj.PerimeterOnly = params.get('perimeter_only', True)
        obj.Flip = params.get('flip', False)
        obj.OnlyEdge = params.get('only_edge', 0)
        obj.GeneratorVersion = VERSION

    # -- execute (called on recompute) ----------------------------------------

    def execute(self, obj):
        if not obj.Sources:
            return

        # Resolve LinkSubList → (face, parent_shape, parent_obj) tuples
        face_entries = [(face, link_obj.Shape, link_obj) for face, link_obj, _sub_name
                         in resolve_sources_faces(obj.Sources, "SmartTrimProxy")]

        if not face_entries:
            return

        params = {
            'trim_width':    float(obj.TrimWidth),
            'trim_height':   float(obj.TrimHeight),
            'trim_style':    str(obj.TrimStyle),
            'bevel_size':    float(obj.BevelSize),
            'skip_bottom':   bool(obj.SkipBottom),
            'perimeter_only': bool(obj.PerimeterOnly),
            'flip':          bool(obj.Flip),
            'only_edge':     int(obj.OnlyEdge),
            'edge_types':    ['vertical'],
        }

        try:
            compound = generate_trim(face_entries, params, doc=obj.Document)
            obj.Shape = compound
        except Exception as e:
            App.Console.PrintError(f"SmartTrim execute error: {e}\n")

    # -- serialisation --------------------------------------------------------

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "SmartTrim")

    # Legacy names (FreeCAD < 0.21.2)
    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class SmartTrimViewProxy:
    """View provider — just keeps the icon and default colour."""

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
