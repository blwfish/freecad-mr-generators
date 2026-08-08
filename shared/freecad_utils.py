"""
freecad_utils.py — Shared FreeCAD utility library for generators

Installed to: Macro/_lib/freecad_utils.py
Imported by:  brick_generator_macro, radial_brick_generator_macro,
              clapboard_generator, board_batten_generator, bead_board_generator,
              shingle_generator, smart_trim_generator, station_sign_generator,
              roof_seam_generator, slate_seam_generator, slate_generator,
              snow_guard_generator, standing_seam_generator,
              standing_seam_snow_guard_generator, label_generator

Version: 1.5.0
  1.5.0: Add resolve_sources_faces() -- consolidates the obj.Sources ->
         (face, link_obj, sub_name) resolution loop that was independently
         copy-pasted into 8 proxies (5 of which had it wrong: getElement()
         outside try/except, or -- smart_trim_proxy.py -- no guard at all).
         Add resolve_font_path()/find_first_existing_path() -- consolidates
         the font-path resolution duplicated in label_proxy.py and
         station_sign_proxy.py, which both silently collapsed "FontPath
         empty" and "FontPath doesn't exist" into the same behavior with no
         signal to the user which case occurred.
  1.4.1: _closest_candidate's scoring formula extracted to
         roof_geometry.score_face_match/best_matching_candidate so it's
         pytest-testable without FreeCAD; this file now just extracts
         plain distance/normal data from Part.Face and calls it.
  1.4.0: Add resolve_shared_edge()/resolve_base_face() — roof-seam face
         unwrapping consolidated from roof_seam_proxy.py and a vendored
         copy in slate_seam_proxy.py, extended to recognize the modern
         Sources PropertyLinkSubList convention (brick_proxy, quoin_proxy,
         shingle_proxy, slate_proxy) alongside the legacy BaseObject/
         ShingledRoof_/ShingleSkin_ convention. Neither original recognized
         Sources, so selecting faces from any current tiled/shingled output
         silently used tiny tile/shingle fragments instead of the real
         roof face.
  1.3.0: Add precondition/postcondition assertions throughout (GEN_NO_ASSERT=1 to disable).
  1.2.0: Add find_spreadsheet() — multi-name spreadsheet lookup with App::Link support.
  1.1.0: Add commit_result() — undoable output object creation with metadata.
  1.0.2: Initial shared library (global placement helpers).
"""

import os

__version__ = "1.5.0"

# ---------------------------------------------------------------------------
# Assertion toggle
# ---------------------------------------------------------------------------
# Set environment variable GEN_NO_ASSERT=1 to disable all assertions (e.g. in
# a hot production loop where you have already validated inputs externally).
# Assertions are enabled by default during development.
_ASSERTIONS_ENABLED = os.environ.get("GEN_NO_ASSERT") != "1"


def _assert(condition, message):
    """Raise AssertionError with *message* if *condition* is False and assertions are enabled."""
    if _ASSERTIONS_ENABLED and not condition:
        raise AssertionError(message)


# ---------------------------------------------------------------------------
# Global placement helpers
# ---------------------------------------------------------------------------

