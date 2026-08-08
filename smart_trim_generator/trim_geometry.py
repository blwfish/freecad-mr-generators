"""
Trim Geometry Library
====================

Pure Python geometry library for architectural trim generation.
Provides corner detection, classification, and trim piece geometry generation.

This library works with FreeCAD Part::TopoShape objects but contains no FreeCAD
dependencies in the core geometry functions - similar to clapboard_geometry.py.

Author: Brian White
Version: 1.4.1
License: MIT
"""

from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
from enum import Enum
import math


class CornerType(Enum):
    """Types of corners detected in face boundaries."""
    EXTERNAL = "external"  # Convex corner (< 180°)
    INTERNAL = "internal"  # Concave corner (> 180°)
    STRAIGHT = "straight"  # Collinear edges (~180°)


@dataclass
class Corner:
    """Represents a detected corner in a face boundary."""
    position: Tuple[float, float, float]  # 3D coordinates (x, y, z)
    corner_type: CornerType
    angle: float  # Interior angle in degrees
    edge_before: object  # FreeCAD Edge leading into corner
    edge_after: object   # FreeCAD Edge leading out of corner
    
    def miter_angle(self) -> float:
        """Calculate the miter cut angle for this corner."""
        # For a corner with interior angle α, each miter piece is cut at α/2
        return self.angle / 2.0


def get_face_boundary_edges(face) -> List:
    """
    Extract ordered boundary edges from a face.
    
    Args:
        face: FreeCAD Face object
        
    Returns:
        List of Edge objects forming the face boundary, in order
    """
    # Get the outer wire of the face
    outer_wire = face.OuterWire
    
    if not outer_wire.isClosed():
        raise ValueError("Face outer wire is not closed - cannot detect corners")
    
    # Return ordered edges
    return outer_wire.OrderedEdges


def get_edge_vector(edge, at_end: bool = False):
    """
    Get the direction vector of an edge at its start or end.
    
    Args:
        edge: FreeCAD Edge object
        at_end: If True, get vector at end; if False, get vector at start
        
    Returns:
        FreeCAD.Vector representing edge direction
    """
    if at_end:
        # Get tangent at the end of the edge
        return edge.tangentAt(edge.LastParameter)
    else:
        # Get tangent at the start of the edge
        return edge.tangentAt(edge.FirstParameter)


def calculate_interior_angle(edge_before, edge_after, face=None) -> float:
    """
    Calculate the interior angle between two consecutive edges.

    The interior angle is the angle measured on the "inside" of the polygon.

    Key insight: getAngle() gives the turn angle (0-180°).
    - For external corners (convex): interior_angle = 180° - turn_angle
    - For internal corners (concave): interior_angle = 180° + turn_angle

    Args:
        edge_before: Edge leading into the corner
        edge_after: Edge leading out of the corner
        face: Optional face object — used to get the face normal for
              correct convex/concave classification on any plane

    Returns:
        Interior angle in degrees (0-360)
    """
    # Get direction vectors
    vec_in = get_edge_vector(edge_before, at_end=True)
    vec_out = get_edge_vector(edge_after, at_end=False)

    # getAngle() returns the turn angle (always 0-180°)
    turn_angle_rad = vec_in.getAngle(vec_out)
    turn_angle_deg = math.degrees(turn_angle_rad)

    # Use cross product to determine turn direction.
    # The sign of cross · face_normal tells us the turn direction
    # relative to the face orientation (works for any plane).
    cross = vec_in.cross(vec_out)

    # Get face normal for the sign check
    if face is not None:
        face_normal = _get_face_normal(face)
        sign = cross.dot(face_normal)
    else:
        # Fallback: assume XY plane
        sign = cross.z

    if sign > 0:
        # External corner (convex): interior = 180 - turn
        return 180.0 - turn_angle_deg
    else:
        # Internal corner (concave): interior = 180 + turn
        return 180.0 + turn_angle_deg


def classify_corner(angle: float, tolerance: float = 5.0) -> CornerType:
    """
    Classify a corner based on its interior angle.
    
    Args:
        angle: Interior angle in degrees
        tolerance: Degrees of tolerance for "straight" classification
        
    Returns:
        CornerType enum value
    """
    if abs(angle - 180.0) < tolerance:
        return CornerType.STRAIGHT
    elif angle < 180.0:
        return CornerType.EXTERNAL
    else:
        return CornerType.INTERNAL


