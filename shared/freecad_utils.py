"""
freecad_utils.py — Shared FreeCAD utility library for generators

Installed to: Macro/_lib/freecad_utils.py
Imported by:  brick_generator_macro, radial_brick_generator_macro,
              clapboard_generator, board_batten_generator, bead_board_generator,
              shingle_generator, smart_trim_generator, station_sign_generator,
              roof_seam_generator

Version: 1.3.0
  1.3.0: Add precondition/postcondition assertions throughout (GEN_NO_ASSERT=1 to disable).
  1.2.0: Add find_spreadsheet() — multi-name spreadsheet lookup with App::Link support.
  1.1.0: Add commit_result() — undoable output object creation with metadata.
  1.0.2: Initial shared library (global placement helpers).
"""

import os

__version__ = "1.3.0"

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