def get_global_face(obj, face_index):
    """
    Return a face from *obj* in global (world) coordinates.

    When an object lives inside a Part container with a non-identity
    Placement, ``obj.Shape.Faces[i]`` gives local coordinates only.
    This function applies the global placement transform so the returned
    face is correctly positioned in world space.

    Parameters
    ----------
    obj : FreeCAD document object
        Must have a ``Shape`` attribute.
    face_index : int
        Zero-based index into ``obj.Shape.Faces``.

    Returns
    -------
    Part.Face
        Face geometry in global coordinates.

    Raises
    ------
    IndexError
        If *face_index* is out of range for this object's faces.

    Preconditions:
        - obj: must not be None; must have a Shape attribute with at least
          one face
        - face_index: must be a non-negative integer within range of
          obj.Shape.Faces

    Postconditions:
        - returned object is a Part.Face (ShapeType == "Face")
        - returned face has non-zero area (degenerate faces indicate a
          geometry problem upstream)
    """
    # --- Preconditions ---
    _assert(obj is not None,
            f"get_global_face: obj must not be None")
    _assert(hasattr(obj, 'Shape'),
            f"get_global_face: obj must have a Shape attribute, got type={type(obj).__name__!r}")
    _assert(isinstance(face_index, int),
            f"get_global_face: face_index must be int, got {type(face_index).__name__!r} value={face_index!r}")
    _assert(face_index >= 0,
            f"get_global_face: face_index must be >= 0, got {face_index}")
    _assert(len(obj.Shape.Faces) > 0,
            f"get_global_face: obj.Shape has no faces (ShapeType={obj.Shape.ShapeType!r})")
    _assert(face_index < len(obj.Shape.Faces),
            f"get_global_face: face_index={face_index} out of range for obj with "
            f"{len(obj.Shape.Faces)} face(s) (Label={getattr(obj, 'Label', repr(obj))!r})")

    face = obj.Shape.Faces[face_index]
    try:
        placement = obj.getGlobalPlacement()
        if not placement.isIdentity():
            # transformShape() applies the rigid-body transform while preserving
            # analytical surface types (Cone, Cylinder, Plane, etc.).
            # transformGeometry() must NOT be used here — it converts all surfaces
            # to BSpline approximations, breaking downstream surface-type checks.
            face = face.transformShape(placement.toMatrix())
    except AttributeError:
        pass  # Object doesn't support getGlobalPlacement (e.g. Sketch)

    # --- Postconditions ---
    _assert(face is not None,
            f"get_global_face: returned face is None (obj={getattr(obj, 'Label', repr(obj))!r}, "
            f"face_index={face_index})")
    _assert(face.ShapeType == "Face",
            f"get_global_face: expected ShapeType='Face', got {face.ShapeType!r} "
            f"(obj={getattr(obj, 'Label', repr(obj))!r}, face_index={face_index})")
    _assert(face.Area > 0,
            f"get_global_face: returned face has zero or negative area={face.Area} "
            f"(obj={getattr(obj, 'Label', repr(obj))!r}, face_index={face_index}); "
            f"degenerate geometry upstream")

    return face


def get_global_placement_matrix(obj):
    """
    Return the global placement matrix for *obj*, or None if unavailable.

    Useful when you want to log or reuse the matrix without calling
    ``getGlobalPlacement()`` twice.

    Parameters
    ----------
    obj : FreeCAD document object

    Returns
    -------
    FreeCAD.Matrix or None
        None if the object doesn't support ``getGlobalPlacement()``.

    Preconditions:
        - obj: must not be None

    Postconditions:
        - returned value is either None or a FreeCAD.Matrix with finite
          elements (no NaN/Inf from a degenerate placement)
    """
    # --- Preconditions ---
    _assert(obj is not None,
            f"get_global_placement_matrix: obj must not be None")

    try:
        matrix = obj.getGlobalPlacement().toMatrix()
    except AttributeError:
        return None

    # --- Postconditions ---
    if matrix is not None and _ASSERTIONS_ENABLED:
        # A valid rigid-body placement matrix should have finite elements.
        # FreeCAD.Matrix exposes elements as A11..A44.
        matrix_elements = [
            matrix.A11, matrix.A12, matrix.A13, matrix.A14,
            matrix.A21, matrix.A22, matrix.A23, matrix.A24,
            matrix.A31, matrix.A32, matrix.A33, matrix.A34,
            matrix.A41, matrix.A42, matrix.A43, matrix.A44,
        ]
        import math
        for i, elem in enumerate(matrix_elements):
            _assert(math.isfinite(elem),
                    f"get_global_placement_matrix: matrix element [{i}] is not finite "
                    f"(value={elem}) for obj={getattr(obj, 'Label', repr(obj))!r}; "
                    f"degenerate placement")

    return matrix


def object_has_global_offset(obj):
    """
    Return True if *obj* is inside a Part container with a non-identity
    placement (i.e. its local and global coordinate frames differ).

    Parameters
    ----------
    obj : FreeCAD document object

    Returns
    -------
    bool

    Preconditions:
        - obj: must not be None

    Postconditions:
        - return value is bool (True or False, never None or other type)
    """
    # --- Preconditions ---
    _assert(obj is not None,
            f"object_has_global_offset: obj must not be None")

    try:
        result = not obj.getGlobalPlacement().isIdentity()
    except AttributeError:
        result = False

    # --- Postconditions ---
    _assert(isinstance(result, bool),
            f"object_has_global_offset: expected bool result, got {type(result).__name__!r} "
            f"value={result!r}")

    return result