def detect_corners(face, angle_tolerance: float = 5.0) -> List[Corner]:
    """
    Detect all corners in a face boundary and classify them.
    
    Args:
        face: FreeCAD Face object
        angle_tolerance: Tolerance in degrees for classifying straight corners
        
    Returns:
        List of Corner objects, ordered around the face boundary
    """
    edges = get_face_boundary_edges(face)
    corners = []
    
    num_edges = len(edges)
    
    for i in range(num_edges):
        edge_before = edges[i]
        edge_after = edges[(i + 1) % num_edges]  # Wrap around to first edge
        
        # Get the vertex position where these edges meet
        # The end vertex of edge_before should match start vertex of edge_after
        vertex_pos = edge_before.valueAt(edge_before.LastParameter)
        position = (vertex_pos.x, vertex_pos.y, vertex_pos.z)
        
        # Calculate interior angle
        angle = calculate_interior_angle(edge_before, edge_after, face)
        
        # Classify the corner
        corner_type = classify_corner(angle, angle_tolerance)
        
        # Create Corner object
        corner = Corner(
            position=position,
            corner_type=corner_type,
            angle=angle,
            edge_before=edge_before,
            edge_after=edge_after
        )
        
        corners.append(corner)
    
    return corners


def filter_corners_for_trim(corners: List[Corner], 
                            include_straight: bool = False) -> List[Corner]:
    """
    Filter corners to only those that need trim pieces.
    
    Args:
        corners: List of all detected corners
        include_straight: If True, include straight corners in results
        
    Returns:
        List of corners that need trim (typically external and internal only)
    """
    if include_straight:
        return corners
    else:
        return [c for c in corners if c.corner_type != CornerType.STRAIGHT]


def analyze_face_for_trim(face, angle_tolerance: float = 5.0) -> Dict:
    """
    Complete analysis of a face for trim placement.
    
    Args:
        face: FreeCAD Face object
        angle_tolerance: Tolerance for straight corner detection
        
    Returns:
        Dictionary with analysis results:
        - 'all_corners': All detected corners
        - 'external_corners': External corners only
        - 'internal_corners': Internal corners only
        - 'trim_corners': Corners needing trim (external + internal)
        - 'straight_edges': Edges between straight corners
    """
    corners = detect_corners(face, angle_tolerance)
    
    external = [c for c in corners if c.corner_type == CornerType.EXTERNAL]
    internal = [c for c in corners if c.corner_type == CornerType.INTERNAL]
    trim_corners = external + internal
    
    return {
        'all_corners': corners,
        'external_corners': external,
        'internal_corners': internal,
        'trim_corners': trim_corners,
        'num_corners': len(corners),
        'num_external': len(external),
        'num_internal': len(internal),
    }


# ============================================================================
# TRIM PROFILE GENERATION
# ============================================================================

def create_simple_rectangular_profile(width: float, height: float):
    """
    Create a simple rectangular trim profile.
    
    Args:
        width: Profile width (perpendicular to wall)
        height: Profile height (parallel to wall)
        
    Returns:
        FreeCAD Wire representing the profile cross-section
    """
    import Part
    import FreeCAD as App
    
    # Simple rectangle profile
    v1 = App.Vector(0, 0, 0)
    v2 = App.Vector(width, 0, 0)
    v3 = App.Vector(width, height, 0)
    v4 = App.Vector(0, height, 0)
    
    edges = [
        Part.LineSegment(v1, v2).toShape(),
        Part.LineSegment(v2, v3).toShape(),
        Part.LineSegment(v3, v4).toShape(),
        Part.LineSegment(v4, v1).toShape(),
    ]
    
    return Part.Wire(edges)


