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