def log_global_placement(obj, label=None):
    """
    Print a one-line diagnostic if *obj* has a non-identity global
    placement.  Silent if placement is identity.

    Parameters
    ----------
    obj : FreeCAD document object
    label : str, optional
        Prefix shown in the message (defaults to obj.Label).

    Preconditions:
        - obj: must not be None
        - label: if provided, must be a str (not a number or other type)

    Postconditions:
        - (no return value; side-effect is a print to stdout if obj has
          a non-identity global placement)
    """
    # --- Preconditions ---
    _assert(obj is not None,
            f"log_global_placement: obj must not be None")
    _assert(label is None or isinstance(label, str),
            f"log_global_placement: label must be str or None, got "
            f"{type(label).__name__!r} value={label!r}")

    name = label or getattr(obj, 'Label', repr(obj))
    try:
        p = obj.getGlobalPlacement()
        if not p.isIdentity():
            pos = p.Base
            print(f"  NOTE: {name} is in a Part container — "
                  f"global placement offset ({pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f}) "
                  f"will be applied to face geometry")
    except AttributeError:
        pass


# ---------------------------------------------------------------------------
# Roof-seam face resolution
# ---------------------------------------------------------------------------
# Extracted 2026-08-08 from roof_seam_proxy.py, where it originated, and a
# vendored copy in slate_seam_proxy.py (deliberately duplicated there rather
# than refactoring an 854-line, zero-test-coverage file as a drive-by of an
# unrelated task -- see that file's git history for the original rationale).
# Consolidating now because both copies needed the same fix at once: neither
# recognized the `Sources` PropertyLinkSubList convention (brick_proxy,
# quoin_proxy, shingle_proxy, slate_proxy) as a valid "trace back to the real
# roof face" path -- only the older BaseObject / ShingledRoof_ / ShingleSkin_
# convention from shingle_generator's legacy macro-only workflow. A user
# selecting faces from any *current* tiled/shingled output (which all use
# Sources) got silently fed tiny individual tile/shingle fragments instead
# of the true whole roof face, breaking hip/valley classification.

import FreeCAD as App
import Part

from roof_geometry import best_matching_candidate


def find_shared_edge(face1, face2, tol=0.1):
    """
    Find the edge shared between two faces, by endpoint matching first and
    a collinear-overlap check second.

    Parameters
    ----------
    face1, face2 : Part.Face
    tol : float
        Distance tolerance (document units) for both checks.

    Returns
    -------
    Part.Edge or None
        None if no shared or collinear-overlapping edge is found.
    """
    for e1 in face1.Edges:
        p1a = e1.Vertexes[0].Point
        p1b = e1.Vertexes[-1].Point
        for e2 in face2.Edges:
            p2a = e2.Vertexes[0].Point
            p2b = e2.Vertexes[-1].Point
            d = min(max(p1a.distanceToPoint(p2a), p1b.distanceToPoint(p2b)),
                    max(p1a.distanceToPoint(p2b), p1b.distanceToPoint(p2a)))
            if d < tol:
                return e1

    for e1 in face1.Edges:
        if not isinstance(e1.Curve, (Part.Line, Part.LineSegment)):
            continue
        p1a = e1.Vertexes[0].Point
        p1b = e1.Vertexes[-1].Point
        d1 = p1b.sub(p1a)
        len1 = d1.Length
        if len1 < 0.001:
            continue
        dir1 = App.Vector(d1)
        dir1.normalize()

        for e2 in face2.Edges:
            if not isinstance(e2.Curve, (Part.Line, Part.LineSegment)):
                continue
            p2a = e2.Vertexes[0].Point
            p2b = e2.Vertexes[-1].Point
            d2 = p2b.sub(p2a)
            len2 = d2.Length
            if len2 < 0.001:
                continue
            if d1.cross(d2).Length / (len1 * len2) > 0.01:
                continue
            offset = p2a.sub(p1a)
            perp = offset.sub(dir1 * offset.dot(dir1))
            if perp.Length > tol:
                continue
            t1a, t1b = 0.0, p1b.sub(p1a).dot(dir1)
            t2a = p2a.sub(p1a).dot(dir1)
            t2b = p2b.sub(p1a).dot(dir1)
            overlap = min(max(t1a, t1b), max(t2a, t2b)) - max(min(t1a, t1b), min(t2a, t2b))
            if overlap >= tol:
                return e1 if len1 <= len2 else e2

    return None


