"""
freecad_utils.py — Shared FreeCAD utility library for generators

Installed to: Macro/_lib/freecad_utils.py
Imported by:  brick_generator_macro, radial_brick_generator_macro,
              clapboard_generator, board_batten_generator, bead_board_generator,
              shingle_generator, smart_trim_generator, station_sign_generator,
              roof_seam_generator

Version: 1.2.0
  1.2.0: Add find_spreadsheet() — multi-name spreadsheet lookup with App::Link support.
  1.1.0: Add commit_result() — undoable output object creation with metadata.
  1.0.2: Initial shared library (global placement helpers).
"""

__version__ = "1.2.0"


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
    """
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
    """
    try:
        return obj.getGlobalPlacement().toMatrix()
    except AttributeError:
        return None


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
    """
    try:
        return not obj.getGlobalPlacement().isIdentity()
    except AttributeError:
        return False


def log_global_placement(obj, label=None):
    """
    Print a one-line diagnostic if *obj* has a non-identity global
    placement.  Silent if placement is identity.

    Parameters
    ----------
    obj : FreeCAD document object
    label : str, optional
        Prefix shown in the message (defaults to obj.Label).
    """
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
    """
    preferred_names = ["params", "ShingleParameters", "BuildingParameters", "Spreadsheet"]
    for ss_name in preferred_names:
        # Try internal object name first
        obj = doc.getObject(ss_name)
        if obj:
            if obj.TypeId == 'App::Link':
                target = obj.LinkedObject
                if target and target.TypeId == 'Spreadsheet::Sheet':
                    return target
            elif obj.TypeId == 'Spreadsheet::Sheet':
                return obj
        # Fall back to Label match
        for obj in doc.Objects:
            if obj.Label == ss_name:
                if obj.TypeId == 'App::Link':
                    target = obj.LinkedObject
                    if target and target.TypeId == 'Spreadsheet::Sheet':
                        return target
                elif obj.TypeId == 'Spreadsheet::Sheet':
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
    """
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

    return result