def create_beveled_profile(width: float, height: float, bevel: float):
    """
    Create a beveled trim profile (chamfered edge).
    
    Args:
        width: Profile width
        height: Profile height  
        bevel: Bevel distance (cut at 45°)
        
    Returns:
        FreeCAD Wire representing the beveled profile

    Raises:
        ValueError: if bevel is not strictly between 0 and both width and
            height. v3=(width, bevel) must sit strictly below v4=(width,
            height) and v2=(width-bevel, 0) strictly right of v1=(0, 0)
            for the intended winding order; bevel >= height or bevel >=
            width silently produces a self-intersecting/inverted polygon
            instead (full-review finding #26, 2026-08-08).
    """
    if not (0 < bevel < width and 0 < bevel < height):
        raise ValueError(
            f"bevel ({bevel}) must be strictly between 0 and both "
            f"width ({width}) and height ({height})")

    import Part
    import FreeCAD as App

    # Beveled rectangle with 45° chamfer on outer edge
    v1 = App.Vector(0, 0, 0)
    v2 = App.Vector(width - bevel, 0, 0)
    v3 = App.Vector(width, bevel, 0)
    v4 = App.Vector(width, height, 0)
    v5 = App.Vector(0, height, 0)
    
    edges = [
        Part.LineSegment(v1, v2).toShape(),
        Part.LineSegment(v2, v3).toShape(),
        Part.LineSegment(v3, v4).toShape(),
        Part.LineSegment(v4, v5).toShape(),
        Part.LineSegment(v5, v1).toShape(),
    ]
    
    return Part.Wire(edges)


# ============================================================================
# TRIM GENERATION
# ============================================================================

def create_straight_trim_segment(edge, profile_wire, face=None,
                                 face_normal_override=None,
                                 name: str = "TrimSegment"):
    """
    Create a straight trim piece by sweeping a profile along an edge.

    The profile is positioned and oriented relative to the edge, with the
    trim extending perpendicular to the face.

    Args:
        edge: FreeCAD Edge to sweep along
        profile_wire: Profile cross-section (Wire)
        face: Optional Face for orientation (needed for proper positioning)
        face_normal_override: If provided, use this normal instead of computing
                              from the face.  Used to ensure trim extends outward.
        name: Name for the resulting shape

    Returns:
        FreeCAD solid object (swept profile)
    """
    import Part
    import FreeCAD as App

    # Create path from edge
    path = Part.Wire([edge])

    # Get edge tangent at start
    tangent = edge.tangentAt(edge.FirstParameter)
    tangent.normalize()

    # Get face normal — use override if provided, otherwise compute from face
    if face_normal_override is not None:
        normal = App.Vector(face_normal_override)
        normal.normalize()
    elif face:
        # Get face normal at a point on the edge
        edge_start = edge.valueAt(edge.FirstParameter)
        u, v = face.Surface.parameter(edge_start)
        normal = face.normalAt(u, v)
        normal.normalize()
    else:
        normal = App.Vector(0, 0, 1)
    
    # Calculate binormal (perpendicular to both tangent and normal)
    # This is the direction the trim extends FROM the wall
    binormal = tangent.cross(normal)
    binormal.normalize()
    
    # Position profile at edge start, extending outward from the face.
    # Profile is defined in the XY plane: X = width, Y = height.
    # Map:  Profile X → normal (outward from wall = trim_width)
    #        Profile Y → −binormal (inward along wall surface = trim_height)
    #   Negating binormal makes the trim sit ON the wall face with
    #   the edge as its outer boundary, rather than hanging past the edge.
    # Then translate to edge start.
    #
    # NOTE: tangent × normal can produce a left-handed system (det = −1).
    # FreeCAD Placement stores rotation as a quaternion, which silently
    # mangles det = −1 matrices.  Use transformShape() instead — it
    # handles arbitrary affine transforms correctly.
    from FreeCAD import Matrix

    base = edge.valueAt(edge.FirstParameter)
    m = Matrix()
    m.A11, m.A21, m.A31 = normal.x, normal.y, normal.z
    m.A12, m.A22, m.A32 = -binormal.x, -binormal.y, -binormal.z
    m.A13, m.A23, m.A33 = tangent.x, tangent.y, tangent.z
    m.A14, m.A24, m.A34, m.A44 = base.x, base.y, base.z, 1

    oriented_profile = profile_wire.copy()
    oriented_profile = oriented_profile.transformShape(m)
    
    # Sweep the oriented profile along the path.
    # path.makePipeShell([section], makeSolid, isFrenet)
    #   path  = the spine wire (the edge to sweep along)
    #   section = cross-section profile positioned at the path start
    try:
        sweep = path.makePipeShell([oriented_profile], True, True)
        return sweep
    except Exception as e:
        # Fallback: simpler sweep if the above fails
        print(f"Warning: Advanced sweep failed ({e}), using simple sweep")
        sweep = path.makePipeShell([oriented_profile], True, False)
        return sweep