def _closest_candidate(orig_face, candidates):
    """
    Return the (face, owner) pair in *candidates* geometrically closest to
    *orig_face*. Thin FreeCAD-object plumbing: extracts plain distance/
    normal-tuple data from each Part.Face and hands the actual "which one
    wins" scoring to roof_geometry.best_matching_candidate, so that pure
    math is pytest-testable without FreeCAD. Shared scoring core for both
    the single-owner legacy path (`_closest_base_face`) and the multi-owner
    `Sources` path, so there is one place that defines "closest match"
    rather than two that could drift.

    Parameters
    ----------
    orig_face : Part.Face
    candidates : list of (Part.Face, owner_obj)

    Returns
    -------
    (Part.Face, owner_obj) or (None, None)
        (None, None) if *candidates* is empty.
    """
    if not candidates:
        return None, None
    orig_center = orig_face.CenterOfMass
    orig_normal_v = orig_face.normalAt(0.5, 0.5)
    orig_normal = (orig_normal_v.x, orig_normal_v.y, orig_normal_v.z)
    test_vtx = Part.Vertex(orig_center)

    scored = []  # (distance, candidate_normal, (face, owner))
    for f, owner in candidates:
        try:
            d = f.distToShape(test_vtx)[0]
        except Exception:
            d = orig_center.distanceToPoint(f.CenterOfMass)
        try:
            fn = f.normalAt(0.5, 0.5)
            normal = (fn.x, fn.y, fn.z)
        except Exception:
            normal = (0.0, 0.0, 0.0)
        scored.append((d, normal, (f, owner)))

    best = best_matching_candidate(orig_normal, scored)
    return best if best is not None else (None, None)


def _closest_base_face(orig_face, base_faces):
    """Return the face in base_faces geometrically closest to orig_face.
    Single-owner convenience wrapper around _closest_candidate."""
    face, _owner = _closest_candidate(orig_face, [(f, None) for f in base_faces])
    return face


def resolve_base_face(face, obj, doc=None, _depth=0):
    """
    Trace a possibly wrapped/tiled/skinned face back to the real face and
    object it was generated from, if any wrapping is detected. Recognizes
    two conventions:

    - Legacy: an explicit `BaseObject` property; a sibling object whose
      `ShingleSkin` property points back at *obj* and which itself has a
      `BaseObject`; or `ShingledRoof_<name>` / `ShingleSkin_<name>` object
      naming. This is shingle_generator's old, destructive, macro-only
      workflow's convention.
    - Modern: a `Sources` PropertyLinkSubList (brick_proxy, quoin_proxy,
      shingle_proxy, slate_proxy) -- may reference faces from more than one
      object, so each candidate face's owner is tracked individually rather
      than assuming a single whole base object.

    Walks up to 5 levels in case of a chain of wraps (e.g. a seam cap
    generated on top of an already-wrapped output). Returns *(face, obj)*
    unchanged if no wrapping is detected by either convention.

    Parameters
    ----------
    face : Part.Face
        The originally selected face (possibly a tiny tile/shingle fragment).
    obj : FreeCAD document object
        The object *face* was selected from.
    doc : FreeCAD.Document, optional
        Document to search for a ShingleSkin-style sibling object and for
        ShingledRoof_/ShingleSkin_ name resolution. Defaults to
        App.ActiveDocument.

    Returns
    -------
    (Part.Face, obj)
        The resolved (face, obj) pair -- possibly the input unchanged.
    """
    if _depth >= 5:
        return face, obj

    base = None
    if 'BaseObject' in obj.PropertiesList:
        candidate = obj.getPropertyByName('BaseObject')
        if candidate is not None:
            base = candidate

    if base is None:
        doc_objects = (doc.Objects if doc else
                       (App.ActiveDocument.Objects if App.ActiveDocument else []))
        for doc_obj in doc_objects:
            if ('ShingleSkin' in doc_obj.PropertiesList
                    and doc_obj.getPropertyByName('ShingleSkin') is obj
                    and 'BaseObject' in doc_obj.PropertiesList):
                candidate = doc_obj.getPropertyByName('BaseObject')
                if candidate is not None:
                    base = candidate
                    break

    if base is None:
        for prefix in ('ShingledRoof_', 'ShingleSkin_'):
            if obj.Name.startswith(prefix):
                base_name = obj.Name[len(prefix):]
                doc_to_use = doc or App.ActiveDocument
                if doc_to_use:
                    candidate = doc_to_use.getObject(base_name)
                    if candidate is not None:
                        base = candidate
                        break

    if base is not None:
        best = _closest_base_face(face, base.Shape.Faces)
        if best is not None:
            return resolve_base_face(best, base, doc, _depth + 1)
        return face, obj

    candidates = []
    if 'Sources' in obj.PropertiesList:
        sources = obj.getPropertyByName('Sources') or []
        # Delegates to resolve_sources_faces() -- this used to be a second,
        # independently-coded implementation (int(sub_name[4:]) index
        # arithmetic) of the same "Sources sub_name -> Face" operation
        # every proxy's getElement(sub_name) idiom already handles, added
        # by the very commit whose stated goal was consolidating this
        # logic to one place (see the module-level "Roof-seam face
        # resolution" changelog entry above). Single source of truth now.
        candidates = [(face, link_obj) for face, link_obj, _sub_name
                      in resolve_sources_faces(sources, 'resolve_base_face')]

    if candidates:
        best_face, best_owner = _closest_candidate(face, candidates)
        if best_face is not None:
            return resolve_base_face(best_face, best_owner, doc, _depth + 1)

    return face, obj


