"""
Snow Guard Solid Geometry Library v1.0.0

Pure-Python geometry shared by snow_guard_proxy.py and
standing_seam_snow_guard_proxy.py's `_build_guard_solid` functions.

Named snow_guard_SOLID_geometry.py (not snow_guard_geometry.py) to avoid
colliding with snow_guard_generator/snow_guard_geometry.py -- install.py
flattens shared/*.py and every generator's *.py into one directory on
FreeCAD's sys.path (see install.py's collect_lib_files()), so two files
with the same basename in different source directories would silently
clobber one another at install time.

Both proxies build an identical box+extruded-triangle guard solid (a flat
mounting pad with a triangular-prism fin fused on top, centered on the
pad) -- the only difference between the two is parameter naming
(pad_* vs clamp_*). Before this module existed, the fin-centering math
was duplicated near-verbatim in both proxy files with nothing enforcing
that the copies stayed identical (full-review finding #20, 2026-08-08):
standing_seam_snow_guard_proxy.py's docstring asserted the construction
was "Identical ... to snow_guard_proxy.py's _build_guard_solid", but nothing
checked that claim, and the arithmetic lived only in FreeCAD-dependent
proxy code that plain `python3 -m pytest` can never reach.

This module extracts just the pure-arithmetic fin-centering positions --
not the FreeCAD Part/App calls that build the actual solid -- so the
formula has one source of truth and is directly pytest-testable.

No FreeCAD dependencies — fully testable with pytest.
"""

from typing import Tuple

__all__ = [
    'calculate_fin_position',
]


def calculate_fin_position(pad_width: float, pad_length: float,
                            fin_base_width: float, fin_thickness: float
                            ) -> Tuple[float, float]:
    """Return (fin_x0, fin_y0): the local-space origin offsets that center
    a snow-guard fin on its mounting pad.

    Local space matches both proxies' `_build_guard_solid`: x=u
    (across-slope, pad_width/clamp_width), y=v (up-slope, pad_length/
    clamp_length). The fin's triangular profile is built in the y-z plane
    starting at y=fin_y0 (so it's centered along the pad's length) and the
    resulting triangular-prism is translated by x=fin_x0 (so it's centered
    across the pad's width).

    fin_x0/fin_y0 can be negative (or leave the fin overhanging the pad)
    if the caller passes a fin_base_width/fin_thickness larger than the
    pad's own length/width -- this function does not clamp or validate;
    callers are responsible for the fin fitting on the pad, same as
    before extraction.
    """
    fin_y0 = (pad_length - fin_base_width) / 2.0
    fin_x0 = (pad_width - fin_thickness) / 2.0
    return fin_x0, fin_y0