# ============================================================================
# MITER CUT GEOMETRY
# ============================================================================

def compute_miter_bisector(corner: Corner):
    """
    Compute the bisector direction for a miter cut at a corner.

    The bisector lies in the face plane and bisects the angle between
    the incoming and outgoing edge tangents.  For a 90° external corner
    the bisector is at 45° to each edge.

    Args:
        corner: Corner object with edge_before and edge_after

    Returns:
        FreeCAD.Vector — normalized bisector direction
    """
    import FreeCAD as App

    # Tangent arriving at corner (points toward corner vertex)
    t_in = get_edge_vector(corner.edge_before, at_end=True)
    t_in.normalize()

    # Tangent departing corner (points away from corner vertex)
    t_out = get_edge_vector(corner.edge_after, at_end=False)
    t_out.normalize()

    # The miter bisector is the vector sum of the two tangents.
    # t_in points *into* the corner, t_out points *out* — their sum
    # bisects the exterior angle, which is exactly the miter line.
    bisector = t_in + t_out

    if bisector.Length < 1e-6:
        # Edges are anti-parallel (180° straight corner).
        # Pick an arbitrary perpendicular in the XY plane.
        bisector = App.Vector(-t_in.y, t_in.x, t_in.z)

    bisector.normalize()
    return bisector


def _get_face_normal(face):
    """Return the outward normal of a face at its centre of mass."""
    import FreeCAD as App

    uv = face.Surface.parameter(face.CenterOfMass)
    normal = face.normalAt(uv[0], uv[1])
    normal.normalize()
    return normal


def _ensure_outward_normal(face, face_normal, outward_hint=None):
    """
    Ensure the face normal points outward (away from the building interior).

    If *outward_hint* is provided (e.g. face_center − solid_center), the
    normal is flipped when it disagrees with the hint.  Otherwise the normal
    is returned unchanged.

    Args:
        face:          FreeCAD Face
        face_normal:   FreeCAD.Vector — raw face normal
        outward_hint:  FreeCAD.Vector — direction known to be "outward",
                       typically ``face.CenterOfMass - solid.CenterOfMass``

    Returns:
        FreeCAD.Vector — corrected normal
    """
    import FreeCAD as App

    if outward_hint is not None and outward_hint.Length > 1e-6:
        if face_normal.dot(outward_hint) < 0:
            return face_normal * -1.0
    return face_normal


def classify_edge_direction(edge, vertical_axis: str = 'z',
                            tolerance_deg: float = 5.0) -> str:
    """
    Classify an edge as 'vertical', 'horizontal', or 'gable'.

    Extracts the edge's tangent direction and delegates the actual
    classification to smart_trim_geometry.classify_edge(). Previously this
    function reimplemented the same angle math independently (a folded
    abs(tangent-component)/acos formula, mathematically equivalent to but
    separately maintained from classify_edge()'s explicit dual-range
    check) -- two sources of truth for one semantic distinction, with no
    test able to pin their equivalence since this FreeCAD-dependent copy
    can't run under plain pytest (see CLAUDE.md's Syntactic-Semantic Seam
    Rule; full-review finding #09, 2026-08-08). Now there is exactly one
    classification implementation.

    Args:
        edge:          FreeCAD Edge
        vertical_axis: axis that represents "up" ('x', 'y', or 'z')
        tolerance_deg: angle tolerance in degrees

    Returns:
        'vertical', 'horizontal', or 'gable'
    """
    from smart_trim_geometry import classify_edge as _classify_edge_tuple

    tangent = edge.tangentAt(edge.FirstParameter)
    tangent.normalize()
    return _classify_edge_tuple(
        (tangent.x, tangent.y, tangent.z), vertical_axis, tolerance_deg)