def resolve_shared_edge(face1, obj1, face2, obj2, doc=None):
    """
    Find the shared edge between two faces, auto-unwrapping tiled/skinned
    outputs (via resolve_base_face) to the real source roof faces if the
    faces as selected don't share an edge directly.

    Tries, in order: (1) the two faces as given, (2) both faces unwrapped
    to their real source via resolve_base_face, (3) a geometric-intersection
    fallback (Face.section) on both the unwrapped and original pairs.

    Parameters
    ----------
    face1, face2 : Part.Face
    obj1, obj2 : FreeCAD document object
        The objects *face1*/*face2* were selected from.
    doc : FreeCAD.Document, optional
        Passed through to resolve_base_face.

    Returns
    -------
    (Part.Edge or None, Part.Face, obj, Part.Face, obj)
        The shared edge (or None if none found) and the (possibly
        unwrapped) face/object pairs it was found between.
    """
    edge = find_shared_edge(face1, face2)
    if edge is not None:
        return edge, face1, obj1, face2, obj2

    f1, o1 = resolve_base_face(face1, obj1, doc)
    f2, o2 = resolve_base_face(face2, obj2, doc)
    if f1 is not face1 or f2 is not face2:
        App.Console.PrintMessage(
            f"  Unwrapping {obj1.Name} -> {o1.Name}, {obj2.Name} -> {o2.Name}\n")
        edge = find_shared_edge(f1, f2)
        if edge is not None:
            return edge, f1, o1, f2, o2

    for fa, oa, fb, ob in [(f1, o1, f2, o2), (face1, obj1, face2, obj2)]:
        try:
            section = fa.section(fb)
            if section.Edges:
                seam = max(section.Edges, key=lambda e: e.Length)
                App.Console.PrintMessage(
                    f"  Found seam via geometric intersection: {seam.Length:.2f} mm\n")
                return seam, fa, oa, fb, ob
        except Exception as e:
            App.Console.PrintMessage(f"  section() failed: {e}\n")

    return None, face1, obj1, face2, obj2


# ---------------------------------------------------------------------------
# Sources resolution
# ---------------------------------------------------------------------------
# Extracted 2026-08-08 from 8 proxies that each independently reimplemented
# "walk an App::PropertyLinkSubList named Sources, resolve each sub-element
# name to a Part.Face" -- the same operation, copy-pasted 8 times. Only 3
# copies (board_batten_proxy.py, roof_seam_proxy.py, slate_seam_proxy.py)
# guarded getElement() in a per-entry try/except; the other 5 called it
# unguarded, so a single stale sub_name (a normal occurrence after any
# topology change elsewhere in the document, not a rare event) raised
# uncaught and aborted resolution of every remaining Sources entry, not just
# the affected one. smart_trim_proxy.py additionally had no hasattr(Shape)
# guard and no Face-type filter at all. Consolidating so there is one
# correct implementation instead of 8 that could (and had) drifted.

