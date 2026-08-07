"""
Snow Guard Geometry Library v1.0.0

Pure Python geometry for placing snow guards (ice/snow stops) in a
staggered grid across a roof face — the pad-and-fin accessories that
prevent packed snow/ice from sliding off shingle, slate, and standing-seam
roofs. This module covers the slate case; shingle and standing-seam are
deferred.

Unlike the coursed-tile generators in this repo (slate, clapboard, board
batten), snow guards are a SPARSE placement, not a tiling fill pattern:
each guard is a small discrete solid, and there is no boolean clip against
the face boundary. The relevant OCCT-safety invariant is therefore "no
guard position lands on the face boundary" (see shared/boundary_assertions
.assert_no_boundary_coincidence), not "the union of elements overflows the
boundary" (assert_overflows_boundary, used by the tiling generators).

No FreeCAD dependencies — fully testable with pytest.
"""

from typing import List, Tuple

__all__ = [
    'validate_parameters',
    'calculate_row_v_positions',
    'calculate_row_u_positions',
    'calculate_grid_positions',
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_parameters(pad_width: float, pad_length: float, pad_thickness: float,
                         fin_height: float, fin_base_width: float,
                         fin_thickness: float) -> Tuple[bool, List[str]]:
    """Validate snow guard solid dimensions for physical soundness.

    pad_width/pad_length are the mounting pad's footprint (across-slope /
    up-slope respectively); fin_base_width is how much of the pad's
    up-slope extent the fin's base occupies, fin_thickness is the fin's
    across-slope extent, fin_height is how far the fin stands proud of the
    roof surface.
    """
    errors = []
    if pad_width <= 0:
        errors.append(f"pad_width must be positive, got {pad_width}")
    if pad_length <= 0:
        errors.append(f"pad_length must be positive, got {pad_length}")
    if pad_thickness <= 0:
        errors.append(f"pad_thickness must be positive, got {pad_thickness}")
    if fin_height <= 0:
        errors.append(f"fin_height must be positive, got {fin_height}")
    if fin_base_width <= 0:
        errors.append(f"fin_base_width must be positive, got {fin_base_width}")
    if fin_thickness <= 0:
        errors.append(f"fin_thickness must be positive, got {fin_thickness}")
    if fin_base_width > 0 and pad_length > 0 and fin_base_width > pad_length:
        errors.append(
            f"fin_base_width ({fin_base_width}) cannot exceed pad_length ({pad_length})")
    if fin_thickness > 0 and pad_width > 0 and fin_thickness > pad_width:
        errors.append(
            f"fin_thickness ({fin_thickness}) cannot exceed pad_width ({pad_width})")
    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Row placement (up-slope axis, "v")
# ---------------------------------------------------------------------------

def calculate_row_v_positions(v_length: float, num_rows: int, first_row_offset: float,
                               row_spacing: float, v_margin: float) -> List[float]:
    """Return the up-slope (v) offset of each guard row, measured from the
    eave (v=0).

    Rows are evenly spaced starting at first_row_offset: row i sits at
    first_row_offset + i * row_spacing. row_spacing is unused (and
    unvalidated) when num_rows == 1.

    v_margin is a REQUIRED positive safety margin (not a fixed epsilon):
    every row must land within [v_margin, v_length - v_margin]. This is a
    hard validation error, not a silent clamp/drop — a config that doesn't
    fit the face is a configuration mistake the caller must fix (mirrors
    calculate_course_v_positions in clapboard_generator/clapboard_geometry
    .py, which raises rather than silently dropping courses that don't
    fit). Keeping v_margin strictly positive also guarantees no row can
    ever land exactly on the real face boundary (v=0 or v=v_length) --
    the condition shared/boundary_assertions.assert_no_boundary_coincidence
    exists to catch.

    Raises ValueError if num_rows < 1, any input is out of range, or the
    row grid doesn't fit within [v_margin, v_length - v_margin].
    """
    if num_rows < 1:
        raise ValueError(f"num_rows must be >= 1, got {num_rows}")
    if first_row_offset < 0:
        raise ValueError(f"first_row_offset must be >= 0, got {first_row_offset}")
    if num_rows > 1 and row_spacing <= 0:
        raise ValueError(
            f"row_spacing must be positive when num_rows > 1, got {row_spacing}")
    if v_margin <= 0:
        raise ValueError(f"v_margin must be positive, got {v_margin}")

    positions = [first_row_offset + i * row_spacing for i in range(num_rows)]

    lo, hi = v_margin, v_length - v_margin
    eps = 1e-9
    if positions[0] < lo - eps or positions[-1] > hi + eps:
        raise ValueError(
            f"row grid does not fit face: rows span [{positions[0]}, {positions[-1]}], "
            f"but usable range is [{lo}, {hi}] (v_length={v_length}, v_margin={v_margin})"
        )

    return positions


# ---------------------------------------------------------------------------
# Within-row placement (across-slope axis, "u")
# ---------------------------------------------------------------------------

def _row_spacing(u_length: float, guards_per_row: int, edge_margin: float,
                  reserve_stagger: bool) -> Tuple[float, float, float]:
    """Single source of truth for a row's (lo, hi, spacing): both
    calculate_row_u_positions and calculate_grid_positions call this
    rather than each computing their own copy, so the two can never drift
    apart (the specific failure mode this repo's Syntactic-Semantic Seam
    Rule targets).

    reserve_stagger=True divides the usable span into (guards_per_row -
    0.5) intervals instead of (guards_per_row - 1). This is NOT cosmetic:
    with the plain (guards_per_row - 1) denominator, the unstaggered row's
    last guard already sits exactly at `hi` (edge_margin from the real
    boundary) -- shifting that same row by +spacing/2 would push it
    spacing/2 past `hi`, outside the safety margin. Reserving one extra
    half-interval of headroom up front means the UNSTAGGERED row's own
    positions stop short of `hi` by exactly half a spacing interval, so
    the STAGGERED row (shifted by that same half-interval) lands with its
    last guard exactly at `hi` instead of beyond it. Both parities then
    share one `spacing` value (so guards visually align into a proper
    zigzag lattice) and both stay within [lo, hi].

    Raises ValueError if guards_per_row < 1, edge_margin isn't positive,
    or edge_margin leaves no usable span.
    """
    if guards_per_row < 1:
        raise ValueError(f"guards_per_row must be >= 1, got {guards_per_row}")
    if edge_margin <= 0:
        raise ValueError(f"edge_margin must be positive, got {edge_margin}")

    lo, hi = edge_margin, u_length - edge_margin
    if hi <= lo:
        raise ValueError(
            f"edge_margin ({edge_margin}) leaves no usable span on u_length ({u_length})")

    if guards_per_row == 1:
        return lo, hi, 0.0

    denom = (guards_per_row - 0.5) if reserve_stagger else (guards_per_row - 1)
    spacing = (hi - lo) / denom
    return lo, hi, spacing


def calculate_row_u_positions(u_length: float, guards_per_row: int, edge_margin: float,
                               stagger_offset: float = 0.0,
                               reserve_stagger: bool = False) -> List[float]:
    """Return the across-slope (u) position of each guard in one row,
    evenly spaced within [edge_margin, u_length - edge_margin].

    guards_per_row == 1 is a special case: the single guard is centered
    and stagger_offset is ignored entirely (there is no spacing interval
    to derive a meaningful stagger from a single point) -- an explicit
    decision, not an oversight.

    edge_margin is a REQUIRED positive safety margin, same rationale as
    calculate_row_v_positions' v_margin: guarantees no guard can land
    exactly on the real face boundary (u=0 or u=u_length).

    reserve_stagger must match whatever value the caller will use across
    the whole grid (calculate_grid_positions passes the grid's own
    stagger_rows flag to every row) -- see _row_spacing for why the
    spacing denominator itself must change, not just the offset.

    Raises ValueError if guards_per_row < 1, edge_margin doesn't leave a
    usable span, or (with a stagger_offset inconsistent with
    reserve_stagger) a guard position falls outside
    [edge_margin, u_length - edge_margin].
    """
    lo, hi, spacing = _row_spacing(u_length, guards_per_row, edge_margin, reserve_stagger)

    if guards_per_row == 1:
        positions = [(lo + hi) / 2.0]
    else:
        positions = [lo + i * spacing + stagger_offset for i in range(guards_per_row)]

    eps = 1e-9
    bad = [p for p in positions if p < lo - eps or p > hi + eps]
    if bad:
        raise ValueError(
            f"guard position(s) {bad} fall outside usable range [{lo}, {hi}] "
            f"(u_length={u_length}, edge_margin={edge_margin}, stagger_offset={stagger_offset})"
        )

    return positions


# ---------------------------------------------------------------------------
# Combined grid
# ---------------------------------------------------------------------------

def calculate_grid_positions(u_length: float, v_length: float, num_rows: int,
                              first_row_offset: float, row_spacing: float,
                              guards_per_row: int, edge_margin: float, v_margin: float,
                              stagger_rows: bool = True) -> List[Tuple[int, float, float]]:
    """Return (row_index, u, v) for every guard in the staggered grid.

    When stagger_rows is True, every odd row (1, 3, 5, ...) is offset by
    half of the shared row spacing, producing the zigzag pattern real
    snow-guard installations use to distribute load -- see _row_spacing
    for why enabling this also changes the (shared, single-source-of-truth)
    spacing denominator, not just the offset applied to odd rows.

    Raises ValueError (propagated from calculate_row_v_positions /
    calculate_row_u_positions) if the requested grid doesn't fit the face.
    """
    v_positions = calculate_row_v_positions(
        v_length, num_rows, first_row_offset, row_spacing, v_margin)

    _, _, spacing = _row_spacing(u_length, guards_per_row, edge_margin, stagger_rows)
    half_spacing = spacing / 2.0

    positions = []
    for row_index, v in enumerate(v_positions):
        stagger_offset = half_spacing if (stagger_rows and row_index % 2 == 1) else 0.0
        u_positions = calculate_row_u_positions(
            u_length, guards_per_row, edge_margin, stagger_offset,
            reserve_stagger=stagger_rows)
        for u in u_positions:
            positions.append((row_index, u, v))

    return positions