def _is_perimeter_edge(edge, face_bbox, vertical_axis: str = 'z',
                       tolerance: float = 0.5) -> bool:
    """
    Test whether an edge sits on the bounding-box boundary of the face.

    Both endpoints must touch the face bbox boundary on at least one axis
    that has meaningful extent (ignoring degenerate/flat axes).  This
    correctly excludes door/window-notch edges that only touch the floor
    at one end.

    Args:
        edge:          FreeCAD Edge
        face_bbox:     FreeCAD BoundBox of the face
        vertical_axis: 'z', 'y', or 'x'
        tolerance:     positional tolerance in mm

    Returns:
        True if BOTH endpoints touch the face bbox boundary
    """
    p1 = edge.valueAt(edge.FirstParameter)
    p2 = edge.valueAt(edge.LastParameter)

    bb = face_bbox

    for p in (p1, p2):
        on_boundary = False
        # Only check axes where the face has meaningful extent
        if bb.XLength > tolerance:
            if abs(p.x - bb.XMin) < tolerance or abs(p.x - bb.XMax) < tolerance:
                on_boundary = True
        if bb.YLength > tolerance:
            if abs(p.y - bb.YMin) < tolerance or abs(p.y - bb.YMax) < tolerance:
                on_boundary = True
        if bb.ZLength > tolerance:
            if abs(p.z - bb.ZMin) < tolerance or abs(p.z - bb.ZMax) < tolerance:
                on_boundary = True
        if not on_boundary:
            return False

    return True


def apply_miter_cut_at_corner(solid, corner: Corner, face_normal,
                              keep_direction, cut_size: float = 200.0):
    """
    Boolean-cut a trim solid along the miter bisector plane at a corner.

    A large planar face is constructed through the corner vertex with its
    normal equal to the miter bisector.  A half-space on the *keep* side
    is intersected with the solid so only the wanted half remains.

    Args:
        solid:          FreeCAD solid to cut
        corner:         Corner object (provides position and edges)
        face_normal:    FreeCAD.Vector — wall face outward normal
        keep_direction: FreeCAD.Vector — direction from the corner toward
                        the part of the solid we want to keep
        cut_size:       half-extent of the cutting plane (mm)

    Returns:
        Cut FreeCAD solid, or original solid on failure
    """
    import Part
    import FreeCAD as App

    corner_pos = App.Vector(*corner.position)
    bisector = compute_miter_bisector(corner)

    # Build two spanning directions for the cutting plane.
    # The plane normal is the bisector; it extends in:
    #   • face_normal  (through the wall thickness)
    #   • bisector × face_normal  (along the wall, ⊥ bisector)
    up = App.Vector(face_normal)
    up.normalize()

    across = bisector.cross(up)
    if across.Length < 1e-6:
        # bisector ∥ face_normal — shouldn't happen for in-plane edges
        across = App.Vector(-bisector.y, bisector.x, 0)
    across.normalize()

    h = cut_size
    p1 = corner_pos + up * h + across * h
    p2 = corner_pos - up * h + across * h
    p3 = corner_pos - up * h - across * h
    p4 = corner_pos + up * h - across * h

    cut_wire = Part.makePolygon([p1, p2, p3, p4, p1])
    cut_face = Part.Face(cut_wire)

    # keep_point tells makeHalfSpace which side to materialise. Vector.
    # normalize() raises Base.FreeCADError on a zero-length vector (it does
    # NOT silently no-op) -- discovered 2026-08-08 writing this function's
    # first real test coverage (full-review finding #27). Moved inside the
    # try/except below, alongside every other failure this function is
    # documented to fall back to the original solid for.
    try:
        kd = App.Vector(keep_direction)
        kd.normalize()
        keep_point = corner_pos + kd * 1.0

        half_space = cut_face.makeHalfSpace(keep_point)
        result = solid.common(half_space)
        # Guard against degenerate result
        if result.isNull() or not result.Solids:
            return solid
        return result
    except Exception:
        return solid


# ============================================================================
# INTERNAL CORNER FILL
# ============================================================================