def resolve_sources_faces(sources, caller_name):
    """
    Safely resolve an App::PropertyLinkSubList `Sources` value to a list of
    validated (face, link_obj, sub_name) triples.

    Each Sources entry is (link_obj, sub_names) where sub_names is a list of
    sub-element names (e.g. "Face3"). For each sub_name:
      - a link_obj with no Shape attribute (e.g. deleted/orphaned) is skipped
      - a sub_name not starting with 'Face' (an Edge/Vertex selection) is
        skipped
      - link_obj.Shape.getElement(sub_name) is called inside a per-entry
        try/except -- a stale sub_name raises there and is skipped WITHOUT
        aborting resolution of the remaining entries

    Every skip is counted; if any occurred, one summary PrintWarning is
    emitted (in addition to the existing per-failure PrintError for
    getElement() exceptions specifically) so partial data loss during batch
    processing stays visible instead of disappearing silently.

    Parameters
    ----------
    sources : list of (FreeCAD document object, list of str)
        The value of an obj.Sources PropertyLinkSubList.
    caller_name : str
        Prefix used in per-entry and summary messages (e.g. "SlateGenerator").

    Returns
    -------
    list of (Part.Face, owner_obj, str)
        Resolved (face, link_obj, sub_name) triples, in Sources order.

    Preconditions:
        - sources: must be iterable of (link_obj, sub_names) pairs
        - caller_name: must be a non-empty str

    Postconditions:
        - returned value is a list (possibly empty, never None)
        - every element is a 3-tuple whose first item is a Part.Face
          (ShapeType == "Face")
    """
    # --- Preconditions ---
    _assert(isinstance(caller_name, str) and caller_name.strip(),
            f"resolve_sources_faces: caller_name must be a non-empty str, "
            f"got {caller_name!r}")

    faces = []
    skipped = 0
    for link_obj, sub_names in sources:
        if not hasattr(link_obj, 'Shape'):
            skipped += len(sub_names)
            continue
        for sub_name in sub_names:
            if not sub_name.startswith('Face'):
                skipped += 1
                continue
            try:
                face = link_obj.Shape.getElement(sub_name)
            except Exception as e:
                skipped += 1
                App.Console.PrintError(
                    f"{caller_name}: {link_obj.Label}/{sub_name}: {e}\n")
                continue
            faces.append((face, link_obj, sub_name))

    if skipped:
        App.Console.PrintWarning(
            f"{caller_name}: skipped {skipped} unusable Sources "
            f"entr{'y' if skipped == 1 else 'ies'}\n")

    # --- Postconditions ---
    _assert(isinstance(faces, list),
            f"resolve_sources_faces: expected list result, got {type(faces).__name__!r}")
    if _ASSERTIONS_ENABLED:
        for face, _owner, _sub_name in faces:
            _assert(face.ShapeType == "Face",
                    f"resolve_sources_faces: expected ShapeType='Face', "
                    f"got {face.ShapeType!r}")

    return faces


# ---------------------------------------------------------------------------
# Font-path resolution
# ---------------------------------------------------------------------------
# Extracted 2026-08-08 from label_proxy.py and station_sign_proxy.py, which
# each independently duplicated the same "does this font path actually
# exist?" check inline in their _make_text_faces(), and each independently
# collapsed three distinct cases -- FontPath unset, FontPath set but the
# file doesn't exist, FontPath valid -- into passing "" to
# Part.makeWireString (which silently falls back to its own system default
# font) with no signal to the user which case occurred or that their chosen
# font wasn't actually used.

def find_first_existing_path(candidates):
    """
    Return the first path in *candidates* that exists on disk, or "" if
    none do.

    Used to build a fallback default font (or similar) path from a list of
    per-platform/per-project candidates. Deliberately does not interpret or
    rank *why* a candidate is preferred -- that ordering is the caller's own
    config, not something this helper should encode.

    Parameters
    ----------
    candidates : sequence of str

    Returns
    -------
    str
        The first existing path, or "" if none exist (including if
        *candidates* is empty).
    """
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def resolve_font_path(font_path, caller_name):
    """
    Resolve *font_path* (an obj.FontPath property value) for
    Part.makeWireString, distinguishing *why* no usable font was found
    instead of silently collapsing every failure case into the same "".

    Parameters
    ----------
    font_path : str
        The current obj.FontPath property value (may be empty/None).
    caller_name : str
        Prefix for the printed warning (e.g. "LabelProxy").

    Returns
    -------
    str
        *font_path* unchanged if it is a non-empty, existing file;
        otherwise "" (Part.makeWireString falls back to its own system
        default font in that case). A PrintWarning distinguishes "FontPath
        is not set" from "FontPath does not exist" so a user whose chosen
        font silently isn't being used can tell why, instead of the two
        cases being indistinguishable console output (or no output at all).

    Preconditions:
        - caller_name: must be a non-empty str

    Postconditions:
        - returned value is a str (never None)
    """
    # --- Preconditions ---
    _assert(isinstance(caller_name, str) and caller_name.strip(),
            f"resolve_font_path: caller_name must be a non-empty str, "
            f"got {caller_name!r}")

    if not font_path:
        App.Console.PrintWarning(
            f"{caller_name}: FontPath is not set -- using system default font\n")
        return ""
    if not os.path.exists(font_path):
        App.Console.PrintWarning(
            f"{caller_name}: FontPath {font_path!r} does not exist -- "
            f"using system default font\n")
        return ""
    return font_path


# ---------------------------------------------------------------------------
# Spreadsheet discovery
# ---------------------------------------------------------------------------

