"""
Station Sign Geometry Library v1.0.0

Pure Python geometry functions for the station sign generator, extracted
2026-08-08 (full-review finding #29) from station_sign_proxy.py, the one
generator in this repo that shipped with no *_geometry.py module and no
tests/ directory at all -- its sign/border/text sizing math (including the
disconnected-glyph-island bbox-containment logic) had zero verification of
any kind since the initial commit.

No FreeCAD dependencies -- fully testable with pytest. Bounding boxes are
plain (xmin, xmax, ymin, ymax) tuples here rather than FreeCAD BoundBox
objects, so station_sign_proxy.py's real Part.Wire.BoundBox values are
converted to tuples at the call site before reaching this module.
"""

import math
from typing import Dict, List, Sequence, Tuple

BBox = Tuple[float, float, float, float]  # (xmin, xmax, ymin, ymax)


# ---------------------------------------------------------------------------
# Disconnected-glyph-island bbox containment
# ---------------------------------------------------------------------------

def bbox_contains(outer: BBox, inner: BBox, eps: float = 1e-6) -> bool:
    """
    Return True if *inner* is contained within *outer*, to within *eps*.

    *eps* is a tolerance in both directions (an inner bbox extending
    infinitesimally past outer's edge, within eps, still counts as
    contained) -- matches Part.Wire.BoundBox comparisons where floating-
    point glyph coordinates rarely land on an exact boundary.
    """
    o_xmin, o_xmax, o_ymin, o_ymax = outer
    i_xmin, i_xmax, i_ymin, i_ymax = inner
    return (i_xmin >= o_xmin - eps and i_xmax <= o_xmax + eps and
            i_ymin >= o_ymin - eps and i_ymax <= o_ymax + eps)


def group_wire_bboxes_into_islands(bboxes: Sequence[BBox],
                                    eps: float = 1e-6) -> List[List[int]]:
    """
    Group wire indices into (outer, [holes...]) islands by bounding-box
    containment, the way a glyph like 'i' or 'j' (a stem plus a separate
    dot) or a glyph with a true hole (like 'o' or 'e') needs to be
    interpreted: bboxes with no containing parent are "outer" wires; every
    bbox contained within an outer wire's bbox joins that outer wire's
    group (so Part.Face(group) treats it as a hole, not a separate face).

    Returns a list of groups, each group a list of indices into *bboxes*
    with the outer wire's index first. A bbox that is both an "outer" wire
    (nothing contains it) and not contained by anything starts its own
    singleton group if it has no contained children.

    Degenerate inputs:
    - Fewer than 2 bboxes: every non-empty input is its own single-element
      group (there's nothing for it to contain or be contained by).
    - A single bbox: same as above, returns [[0]] (or [] for empty input).
    """
    n = len(bboxes)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    is_outer = [True] * n
    for i in range(n):
        for j in range(n):
            if i != j and bbox_contains(bboxes[j], bboxes[i], eps):
                is_outer[i] = False
                break

    used = [False] * n
    groups = []
    for i in range(n):
        if not is_outer[i] or used[i]:
            continue
        used[i] = True
        group = [i]
        for j in range(n):
            if not used[j] and not is_outer[j] and bbox_contains(bboxes[i], bboxes[j], eps):
                group.append(j)
                used[j] = True
        groups.append(group)

    return groups


# ---------------------------------------------------------------------------
# Sign layout
# ---------------------------------------------------------------------------

def calculate_sign_layout(text_w: float, text_h: float,
                          text_xmin: float, text_ymin: float,
                          mat_thick: float, border_thick: float,
                          border_gap: float) -> Dict:
    """
    Calculate the station sign's overall dimensions and layer/text
    placement, scaling the sign to fit the measured text exactly.

    Layout (looking from above):
        [border_thick][border_gap][text][border_gap][border_thick]

    Z layers:
        0              -> bg_thickness   : background slab  (2 x mat_thick)
        bg_thickness   -> border_height  : border frame      (1 x mat_thick)
        border_height  -> top            : raised text        (1 x mat_thick)

    Args:
        text_w, text_h: measured bounding-box width/height of the text at
            the target font size (Part.Wire.BoundBox.XLength/YLength)
        text_xmin, text_ymin: the text bounding box's own XMin/YMin, so
            text_x/text_y correctly re-center text that doesn't start at
            the local origin (a font's glyph outlines aren't guaranteed to
            start at (0, 0))
        mat_thick, border_thick, border_gap: as station_sign_proxy's own
            properties

    Returns dict with sign_w, sign_h, bg_thickness, border_height,
    inner_x, inner_y, inner_w, inner_h, text_x, text_y, text_z.

    Raises ValueError if mat_thick/border_thick <= 0, border_gap < 0, or
    text_w/text_h <= 0 (a degenerate/empty measured text bounding box).
    """
    if mat_thick <= 0:
        raise ValueError(f"mat_thick must be positive, got {mat_thick}")
    if border_thick <= 0:
        raise ValueError(f"border_thick must be positive, got {border_thick}")
    if border_gap < 0:
        raise ValueError(f"border_gap must not be negative, got {border_gap}")
    if text_w <= 0 or text_h <= 0:
        raise ValueError(
            f"text_w/text_h must be positive, got ({text_w}, {text_h})")

    sign_w = 2 * border_thick + 2 * border_gap + text_w
    sign_h = 2 * border_thick + 2 * border_gap + text_h

    bg_thickness = 2 * mat_thick
    border_height = bg_thickness + mat_thick

    inner_x = border_thick
    inner_y = border_thick
    inner_w = sign_w - 2 * border_thick
    inner_h = sign_h - 2 * border_thick

    text_x = inner_x + (inner_w - text_w) / 2 - text_xmin
    text_y = inner_y + (inner_h - text_h) / 2 - text_ymin
    text_z = border_height

    return {
        'sign_w': sign_w,
        'sign_h': sign_h,
        'bg_thickness': bg_thickness,
        'border_height': border_height,
        'inner_x': inner_x,
        'inner_y': inner_y,
        'inner_w': inner_w,
        'inner_h': inner_h,
        'text_x': text_x,
        'text_y': text_y,
        'text_z': text_z,
    }
