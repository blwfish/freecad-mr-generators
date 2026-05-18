"""
boundary_assertions — shared pytest helpers for boundary-overflow invariants.

Background
----------
Several generators in this repo fill a bounded region of a roof/wall face by
placing geometric elements (bricks, boards, beads, panels, shingles, slates)
and then trimming the union with an OCCT `common()` Boolean against a slab
extruded from the face.

OCCT has a well-known failure mode when Boolean operations are given geometry
whose boundary faces are *exactly coincident* with the clip slab's boundary
faces: the BRep builder segfaults inside the C++ layer (no Python exception,
no traceback — FreeCAD returns to the shell prompt).

The robust fix is to design the placed geometry so its bounding extent
strictly overflows the face boundary on both sides — even by a fraction of a
mortar joint is enough.  Then `common()` always has clean non-coincident
geometry to clip and the segfault never triggers.

The single assertion in this module captures the invariant:

    For every face boundary that the generator fills against, the union of
    placed elements must start STRICTLY BEFORE the lower bound and end
    STRICTLY AFTER the upper bound — never exactly on it.

This is a pure-Python check that runs in microseconds and catches the bug
before OCCT is ever invoked.
"""

from typing import Iterable, Callable, Tuple, Any


def assert_overflows_boundary(
    elements: Iterable[Any],
    lo: float,
    hi: float,
    get_extent: Callable[[Any], Tuple[float, float]],
    eps: float = 1e-6,
    direction: str = 'both',
    label: str = '',
) -> None:
    """Assert that placed elements strictly overflow the [lo, hi] boundary.

    Args:
        elements: iterable of placed elements (bricks, boards, panels, …)
        lo: lower bound of the face along the axis under test
        hi: upper bound of the face along the axis under test
        get_extent: callable(element) -> (start, end) along the axis
        eps: tolerance — overflow must exceed `eps` to count
        direction: 'both' (default), 'left' (only lo), or 'right' (only hi)
        label: descriptive prefix for the assertion message

    Raises:
        AssertionError: if no element starts < lo - eps (left check) or no
            element ends > hi + eps (right check).  The assertion message
            names the OCCT segfault risk so future readers know why this
            invariant matters.
    """
    extents = [get_extent(e) for e in elements]
    if not extents:
        raise AssertionError(
            f"{label}no elements produced — cannot verify boundary overflow "
            f"against [{lo}, {hi}]"
        )

    min_start = min(t[0] for t in extents)
    max_end = max(t[1] for t in extents)

    if direction in ('both', 'left'):
        assert min_start < lo - eps, (
            f"{label}left boundary not overflowed: min element start = "
            f"{min_start:.6f}, need < {lo} - {eps} = {lo - eps:.6f}. "
            f"Exact-coincident boundary faces crash OCCT common() — "
            f"placed elements must extend strictly past the face edge."
        )

    if direction in ('both', 'right'):
        assert max_end > hi + eps, (
            f"{label}right boundary not overflowed: max element end = "
            f"{max_end:.6f}, need > {hi} + {eps} = {hi + eps:.6f}. "
            f"Exact-coincident boundary faces crash OCCT common() — "
            f"placed elements must extend strictly past the face edge."
        )


def assert_no_boundary_coincidence(
    elements: Iterable[Any],
    lo: float,
    hi: float,
    get_extent: Callable[[Any], Tuple[float, float]],
    eps: float = 1e-4,
    label: str = '',
) -> None:
    """Assert no element edge lands within `eps` of the [lo, hi] boundary.

    This is the WEAKER form of the boundary invariant, suitable for sparse
    placement patterns (e.g. bead-board gaps) where elements don't tile the
    entire wall and most gaps stop well inside the boundary.  The crash
    condition is only triggered when an individual element edge falls
    *exactly* on the boundary — so we check each element's edges
    independently rather than demanding overflow of the whole union.

    For tiling patterns (bricks, boards) use the stronger
    `assert_overflows_boundary` instead.

    Args:
        elements: iterable of placed elements
        lo, hi: boundary values
        get_extent: callable(element) -> (start, end)
        eps: forbidden zone width on each side of each boundary
        label: descriptive prefix for the assertion message

    Raises:
        AssertionError: if any element has an edge within `eps` of `lo` or `hi`.
    """
    bad = []
    for elem in elements:
        s, e = get_extent(elem)
        for boundary_name, boundary_val in (('lo', lo), ('hi', hi)):
            if abs(s - boundary_val) < eps:
                bad.append((elem, 'start', s, boundary_name, boundary_val))
            if abs(e - boundary_val) < eps:
                bad.append((elem, 'end', e, boundary_name, boundary_val))

    if bad:
        msg = f"{label}{len(bad)} element edge(s) within {eps} of boundary:\n"
        for elem, side, val, bname, bval in bad[:5]:
            msg += f"  {side}={val:.6f} ≈ {bname}={bval} on element {elem}\n"
        if len(bad) > 5:
            msg += f"  ... and {len(bad) - 5} more\n"
        msg += "OCCT common() segfaults on coincident boundary faces."
        raise AssertionError(msg)