def create_internal_corner_fill(corner: Corner, face_normal,
                                profile_width: float, profile_height: float):
    """
    Create a wedge-shaped fill piece for an internal (concave) corner.

    At internal corners, even after miter cuts the two trim segments may
    leave a small triangular gap where they don't overlap.  This function
    generates a prism that fills that gap.

    The fill is a triangular prism whose cross-section (in the face plane)
    is the triangle formed by:
      • the corner vertex
      • the vertex offset along -binormal_before by profile_width
      • the vertex offset along -binormal_after  by profile_width
    extruded along the face normal by profile_height.

    Args:
        corner:         Corner with INTERNAL type
        face_normal:    FreeCAD.Vector — wall face outward normal
        profile_width:  trim width (perpendicular to wall edge)
        profile_height: trim height (along face normal)

    Returns:
        FreeCAD solid (triangular prism), or None if not needed / on failure
    """
    import Part
    import FreeCAD as App

    if corner.corner_type != CornerType.INTERNAL:
        return None

    corner_pos = App.Vector(*corner.position)

    # Tangent directions at the corner
    t_in = get_edge_vector(corner.edge_before, at_end=True)
    t_in.normalize()
    t_out = get_edge_vector(corner.edge_after, at_end=False)
    t_out.normalize()

    fn = App.Vector(face_normal)
    fn.normalize()

    # Binormals: direction trim extends from each edge (tangent × face_normal)
    bin_before = t_in.cross(fn)
    bin_before.normalize()
    bin_after = t_out.cross(fn)
    bin_after.normalize()

    # The fill triangle vertices (in face plane)
    p0 = corner_pos
    p1 = corner_pos + bin_before * profile_width
    p2 = corner_pos + bin_after * profile_width

    # If the three points are nearly collinear, no fill is needed
    tri_cross = (p1 - p0).cross(p2 - p0)
    if tri_cross.Length < 1e-6:
        return None

    try:
        tri_wire = Part.makePolygon([p0, p1, p2, p0])
        tri_face = Part.Face(tri_wire)
        fill = tri_face.extrude(fn * profile_height)
        return fill
    except Exception:
        return None


# ============================================================================
# COMPLETE TRIM GENERATION
# ============================================================================