def find_spreadsheet(doc):
    """
    Find a spreadsheet object in *doc* by name or label, following App::Link
    if the named object is a link to a spreadsheet.

    Searches names in priority order:
      ``params`` → ``ShingleParameters`` → ``BuildingParameters`` → ``Spreadsheet``

    For each candidate, first tries ``doc.getObject(name)`` (internal name
    match), then scans ``doc.Objects`` for a matching ``Label``.  Both paths
    resolve App::Link transparently.

    Parameters
    ----------
    doc : FreeCAD.Document

    Returns
    -------
    Spreadsheet::Sheet or None
        The first matching spreadsheet, or None if none found.

    Preconditions:
        - doc: must not be None
        - doc: must have getObject() and Objects attributes (must be a
          FreeCAD Document, not a string or path)

    Postconditions:
        - if a non-None value is returned, its TypeId is 'Spreadsheet::Sheet'
          (links are resolved; the raw link object is never returned)
        - if no spreadsheet is present in the document, returns None (never
          raises; callers must check for None)
    """
    # --- Preconditions ---
    _assert(doc is not None,
            f"find_spreadsheet: doc must not be None")
    _assert(hasattr(doc, 'getObject') and hasattr(doc, 'Objects'),
            f"find_spreadsheet: doc must be a FreeCAD.Document (has getObject + Objects), "
            f"got type={type(doc).__name__!r}")

    preferred_names = ["params", "ShingleParameters", "BuildingParameters", "Spreadsheet"]
    for ss_name in preferred_names:
        # Try internal object name first
        obj = doc.getObject(ss_name)
        if obj:
            if obj.TypeId == 'App::Link':
                target = obj.LinkedObject
                if target and target.TypeId == 'Spreadsheet::Sheet':
                    # --- Postcondition (link path) ---
                    _assert(target.TypeId == 'Spreadsheet::Sheet',
                            f"find_spreadsheet: resolved link target has unexpected TypeId="
                            f"{target.TypeId!r} (expected 'Spreadsheet::Sheet')")
                    return target
            elif obj.TypeId == 'Spreadsheet::Sheet':
                # --- Postcondition (direct path) ---
                _assert(obj.TypeId == 'Spreadsheet::Sheet',
                        f"find_spreadsheet: matched object has unexpected TypeId="
                        f"{obj.TypeId!r} (expected 'Spreadsheet::Sheet')")
                return obj
        # Fall back to Label match
        for obj in doc.Objects:
            if obj.Label == ss_name:
                if obj.TypeId == 'App::Link':
                    target = obj.LinkedObject
                    if target and target.TypeId == 'Spreadsheet::Sheet':
                        _assert(target.TypeId == 'Spreadsheet::Sheet',
                                f"find_spreadsheet: resolved link target has unexpected TypeId="
                                f"{target.TypeId!r} (expected 'Spreadsheet::Sheet')")
                        return target
                elif obj.TypeId == 'Spreadsheet::Sheet':
                    _assert(obj.TypeId == 'Spreadsheet::Sheet',
                            f"find_spreadsheet: matched object has unexpected TypeId="
                            f"{obj.TypeId!r} (expected 'Spreadsheet::Sheet')")
                    return obj
    return None


# ---------------------------------------------------------------------------
# Undoable output creation
# ---------------------------------------------------------------------------

