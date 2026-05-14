"""
SmartTrim FeaturePython proxy — parametric trim object for FreeCAD.

Change any property in the panel and the trim regenerates automatically.
Face references are stored as PropertyLinkSubList so they survive save/reload.

This module must be importable by FreeCAD (lives on sys.path via Macro dir).
"""

import FreeCAD as App
import Part

VERSION = "1.7.0"

# Ensure trim_geometry is importable (same directory)
import sys
from pathlib import Path
_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

import trim_geometry as tg


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
# Convex corner fill helpers
# =============================================================================

def _get_face_vertical_edges(face, perimeter_only=True, vertical_axis='z'):
    """Return vertical (optionally perimeter-only) edges of a face."""
    edges = tg.get_face_boundary_edges(face)
    bbox = face.BoundBox
    result = []
    for edge in edges:
        if tg.classify_edge_direction(edge, vertical_axis) != 'vertical':
            continue
        if perimeter_only and not tg._is_perimeter_edge(edge, bbox, vertical_axis):
            continue
        result.append(edge)
    return result


def _find_shared_corner_edges(edges_A, edges_B, tolerance=0.5):
    """
    Find edges from two faces that share the same geometric line.

    Two edges share a line when both endpoint pairs coincide within tolerance
    (order-independent — winding direction may differ between faces).

    Returns:
        List of (start_pt, end_pt, tangent_A, tangent_B) tuples with
        start_pt.z <= end_pt.z.  tangent_A/B are the CCW-winding tangents of
        the respective edges at their FirstParameter (needed to compute each
        face's -binormal direction for corner clipping).
    """
    shared = []
    for eA in edges_A:
        pA1 = eA.valueAt(eA.FirstParameter)
        pA2 = eA.valueAt(eA.LastParameter)
        for eB in edges_B:
            pB1 = eB.valueAt(eB.FirstParameter)
            pB2 = eB.valueAt(eB.LastParameter)
            match = ((pA1.distanceToPoint(pB1) < tolerance and
                      pA2.distanceToPoint(pB2) < tolerance) or
                     (pA1.distanceToPoint(pB2) < tolerance and
                      pA2.distanceToPoint(pB1) < tolerance))
            if match:
                # Sort so start has smaller Z (bottom of corner line)
                start = pA1 if pA1.z <= pA2.z else pA2
                end   = pA2 if pA1.z <= pA2.z else pA1
                tA = eA.tangentAt(eA.FirstParameter)
                tB = eB.tangentAt(eB.FirstParameter)
                shared.append((start, end, tA, tB))
    return shared


def _neg_binormal(tangent, face_normal):
    """
    Return the direction a trim piece extends from an edge along the wall
    surface: -(tangent × face_normal), normalised.  Returns None if degenerate.
    """
    import FreeCAD as App
    t = App.Vector(tangent);  t.normalize()
    n = App.Vector(face_normal); n.normalize()
    nb = t.cross(n) * -1.0
    if nb.Length < 1e-6:
        return None
    nb.normalize()
    return nb


# =============================================================================
# Trim generation (from face_entries + params dict)
# =============================================================================