def generate_trim_for_face(face, profile_wire,
                          include_corners: bool = True,
                          corner_treatment: str = "mitered",
                          outward_hint=None,
                          skip_bottom: bool = False,
                          perimeter_only: bool = False,
                          edge_types: Optional[List[str]] = None,
                          vertical_axis: str = 'z') -> List:
    """
    Generate complete trim for a face boundary.

    Each boundary edge is swept with the profile to produce a straight
    trim segment.  When ``corner_treatment="mitered"`` (the default),
    every segment is boolean-cut at both ends along the miter bisector
    so that adjacent pieces meet with a clean 45° (or other angle) joint.

    Args:
        face:            FreeCAD Face object
        profile_wire:    Trim profile cross-section
        include_corners: Whether to generate corner fill pieces at internal corners
        corner_treatment: "mitered" or "straight" corners
        outward_hint:    FreeCAD.Vector pointing outward from the building
                         (e.g. face.CenterOfMass − solid.CenterOfMass).
                         Used to ensure trim extends outward from the wall.
        skip_bottom:     Skip horizontal edges at the face's minimum height
        perimeter_only:  Only trim edges on the face bounding-box boundary
                         (skips internal notch/construction-joint edges)
        edge_types:      List of edge types to include: 'vertical',
                         'horizontal', 'gable'.  None means include all.
        vertical_axis:   Axis representing "up" ('x', 'y', or 'z')

    Returns:
        List of trim piece solids
    """
    import Part
    import math

    # Analyse the face
    analysis = analyze_face_for_trim(face)
    corners = analysis['all_corners']
    edges = get_face_boundary_edges(face)

    # Determine which edges to trim
    face_bbox = face.BoundBox
    edge_mask = []  # True = trim this edge
    for edge in edges:
        include = True

        # Edge type filter
        if edge_types is not None:
            etype = classify_edge_direction(edge, vertical_axis)
            if etype not in edge_types:
                include = False

        # Skip bottom edges (both endpoints at minimum height)
        if include and skip_bottom:
            p1 = edge.valueAt(edge.FirstParameter)
            p2 = edge.valueAt(edge.LastParameter)
            if vertical_axis == 'z':
                at_bottom = (abs(p1.z - face_bbox.ZMin) < 0.5 and
                             abs(p2.z - face_bbox.ZMin) < 0.5)
            elif vertical_axis == 'y':
                at_bottom = (abs(p1.y - face_bbox.YMin) < 0.5 and
                             abs(p2.y - face_bbox.YMin) < 0.5)
            else:
                at_bottom = (abs(p1.x - face_bbox.XMin) < 0.5 and
                             abs(p2.x - face_bbox.XMin) < 0.5)
            if at_bottom:
                include = False

        # Perimeter-only filter
        if include and perimeter_only:
            if not _is_perimeter_edge(edge, face_bbox, vertical_axis):
                include = False

        edge_mask.append(include)

    # Correct face normal direction (default for all edges)
    face_normal = _get_face_normal(face)
    face_normal = _ensure_outward_normal(face, face_normal, outward_hint)

    # Sweep each included edge to get raw (uncut) trim solids.
    # makePipeShell may return a Shell; convert to Solid for boolean ops.
    raw_solids = []
    included_indices = []
    for i, edge in enumerate(edges):
        if not edge_mask[i]:
            raw_solids.append(None)
            continue
        segment = create_straight_trim_segment(edge, profile_wire, face,
                                               face_normal_override=face_normal)
        if segment.ShapeType == 'Shell':
            segment = Part.Solid(segment)
        elif segment.ShapeType == 'Compound' and segment.Shells:
            segment = Part.Solid(segment.Shells[0])
        raw_solids.append(segment)
        included_indices.append(i)

    if corner_treatment != "mitered":
        return [s for s in raw_solids if s is not None]

    n = len(edges)
    mitered_solids = []

    for i in included_indices:
        solid = raw_solids[i]

        # --- Start of this edge: corner between edges[i-1] and edges[i] ---
        # Only miter if the OTHER edge at this corner is also included.
        prev_idx = (i - 1) % n
        start_corner = corners[prev_idx]
        if (start_corner.corner_type != CornerType.STRAIGHT
                and edge_mask[prev_idx]):
            start_tangent = get_edge_vector(edges[i], at_end=False)
            solid = apply_miter_cut_at_corner(
                solid, start_corner, face_normal, start_tangent)

        # --- End of this edge: corner between edges[i] and edges[i+1] ---
        next_idx = (i + 1) % n
        end_corner = corners[i]
        if (end_corner.corner_type != CornerType.STRAIGHT
                and edge_mask[next_idx]):
            end_tangent = get_edge_vector(edges[i], at_end=True)
            keep_dir = end_tangent * -1.0
            solid = apply_miter_cut_at_corner(
                solid, end_corner, face_normal, keep_dir)

        mitered_solids.append(solid)

    # Fill gaps at internal (concave) corners between included edges
    if include_corners:
        bb = profile_wire.BoundBox
        profile_width = bb.XLength
        profile_height = bb.YLength

        for idx, corner in enumerate(corners):
            if corner.corner_type != CornerType.INTERNAL:
                continue
            # Only fill if both adjacent edges were included
            edge_before_idx = idx
            edge_after_idx = (idx + 1) % n
            if edge_mask[edge_before_idx] and edge_mask[edge_after_idx]:
                fill = create_internal_corner_fill(
                    corner, face_normal, profile_width, profile_height)
                if fill is not None:
                    mitered_solids.append(fill)

    return mitered_solids


# Example usage when called from FreeCAD macro:
"""
import FreeCAD as App
import trim_corner_detection as tcd

# Get selected face
sel = Gui.Selection.getSelectionEx()
if sel and sel[0].HasSubObjects:
    face = sel[0].SubObjects[0]
    
    # Analyze the face
    analysis = tcd.analyze_face_for_trim(face)
    
    print(f"Found {analysis['num_corners']} corners:")
    print(f"  - {analysis['num_external']} external corners")
    print(f"  - {analysis['num_internal']} internal corners")
    
    # Process each corner that needs trim
    for corner in analysis['trim_corners']:
        print(f"Corner at {corner.position}:")
        print(f"  Type: {corner.corner_type.value}")
        print(f"  Angle: {corner.angle:.1f}°")
        print(f"  Miter cut: {corner.miter_angle():.1f}°")
"""