def commit_result(doc, object_name, shape, generator_name, generator_version,
                  extra_props=None, transaction_label=None):
    """
    Create an output Part::Feature inside an undo transaction.

    Wraps ``doc.addObject`` + property assignment + ``doc.recompute()``
    in ``openTransaction`` / ``commitTransaction`` so the entire operation
    is a single Ctrl+Z step.  On error the transaction is aborted
    (no partial objects left behind).

    Parameters
    ----------
    doc : FreeCAD.Document
        Active document.
    object_name : str
        Name for the new Part::Feature (e.g. "HipCap_Roof").
    shape : Part.Shape
        The shape to assign (Compound, Solid, etc.).
    generator_name : str
        Value for the GeneratorName metadata property.
    generator_version : str
        Value for the GeneratorVersion metadata property.
    extra_props : dict, optional
        Additional ``{prop_name: (prop_type, group, tooltip, value)}``
        entries.  Example::

            {"SeamType": ("App::PropertyString", "Metadata",
                          "Seam type (hip or valley)", "hip")}

    transaction_label : str, optional
        Label shown in Edit→Undo.  Defaults to
        ``"{generator_name}: {object_name}"``.

    Returns
    -------
    FreeCAD.DocumentObject
        The newly created Part::Feature.

    Preconditions:
        - doc: must not be None; must support openTransaction/addObject
        - object_name: must be a non-empty str (used as FreeCAD object name)
        - shape: must not be None; must be a Part.Shape or compatible;
          must be valid (shape.isValid()) and non-degenerate (positive
          BoundBox diagonal)
        - generator_name: must be a non-empty str
        - generator_version: must be a non-empty str
        - extra_props: if provided, must be a dict; each value must be a
          4-tuple of (prop_type_str, group_str, tooltip_str, value)

    Postconditions:
        - returned object is not None
        - returned object has GeneratorName == generator_name
        - returned object has GeneratorVersion == generator_version
        - returned object has a Shape assigned (Shape is not None)
    """
    # --- Preconditions ---
    _assert(doc is not None,
            f"commit_result: doc must not be None")
    _assert(hasattr(doc, 'openTransaction') and hasattr(doc, 'addObject'),
            f"commit_result: doc must be a FreeCAD.Document, got type={type(doc).__name__!r}")

    _assert(isinstance(object_name, str) and object_name.strip(),
            f"commit_result: object_name must be a non-empty str, got {object_name!r}")

    _assert(shape is not None,
            f"commit_result: shape must not be None (object_name={object_name!r})")
    _assert(hasattr(shape, 'isValid'),
            f"commit_result: shape must be a Part.Shape (has isValid()), "
            f"got type={type(shape).__name__!r} (object_name={object_name!r})")
    _assert(shape.isValid(),
            f"commit_result: shape.isValid() returned False for object_name={object_name!r}; "
            f"OCCT considers this shape corrupt — do not commit invalid geometry")
    _assert(hasattr(shape, 'BoundBox') and shape.BoundBox.DiagonalLength > 0,
            f"commit_result: shape has zero/degenerate BoundBox "
            f"(DiagonalLength={getattr(shape, 'BoundBox', None) and shape.BoundBox.DiagonalLength!r}) "
            f"for object_name={object_name!r}; shape is empty or point-degenerate")

    _assert(isinstance(generator_name, str) and generator_name.strip(),
            f"commit_result: generator_name must be a non-empty str, got {generator_name!r}")
    _assert(isinstance(generator_version, str) and generator_version.strip(),
            f"commit_result: generator_version must be a non-empty str, got {generator_version!r}")

    _assert(extra_props is None or isinstance(extra_props, dict),
            f"commit_result: extra_props must be dict or None, got "
            f"{type(extra_props).__name__!r}")
    if extra_props and _ASSERTIONS_ENABLED:
        for prop_name, prop_spec in extra_props.items():
            _assert(isinstance(prop_spec, tuple) and len(prop_spec) == 4,
                    f"commit_result: extra_props[{prop_name!r}] must be a 4-tuple "
                    f"(prop_type, group, tooltip, value), got {prop_spec!r}")

    _assert(transaction_label is None or isinstance(transaction_label, str),
            f"commit_result: transaction_label must be str or None, got "
            f"{type(transaction_label).__name__!r} value={transaction_label!r}")

    label = transaction_label or f"{generator_name}: {object_name}"
    doc.openTransaction(label)
    try:
        result = doc.addObject("Part::Feature", object_name)
        result.Shape = shape

        result.addProperty(
            "App::PropertyString", "GeneratorName", "Metadata", "Generator name")
        result.GeneratorName = generator_name

        result.addProperty(
            "App::PropertyString", "GeneratorVersion", "Metadata", "Generator version")
        result.GeneratorVersion = generator_version

        if extra_props:
            for prop_name, (prop_type, group, tooltip, value) in extra_props.items():
                result.addProperty(prop_type, prop_name, group, tooltip)
                setattr(result, prop_name, value)

        doc.recompute()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise

    # --- Postconditions ---
    _assert(result is not None,
            f"commit_result: doc.addObject returned None for object_name={object_name!r}")
    _assert(result.Shape is not None,
            f"commit_result: result.Shape is None after assignment for object_name={object_name!r}")
    _assert(result.GeneratorName == generator_name,
            f"commit_result: GeneratorName mismatch: expected {generator_name!r}, "
            f"got {result.GeneratorName!r} (object_name={object_name!r})")
    _assert(result.GeneratorVersion == generator_version,
            f"commit_result: GeneratorVersion mismatch: expected {generator_version!r}, "
            f"got {result.GeneratorVersion!r} (object_name={object_name!r})")

    return result