def generate_trim(face_entries, params, doc=None):
    """Generate a compound of trim pieces for the given faces."""
    per_face_pieces = []  # list[list[solid]] — one list per successfully processed face
    face_data = []        # [(outward_normal, vertical_edges)] — parallel to per_face_pieces
    all_fill_pieces = []  # convex corner fill prisms (added after clipping)

    # Build profile
    w, h = params['trim_width'], params['trim_height']
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
        try:
            # Outward face normal (needed for corner passes)
            fn = tg._get_face_normal(face)
            fn = tg._ensure_outward_normal(face, fn, outward_hint)
            vert_edges = _get_face_vertical_edges(
                face, perimeter_only=params.get('perimeter_only', True))

            pieces = tg.generate_trim_for_face(
                face, profile,
                outward_hint=outward_hint,
                skip_bottom=params.get('skip_bottom', True),
                perimeter_only=params.get('perimeter_only', True),
                edge_types=params.get('edge_types', None),
            )

            # Filter to a single edge if requested (1-based index)
            only = params.get('only_edge', 0)
            if only > 0 and only <= len(pieces):
                pieces = [pieces[only - 1]]

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

            # Keep per-face lists aligned: both appended together on success
            per_face_pieces.append(pieces)
            face_data.append((fn, vert_edges))

        except Exception as e:
            App.Console.PrintError(f"  Face {i}: {e}\n")
            import traceback
            traceback.print_exc()

    # Corner passes only make sense with ≥2 faces and no single-edge debug mode
    _corner_passes_ok = (
        not params.get('flip', False)
        and params.get('only_edge', 0) == 0
        and len(face_data) >= 2
    )

    if _corner_passes_ok:
        nf = len(face_data)
        for i in range(nf):
            fn_i, edges_i = face_data[i]
            for j in range(i + 1, nf):
                fn_j, edges_j = face_data[j]

                # Only process perpendicular face pairs (building corners).
                # Coplanar/antiparallel pairs (parallel walls, construction
                # joints) are skipped.
                dot = fn_i.dot(fn_j)
                if abs(dot) > 0.85:
                    continue

                shared = _find_shared_corner_edges(edges_i, edges_j)
                if not shared:
                    continue

                for (start_pt, end_pt, tang_i, tang_j) in shared:

                    # --- Pass A: equalise visible trim widths ---
                    # Clip each face's pieces at the adjacent face's plane,
                    # keeping only the part that extends in the trim's natural
                    # direction (-binormal).  This removes any overshoot caused
                    # by one wall face extending past the logical corner centre.
                    if params.get('equalize_corners', True):
                        nb_i = _neg_binormal(tang_i, fn_i)
                        nb_j = _neg_binormal(tang_j, fn_j)

                        if nb_i is not None:
                            per_face_pieces[i] = [
                                tg.clip_solid_at_plane(
                                    p, start_pt, fn_j, nb_i)
                                for p in per_face_pieces[i]
                            ]
                        if nb_j is not None:
                            per_face_pieces[j] = [
                                tg.clip_solid_at_plane(
                                    p, start_pt, fn_i, nb_j)
                                for p in per_face_pieces[j]
                            ]

                    # --- Pass B: convex corner fill ---
                    # Add the TrimWidth×TrimWidth prism that fills the gap
                    # between the two trim boards at the corner.
                    if params.get('convex_corner_fill', True):
                        fill = tg.create_building_corner_fill(
                            start_pt, end_pt, fn_i, fn_j,
                            params['trim_width'])
                        if fill is not None:
                            all_fill_pieces.append(fill)

    # Combine: clipped per-face pieces + fill prisms
    all_trim_pieces = [p for pieces in per_face_pieces for p in pieces]
    all_trim_pieces.extend(all_fill_pieces)

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

        if not hasattr(obj, 'EqualizeCorners'):
            obj.addProperty(
                "App::PropertyBool", "EqualizeCorners", grp,
                "Clip trim at building corners so both boards show equal visible width")

        if not hasattr(obj, 'ConvexCornerFill'):
            obj.addProperty(
                "App::PropertyBool", "ConvexCornerFill", grp,
                "Fill gap at exterior building corners (where two trimmed walls meet)")

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
        obj.EqualizeCorners = params.get('equalize_corners', True)
        obj.ConvexCornerFill = params.get('convex_corner_fill', True)
        obj.GeneratorVersion = VERSION

    # -- execute (called on recompute) ----------------------------------------

    def execute(self, obj):
        if not obj.Sources:
            return

        # Resolve LinkSubList → (face, parent_shape, parent_obj) tuples
        face_entries = []
        for link_obj, sub_names in obj.Sources:
            parent_shape = link_obj.Shape
            for sub_name in sub_names:
                face = link_obj.Shape.getElement(sub_name)
                face_entries.append((face, parent_shape, link_obj))

        if not face_entries:
            return

        params = {
            'trim_width':    float(obj.TrimWidth),
            'trim_height':   float(obj.TrimHeight),
            'trim_style':    str(obj.TrimStyle),
            'bevel_size':    float(obj.BevelSize),
            'skip_bottom':   bool(obj.SkipBottom),
            'perimeter_only': bool(obj.PerimeterOnly),
            'flip':               bool(obj.Flip),
            'only_edge':          int(obj.OnlyEdge),
            'equalize_corners':   bool(obj.EqualizeCorners),
            'convex_corner_fill': bool(obj.ConvexCornerFill),
            'edge_types':         ['vertical'],
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
