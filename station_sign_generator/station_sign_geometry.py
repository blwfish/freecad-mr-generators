"""
Station Sign Geometry Library v1.1.0

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

v1.1.0 (full-review finding freecad-mr-generators-20260915-e612#06):
bbox_contains()/group_wire_bboxes_into_islands() moved to
shared/face_geometry.py -- this disconnected-glyph-island logic isn't
station-sign-specific (label_generator needs the identical algorithm and
had drifted into its own untested, buggy inline copy). Re-exported here so
existing `from station_sign_geometry import bbox_contains,
group_wire_bboxes_into_islands` call sites and tests keep working
unchanged.
"""

import math
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

_shared_path = str(Path(__file__).parent.parent / 'shared')
if _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

from face_geometry import BBox, bbox_contains, group_wire_bboxes_into_islands  # noqa: E402,F401


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
