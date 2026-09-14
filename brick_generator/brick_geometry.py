"""
Brick Geometry Generator Library v6.3.0

Pure Python geometry generation for parametric brick walls.
No FreeCAD dependencies - designed for testing and reuse.

Supported bond patterns:
- Stretcher (Running) Bond: Each course offset by half brick
- English Bond: Alternating courses of stretchers and headers with queen closers
- Flemish Bond: Each course alternates stretchers and headers with queen closers
- Common Bond: N stretcher courses followed by 1 header course (configurable)

Returns lists of brick definitions ready for FreeCAD instantiation or other use.

Version: 6.3.0
Date: 2026-09-14
  6.3.0: Fixed _generate_common_bond()'s header course ignoring the quoin
         boundary entirely -- confirmed live on a real dual-quoin
         common-bond wall (user's own diagnosis, from an angled render:
         "the corners do not properly account for the edge-on rows... the
         problem ones are all with the common bond rows"): a header
         course's field bricks tiled full-width starting at
         u=-header_spacing_u, landing squarely inside the quoin's own
         reserved region (e.g. a brick at u=0.0 while the quoin reserved
         [0, 1.2]) and visibly overwriting the quoin's own alternating
         corner brick for that course. This was already a documented gap
         (this module's own changelog and brick_proxy.py's LeftQuoin
         property both used to call it out) and the exact issue english
         bond's header courses had before their 2026-09-13 fix -- common
         bond just never got the matching treatment then. Fix: header
         courses now route through _emit_bounded_run with the quoin
         boundary, identically to stretcher courses and english bond's
         header courses, when left_quoin is set; unchanged (unbounded
         full-width tile-and-clip) when it isn't.
  6.2.0: Fixed a missing mortar joint in _emit_bounded_run() -- confirmed
         live on a real dual-face corner (header-quoin course forcing a
         nonzero left closer): the closer landed flush against the quoin
         brick with zero gap, while courses that needed no closer (the
         common case) showed a correct full mortar joint. Root cause: the
         quoin-adjacent call sites pass left_boundary = quoin_fill_start()
         - mortar specifically so _fit_run_between_boundaries' one internal
         mortar reservation lands between the quoin and the first placed
         element -- correct when that element is a regular brick (the
         common case, left_closer == 0), but when it's a closer instead,
         that single reservation was structurally repurposed to sit
         between the closer and the brick run, leaving nothing between the
         quoin's own material and the closer. Fix: when a nonzero left
         closer lands on a quoin boundary, refit against a boundary
         shifted right by one more mortar before placing anything, so the
         quoin-to-closer gap is explicitly reserved rather than silently
         dropped. Affects every quoin-adjacent caller of
         _emit_bounded_run() (stretcher, common, english) uniformly, since
         they all share the same call pattern; flemish's dual-quoin path
         never places a left closer at all (by construction) and is
         unaffected.
  6.1.0: Added topo_eps()/clamp_brick_to_segment() -- the pure-math half of
         a performance fix to brick_proxy.py's _create_mortar_grid, which
         used to boolean-intersect (Part.Shape.common()) every brick
         against face_slab to clip the deliberate overflow this module's
         course generation produces (TOPO_EPS nudges, the +2-course V
         overflow, stretcher bond's plain-path overflow). Measured: 801s
         for one 756-brick wall's mortar cut, vs 2.9s with no boolean
         intersection at all. Since every brick's position is exact
         arithmetic, clipping it to a boundary doesn't need OCCT --
         clamp_brick_to_segment() does it numerically instead, so
         brick_proxy.py's final mortar cut is a plain
         face_slab.cut(brick_compound) with no .common() call at any
         brick count. topo_eps() also consolidates the TOPO_EPS = mortar
         * 0.1 formula that was previously hand-copied at two separate
         call sites in this file into one canonical function. No change
         to course-generation output -- this only affects how the
         resulting overflow gets clipped downstream.
  6.0.0: Dual-quoin (both left_quoin AND right_quoin on one wall) now works
         on every bond type, not just flemish -- confirmed live that any
         multi-wall building has at least one wall needing dual-quoin (a
         middle wall between two real corners), so restricting that to one
         bond was a basic capability gap. Enabled by two bug fixes to
         quoin-adjacent closer sizing, both confirmed live against a real
         building before and after:
         - New _fit_run_between_boundaries()/_emit_bounded_run(), replacing
           the old _calculate_course_layout() (removed -- fully subsumed):
           generalizes its symmetric two-closer algebra to two independent,
           arbitrary boundaries (a quoin's own _quoin_fill_start/_end, not
           just a plain wall edge), bounded to [min_closer, max_closer]
           instead of relying entirely on downstream OCCT clipping.
           Previously stretcher/common/english's quoin-adjacent fill had
           NO closer sizing at all when left_quoin was set (or right_quoin
           standalone, via the mirror trick) -- confirmed live: ~0.27-
           0.36mm slivers on every course of both a demo building's door
           piers. English bond's header courses additionally never
           consulted quoin state at all (a previously-undocumented
           instance of the same gap), now fixed as a side effect of the
           same change.
         - _generate_flemish_bond's dual-quoin closer had a minimum bound
           only, no maximum -- confirmed live: 3.82mm/5.05mm closers
           (bigger than a full 2.32mm stretcher brick) on a real
           28.0276mm wall. A shared-n search bounding both course parities
           together was tried and confirmed ineffective (n only moves in
           whole stretcher+header pairs, a step too coarse to always land
           in a tight window); the actual fix inserts one extra single
           brick per-course when that course's own closer would exceed
           max(S,H)+m, shrinking it by that brick's width+mortar -- a
           half-pair-granularity adjustment the shared-n search can't
           reach. Brought the same real wall's closer down to a uniform
           2.62mm. Documented residual limitation: for some wall-width/
           brick-size combinations the per-step swing between candidate
           brick counts can still exceed any reasonably tight bound with
           no single-brick insertion able to close the gap; the fix falls
           back to the original (larger but still valid) closer rather
           than raising in that case.
  5.2.0: right_quoin no longer requires left_quoin=True or flemish bond --
         a standalone right-edge quoin on any bond is built by generating
         the mirror-image left_quoin problem and reflecting every brick's
         u coordinate (course parity, which drives stretcher/header
         alternation, never depends on u-position, so this is exact, not
         an approximation). The dual-quoin-simultaneously case (both
         left_quoin AND right_quoin on one wall) remains flemish-only --
         that path has real bespoke meet-in-the-middle math in
         _generate_flemish_bond, unlike the standalone case. Also added
         compute_face_axes(), extracted from brick_proxy.py's
         _get_face_coordinate_system() so the u/v-axis derivation used by
         quoin corner detection is pure-Python-testable (surfaced while
         fixing a real gap: a door pier's only real corner landed on its
         *right* edge only, which was previously inexpressible without an
         unwanted second quoin column and a forced bond-pattern change).
  5.1.0: Add face_index_set()/resolve_quoin_flags_for_face()/find_dual_
         listed_faces() -- the per-face quoin-role override resolution
         logic from brick_proxy.py's _face_index_set/_resolve_quoin_flags,
         extracted so it's testable under plain pytest instead of only via
         FreeCAD (full-review finding
         freecad-mr-generators-20260808-a0b9#09). The logic itself was
         already pure Python; only App.Console.PrintWarning tied it to
         FreeCAD, and that call stays in the proxy.
"""

__version__ = "6.3.0"

import math
from typing import List, Dict, Tuple, NamedTuple, Set


class BrickDef(NamedTuple):
    """Represents a single brick in the wall."""
    index: int                    # Sequential brick number
    u: float                      # Position along width (local coords)
    v: float                      # Position along height (local coords)
    course: int                   # Which course (0-indexed from bottom)
    brick_type: str               # 'stretcher' or 'header'
    width: float                  # Brick dimension along U
    height: float                 # Brick dimension along V (always same)
    depth: float                  # Brick dimension perpendicular to wall


# =============================================================================
# Per-face quoin-role override resolution
# =============================================================================
# Pure logic behind brick_proxy.py's LeftQuoinPrimaryFaces/LeftQuoinSecondary
# Faces/RightQuoinPrimaryFaces/RightQuoinSecondaryFaces override properties
# (added alongside the dual-quoin corner-merge feature). A face not listed in
# any override falls back to the object-level LeftQuoin/RightQuoin/*Primary
# booleans unchanged.

def face_index_set(link_sub_list, link_obj) -> Set[int]:
    """Face indices (0-based) referencing *link_obj* within a
    PropertyLinkSubList-shaped value: an iterable of (entry_obj, sub_names)
    pairs, where sub_names is an iterable of strings like "Face3".

    *link_obj* is compared by identity (`is`), matching how FreeCAD's own
    PropertyLinkSubList entries reference document objects -- but this
    function itself has no FreeCAD dependency; any hashable/comparable
    object works as link_obj in a test.
    """
    indices = set()
    for entry_obj, sub_names in link_sub_list:
        if entry_obj is not link_obj:
            continue
        for sub_name in sub_names:
            if sub_name.startswith('Face'):
                indices.add(int(sub_name[4:]) - 1)
    return indices


def find_dual_listed_faces(primary_set: Set[int], secondary_set: Set[int]) -> Set[int]:
    """Faces present in both a Primary and Secondary override set for the
    same side (Left or Right) -- ambiguous; callers resolve these as
    Primary and should warn the user."""
    return primary_set & secondary_set


def resolve_quoin_flags_for_face(
        face_idx: int,
        left_primary: Set[int], left_secondary: Set[int],
        right_primary: Set[int], right_secondary: Set[int],
        default_left_quoin: bool, default_left_primary: bool,
        default_right_quoin: bool, default_right_primary: bool,
) -> Tuple[bool, bool, bool, bool]:
    """Resolve (left_quoin, left_quoin_primary, right_quoin,
    right_quoin_primary) for one face index, honoring the per-face
    override sets ahead of the object-level defaults.

    Returns a 4-tuple of bools.
    """
    if face_idx in left_primary or face_idx in left_secondary:
        left_quoin, left_primary_flag = True, (face_idx in left_primary)
    else:
        left_quoin, left_primary_flag = default_left_quoin, default_left_primary
    if face_idx in right_primary or face_idx in right_secondary:
        right_quoin, right_primary_flag = True, (face_idx in right_primary)
    else:
        right_quoin, right_primary_flag = default_right_quoin, default_right_primary
    return left_quoin, left_primary_flag, right_quoin, right_primary_flag


# =============================================================================
# Face U/V-axis derivation (pure logic, now living in shared/face_geometry.py)
# =============================================================================
# Relocated 2026-09-13 (see that module's docstring for why) since this
# logic is generic face-axis infrastructure, not brick-specific --
# shared/corner_detection.py, and any future clapboard/bead_board/smart_trim
# corner work, needs the same axis derivation. Re-exported here so existing
# `from brick_geometry import compute_face_axes` call sites (and
# brick_proxy.py's `_bg.compute_face_axes` attribute access) keep working
# unchanged.

from face_geometry import compute_face_axes  # noqa: E402,F401


# =============================================================================
# Mortar-grid boundary clamping (pure logic, used by brick_proxy.py's
# _create_mortar_grid)
# =============================================================================
# BrickGeometry deliberately builds bricks that overflow a wall's real
# boundary in several ways (TOPO_EPS nudges, the +2-course V overflow,
# stretcher bond's plain-path overflow -- see _emit_bounded_run/
# _generate_flemish_bond docstrings) so that OCCT's mortar-grid cut never
# sees a brick edge exactly coincident with the wall's own face_slab
# boundary (a real, previously-hit OCCT crash). brick_proxy.py used to
# reconcile this by boolean-intersecting every brick against face_slab
# (Part.Shape.common()) before cutting -- correct, but catastrophically
# slow (measured: 801s for one 756-brick wall) since boolean intersection
# is by far OCCT's most expensive operation at this shape count.
# clamp_brick_to_segment() replaces that: since every brick's position is
# exact, known arithmetic, the same "clip to boundary" question has a
# pure-Python answer that needs no OCCT geometry at all -- brick_proxy.py
# now clamps every BrickDef's numbers to its own segment's bounds before
# building any OCCT solid, so the final mortar cut is a plain
# face_slab.cut(brick_compound) with no boolean-intersection step at any
# brick count.

TOPO_EPS_FACTOR = 0.1


def topo_eps(mortar: float) -> float:
    """The nudge used throughout this module to push a boundary-adjacent
    brick edge past (never exactly onto) a real wall edge, avoiding an
    OCCT coincident-face crash. Single source of truth for this constant
    -- see _emit_bounded_run/_generate_flemish_bond for its original uses,
    and clamp_brick_to_segment below for its newest one."""
    return mortar * TOPO_EPS_FACTOR


def clamp_brick_to_segment(bd: BrickDef, seg_width: float, v_length: float,
                            eps: float):
    """
    Shrink `bd`'s (u, width)/(v, height) to fit within
    [0, seg_width] x [0, v_length], nudging any clamped edge `eps` inward
    (never exactly to the boundary).

    BrickGeometry's course-generation deliberately lets bricks overflow a
    wall's real edge (see this section's own docstring above) on the
    understanding that *something* will clip them back before they reach
    a final OCCT boolean. This is that "something," done analytically
    instead of via an OCCT boolean intersection -- a fully-interior brick
    (the common case) is returned unchanged; only a brick whose (u, v)
    extent actually exceeds the segment's bounds is modified, and only on
    the side(s) that overflow.

    Some generated bricks don't just overflow a boundary -- they land
    ENTIRELY outside it (zero overlap with [0, seg_width] x [0,
    v_length]), not merely poking past one edge. This is expected, not a
    bug in the caller: BrickGeometry's own "+2 extra courses" V-direction
    buffer and stretcher bond's plain-tiling loop tail both deliberately
    over-generate past what a wall could ever use. Clamping such a brick
    would produce a negative-size result (its far edge, once clamped,
    lands before its near edge); there is nothing to clip, so this
    function returns None for it instead -- the caller should drop it
    from the brick list entirely.

    The `eps` inward nudge on a clamped (but still overlapping) edge
    matters for the same reason the overflow existed in the first place:
    landing the clamped edge EXACTLY on the boundary would make it
    exactly coincident with face_slab's own edge in the eventual OCCT cut
    -- precisely the crash this module's TOPO_EPS convention exists to
    avoid (see topo_eps() above). Pass topo_eps(mortar) for `eps` to reuse
    that same convention rather than a second hand-picked value.

    Returns:
        A new BrickDef clamped to the segment, or None if `bd` has zero
        overlap with [0, seg_width] x [0, v_length] (drop it).

    Raises:
        ValueError: `bd` overlaps the segment but clamping still produced
        a non-positive width or height -- the segment is too narrow for
        this brick/mortar combination to ever fit, regardless of clipping
        (a real infeasibility, distinct from the "no overlap at all"
        drop-it case above).
    """
    u0, u1 = bd.u, bd.u + bd.width
    v0, v1 = bd.v, bd.v + bd.height
    if u0 >= seg_width or u1 <= 0 or v0 >= v_length or v1 <= 0:
        return None

    # Each axis is only touched (and its width/height only recomputed via
    # subtraction) if that axis actually overflows -- keeping the untouched
    # axis's original float value exactly, rather than reconstructing it
    # via (end - start) arithmetic that can reintroduce a bit of float
    # noise even when the value doesn't conceptually change.
    new_u, new_width = bd.u, bd.width
    u_start, u_end = bd.u, bd.u + bd.width
    u_changed = False
    if u_start < 0:
        u_start, u_changed = eps, True
    if u_end > seg_width:
        u_end, u_changed = seg_width - eps, True
    if u_changed:
        new_u, new_width = u_start, u_end - u_start

    new_v, new_height = bd.v, bd.height
    v_start, v_end = bd.v, bd.v + bd.height
    v_changed = False
    if v_start < 0:
        v_start, v_changed = eps, True
    if v_end > v_length:
        v_end, v_changed = v_length - eps, True
    if v_changed:
        new_v, new_height = v_start, v_end - v_start

    if new_width <= 0 or new_height <= 0:
        raise ValueError(
            f"clamping brick (u={bd.u:.4f}, width={bd.width:.4f}, "
            f"v={bd.v:.4f}, height={bd.height:.4f}) to segment "
            f"{seg_width:.4f} x {v_length:.4f} produced a non-positive "
            f"size -- segment too narrow for this brick/mortar combination")
    if not u_changed and not v_changed:
        return bd
    return bd._replace(u=new_u, width=new_width, v=new_v, height=new_height)


class BrickGeometry:
    """
    Generates brick wall geometry for a rectangular wall face.
    
    Wall coordinate system:
    - U axis: horizontal (left to right), length u_length
    - V axis: vertical (bottom to top), length v_length
    - Normal: perpendicular to wall (out)
    """
    
    def __init__(self, u_length: float, v_length: float,
                 brick_width: float, brick_height: float, brick_depth: float,
                 mortar: float, bond_type: str = 'stretcher',
                 common_bond_count: int = 5,
                 skin_depth: float = None,
                 left_quoin: bool = False,
                 left_quoin_primary: bool = True,
                 right_quoin: bool = False,
                 right_quoin_primary: bool = True):
        """
        Initialize brick geometry generator.

        Args:
            u_length: Wall width (mm)
            v_length: Wall height (mm)
            brick_width: Brick width along wall (mm) - stretcher orientation
            brick_height: Brick height (always along V) (mm)
            brick_depth: Brick depth (mm) - used for header width calculation
            mortar: Mortar joint thickness (mm)
            bond_type: 'stretcher', 'english', 'flemish', or 'common'
            common_bond_count: For common bond, number of stretcher courses between headers
            skin_depth: Rendered brick depth (mm) - defaults to brick_depth if not specified
            left_quoin: True when a QuoinGeometry column occupies the left edge (u=0).
                        Skips the left closer; fill begins at quoin_width + mortar.
            left_quoin_primary: True = this is Face A (stretcher quoin on even courses).
                                False = this is Face B (header-return quoin on even courses).
                                Ignored when left_quoin=False.
            right_quoin: True when a QuoinGeometry column occupies the right
                        edge (u=u_length). Standalone (left_quoin=False) works on
                        any bond type: generated as the mirror-image left_quoin
                        problem and reflected, since course parity never depends
                        on u-position. Combined with left_quoin=True (a wall
                        spanning two quoin corners) is flemish-only -- the right
                        closer must be shrunk per-course to also clear the right
                        quoin's reserved width, which only _generate_flemish_bond
                        implements.
            right_quoin_primary: True = Face A at the right corner (stretcher quoin
                                on even courses). False = Face B. Ignored when
                                right_quoin=False.
        """
        self.u_length = u_length
        self.v_length = v_length
        self.brick_width = brick_width
        self.brick_height = brick_height
        self.brick_depth = brick_depth
        self.mortar = mortar
        self.bond_type = bond_type.lower()
        self.common_bond_count = common_bond_count
        self.skin_depth = skin_depth if skin_depth is not None else brick_depth
        self.left_quoin = left_quoin
        self.left_quoin_primary = left_quoin_primary
        self.right_quoin = right_quoin
        self.right_quoin_primary = right_quoin_primary

        # Validate inputs
        if any(x <= 0 for x in [u_length, v_length, brick_width, brick_height, brick_depth, mortar]):
            raise ValueError("All dimensions must be positive")

        if self.bond_type not in ['stretcher', 'english', 'flemish', 'common']:
            raise ValueError(f"Unknown bond type: {bond_type}")

        if self.bond_type == 'common' and common_bond_count < 1:
            raise ValueError("common_bond_count must be at least 1")

        # Dual-quoin (both edges quoined on one wall) now works on every
        # bond type: stretcher/common/english route both quoin boundaries
        # through _fit_run_between_boundaries/_emit_bounded_run (their
        # left_quoin branch already computes _quoin_fill_end via
        # right_quoin's own state, needing no special-casing for "both");
        # flemish keeps its bespoke meet-in-the-middle search
        # (_generate_flemish_bond's worst_right_reserve) since its
        # alternating-type structure isn't a fit for the shared
        # single-brick-type helper. Previously flemish-only -- any
        # multi-wall building has at least one wall needing dual-quoin (a
        # middle wall between two real corners), so restricting that to one
        # bond type was a basic capability gap, not an edge case.

        # Pre-calculate spacing
        self.stretcher_spacing_u = brick_width + mortar
        self.header_spacing_u = brick_depth + mortar
        self.course_spacing_v = brick_height + mortar

        # Calculate coverage metrics
        self.num_courses = math.ceil(v_length / self.course_spacing_v) + 2

        # Header width (for bonds that use headers)
        self.header_width = brick_depth
        self.stretcher_width = brick_width

    def _quoin_fill_start(self, course: int) -> float:
        """
        When left_quoin=True, return the u-coordinate where fill begins for
        this course (quoin_width + mortar). Returns 0.0 when left_quoin=False.
        """
        if not self.left_quoin:
            return 0.0
        # Primary face: stretcher quoin on even courses, header-return on odd.
        # Return face: header-return on even, stretcher on odd.
        this_face_is_stretcher = (course % 2 == 0) == self.left_quoin_primary
        quoin_w = self.stretcher_width if this_face_is_stretcher else self.header_width
        return quoin_w + self.mortar

    def _quoin_fill_end(self, course: int) -> float:
        """
        When right_quoin=True, return the u-coordinate where fill must end
        for this course (u_length - quoin_width - mortar). Returns u_length
        when right_quoin=False.

        This is the single source of truth for the right-quoin boundary:
        `_generate_flemish_bond` derives its right closer width
        (`C_right`) directly from this method (`C_right = fill_end - u`)
        rather than recomputing the reserved-width formula inline.
        """
        if not self.right_quoin:
            return self.u_length
        this_face_is_stretcher = (course % 2 == 0) == self.right_quoin_primary
        quoin_w = self.stretcher_width if this_face_is_stretcher else self.header_width
        return self.u_length - quoin_w - self.mortar

    def _fit_run_between_boundaries(
            self, left_boundary: float, right_boundary: float,
            brick_width: float, target_left_closer: float = None,
            max_closer: float = None) -> Tuple[int, float, float]:
        """
        Fit N repeating bricks of one width between two arbitrary boundaries
        (0/u_length for a plain wall edge, or a quoin's _quoin_fill_start/
        _quoin_fill_end for a quoin edge), with a closer at each end.

        Generalizes _calculate_course_layout's symmetric two-closer algebra
        to two independent boundaries -- a dual quoin (both ends quoined) is
        then just "both boundaries happen to be quoin-shaped instead of one
        being a plain wall edge," not a separate problem.

        Layout: left_closer + mortar + [brick + mortar] * n + right_closer
        spans exactly (right_boundary - left_boundary). With
        target_left_closer=None and max_closer=None, this reduces to
        EXACTLY _calculate_course_layout's own search and even split (same
        reduction loop, same floor-at-0 fallback) -- verified by
        TestFitRunBetweenBoundaries's equivalence sweep. That fallback (a
        single n=1 course relying entirely on downstream OCCT clipping) only
        applies when max_closer is None; a bounded caller that hits genuine
        infeasibility raises ValueError instead (see below), matching the
        existing dual-quoin infeasibility precedent rather than silently
        emitting an out-of-bounds closer.

        Args:
            left_boundary, right_boundary: u-coordinates the fill must span
                between (right_boundary > left_boundary).
            brick_width: width of the single repeated brick type.
            target_left_closer: if given, bias the leftover split toward
                this left-closer value (clamped into whatever range keeps
                both closers in bounds) instead of always splitting evenly
                -- lets a caller preserve a course-parity stagger offset
                (e.g. running bond's half-brick alternation) through the
                switch from raw tile-and-clip to bounded fitting.
            max_closer: if given, neither closer may exceed this. When the
                naturally-selected n would produce an oversized closer,
                more brick+mortar pairs are added until both closers fit in
                [min_closer, max_closer], where min_closer = mortar * 2
                (the existing convention). Feasibility requires
                max_closer >= min_closer + (brick_width + mortar) / 2 --
                true by a wide margin for every real brick/mortar ratio;
                raises ValueError on genuine infeasibility (a pathological
                brick/mortar ratio, or a boundary span too narrow for even
                one brick between two bounded closers) rather than emitting
                a closer outside the requested bounds.

        Returns:
            (n_bricks, left_closer, right_closer)
        """
        span = right_boundary - left_boundary
        m = self.mortar
        min_closer = m * 2

        def leftover_for(n):
            return span - n * brick_width - (n + 1) * m

        spacing = brick_width + m
        n = int((span + m) / spacing)
        if n < 1:
            n = 1

        leftover = leftover_for(n)
        while leftover < 2 * min_closer and n > 1:
            n -= 1
            leftover = leftover_for(n)

        if max_closer is not None:
            while leftover > 2 * max_closer:
                n += 1
                leftover = leftover_for(n)
                if leftover < 2 * min_closer:
                    raise ValueError(
                        f"Cannot fit brick_width={brick_width} between "
                        f"boundaries spanning {span:.4f}mm with both "
                        f"closers bounded to [{min_closer:.4f}, "
                        f"{max_closer:.4f}]: no course count satisfies "
                        f"both bounds.")

        if leftover < 0:
            # Unbounded (max_closer=None) narrow-span fallback, matching
            # _calculate_course_layout's own floor-at-0 -- a bounded caller
            # can never reach here (it would have raised above instead).
            leftover = 0
            n = max(n, 1)

        if target_left_closer is None:
            left_closer = leftover / 2.0
        else:
            hi = min(leftover, max_closer) if max_closer is not None else leftover
            lo = max(0.0, leftover - hi)
            if 0 < lo < min_closer:
                # `lo` is the smallest left_closer that keeps right_closer
                # within max_closer -- but a positive value below
                # min_closer is itself a sliver (the exact bug this
                # function exists to prevent). Bumping it up to min_closer
                # is always safe here: leftover >= 2*min_closer is already
                # guaranteed by the reduction loop above, so
                # right_closer = leftover - min_closer >= min_closer too.
                lo = min_closer
            left_closer = min(max(target_left_closer, lo), hi)
        right_closer = leftover - left_closer

        return n, left_closer, right_closer

    def _emit_bounded_run(self, v: float, course: int, left_boundary: float,
                           right_boundary: float, brick_width: float,
                           brick_type: str, left_is_real_edge: bool,
                           right_is_real_edge: bool,
                           target_left_closer: float = 0.0,
                           max_closer: float = None) -> List['BrickDef']:
        """
        Build one course's BrickDefs for a run of `brick_type` bricks
        between two boundaries, via _fit_run_between_boundaries.

        target_left_closer=0.0 (the quoin-adjacent default): never insert a
        closer right at a quoin boundary (a real masonry quoin's own width
        already occupies its edge; a left closer only appears here if
        leftover would otherwise force the right closer past max_closer).
        Callers with two plain (non-quoin) boundaries should pass
        target_left_closer=None for an even split instead.

        max_closer bounds both closers to a whole brick's width by default
        for quoin-adjacent callers (this session's confirmed-live
        oversized-closer bug); plain-wall callers needing bit-for-bit
        equivalence with the old (unbounded) behavior should pass
        max_closer=None explicitly.

        left_is_real_edge/right_is_real_edge: True when that boundary is
        the actual wall edge, not an internal quoin reservation -- nudges
        that closer past the edge by TOPO_EPS (mortar * 0.1, matching
        _generate_flemish_bond's identical convention) so brick_proxy.py's
        mortar-grid cut never sees a boundary face exactly coincident with
        face_slab's.
        """
        n, left_closer, right_closer = self._fit_run_between_boundaries(
            left_boundary, right_boundary, brick_width,
            target_left_closer=target_left_closer, max_closer=max_closer)

        if not left_is_real_edge and left_closer > 0:
            # A left closer landed at a quoin boundary. The single mortar
            # _fit_run_between_boundaries reserves internally sits between
            # the closer and the brick run -- that's the ONLY gap needed
            # when left_closer is 0 (closer absent, so that gap serves as
            # "quoin to first brick"). But a closer that DOES get emitted
            # is real brick material, not a boundary -- it still needs its
            # own mortar joint separating it from the quoin's own material,
            # which nothing above reserves, so the closer was landing flush
            # against the quoin with zero gap (confirmed live: a header-
            # course quoin forcing a nonzero left closer, courses otherwise
            # showing a full mortar joint). Refit against a boundary shifted
            # right by one more mortar to reserve that second, physically
            # required gap, then place everything (closer included) from
            # the shifted boundary instead of the original one.
            left_boundary = left_boundary + self.mortar
            n, left_closer, right_closer = self._fit_run_between_boundaries(
                left_boundary, right_boundary, brick_width,
                target_left_closer=target_left_closer, max_closer=max_closer)

        eps = topo_eps(self.mortar)
        if left_is_real_edge and left_closer > 0:
            left_closer += eps
            left_boundary -= eps
        if right_is_real_edge:
            right_closer += eps

        bricks = []
        u = left_boundary
        if left_closer > 0:
            bricks.append(BrickDef(
                index=0, u=u, v=v, course=course,
                brick_type='closer', width=left_closer,
                height=self.brick_height, depth=self.skin_depth,
            ))
        # Always consume the closer's mortar-gap slot, even when left_closer
        # is exactly 0 (no BrickDef emitted) -- _fit_run_between_boundaries'
        # leftover formula structurally reserves (n+1) mortars regardless of
        # whether the left closer ends up 0 or positive (it can't know in
        # advance which, since target_left_closer is only a bias, not a
        # guarantee). Skipping this advance when left_closer==0 left the
        # whole run exactly one mortar short of right_boundary -- confirmed
        # live via TestStandaloneRightQuoinBoundaryOverflow before this fix.
        u += left_closer + self.mortar
        spacing = brick_width + self.mortar
        for _ in range(n):
            bricks.append(BrickDef(
                index=0, u=u, v=v, course=course,
                brick_type=brick_type, width=brick_width,
                height=self.brick_height, depth=self.skin_depth,
            ))
            u += spacing
        if right_closer > 0:
            bricks.append(BrickDef(
                index=0, u=u, v=v, course=course,
                brick_type='closer', width=right_closer,
                height=self.brick_height, depth=self.skin_depth,
            ))
        return bricks

    def generate(self) -> Dict:
        """
        Generate complete brick layout.
        
        Returns:
            Dictionary with:
                'bricks': List of BrickDef objects
                'metadata': Dict with generation metadata
        """
        if self.right_quoin and not self.left_quoin:
            # No bond method computes a right-edge quoin directly (only
            # _generate_flemish_bond's dual-quoin path references
            # right_quoin at all, and only when left_quoin is also set).
            # Course parity (course % 2, which drives stretcher/header
            # alternation) never depends on u-position, so a standalone
            # right_quoin is exactly the mirror-image left_quoin problem.
            bricks = self._generate_mirrored_right_quoin()
        elif self.bond_type == 'stretcher':
            bricks = self._generate_stretcher_bond()
        elif self.bond_type == 'english':
            bricks = self._generate_english_bond()
        elif self.bond_type == 'flemish':
            bricks = self._generate_flemish_bond()
        elif self.bond_type == 'common':
            bricks = self._generate_common_bond()

        # Add sequential indices
        for i, brick in enumerate(bricks):
            bricks[i] = brick._replace(index=i)
        
        return {
            'bricks': bricks,
            'metadata': {
                'bond_type': self.bond_type,
                'num_courses': self.num_courses,
                'total_bricks': len(bricks),
                'u_length': self.u_length,
                'v_length': self.v_length,
                'brick_width': self.brick_width,
                'brick_height': self.brick_height,
                'brick_depth': self.brick_depth,
                'mortar': self.mortar,
            }
        }

    def _generate_mirrored_right_quoin(self) -> List[BrickDef]:
        """
        Standalone right_quoin (left_quoin=False): build the mirror-image
        left_quoin problem -- same bond, same right_quoin_primary as the
        Primary designation -- then reflect every brick's u coordinate
        across the wall so the quoin column lands at u=u_length instead of
        u=0. Exact, not approximate: course parity (course % 2) drives
        stretcher/header alternation and never depends on u-position, so
        reflection changes nothing about which brick is a stretcher vs a
        header -- only where it sits along the wall.
        """
        mirror = BrickGeometry(
            u_length=self.u_length, v_length=self.v_length,
            brick_width=self.brick_width, brick_height=self.brick_height,
            brick_depth=self.brick_depth, mortar=self.mortar,
            bond_type=self.bond_type, common_bond_count=self.common_bond_count,
            skin_depth=self.skin_depth,
            left_quoin=True, left_quoin_primary=self.right_quoin_primary,
            right_quoin=False,
        )
        mirror_bricks = mirror.generate()['bricks']
        return [
            b._replace(u=self.u_length - b.u - b.width)
            for b in mirror_bricks
        ]

    def _generate_stretcher_bond(self) -> List[BrickDef]:
        """
        Stretcher (Running) Bond.
        Each course offset by half brick width.
        All bricks are stretchers.

        With left_quoin=True (right_quoin can only be True together with
        left_quoin here -- generate()'s dispatch routes a standalone
        right_quoin through the mirror trick before reaching this method):
        the run starts flush after the quoin (target_left_closer=0.0,
        matching the established quoin convention of never inserting a
        closer right at the quoin itself) and is bounded to
        [min_closer, brick_width] via _fit_run_between_boundaries -- for a
        single quoin the far boundary is the real wall edge
        (_quoin_fill_end returns u_length when right_quoin=False); for a
        dual quoin it's the second quoin's own boundary. No plain-wall
        behavior change: without any quoin this still overflows both edges
        for OCCT to clip, exactly as before.
        """
        bricks = []

        for course in range(self.num_courses):
            v = course * self.course_spacing_v

            if self.left_quoin:
                # _quoin_fill_start already includes the mortar gap after
                # the quoin; subtract it back out since _emit_bounded_run's
                # own leftover formula unconditionally reserves that same
                # gap (whether or not a left closer ends up emitted) --
                # passing quoin_fill_start directly double-counts it and
                # leaves the whole run one mortar short of right_boundary
                # (confirmed live via TestStandaloneRightQuoinBoundaryOverflow).
                bricks.extend(self._emit_bounded_run(
                    v, course, self._quoin_fill_start(course) - self.mortar,
                    self._quoin_fill_end(course), self.brick_width,
                    'stretcher', left_is_real_edge=False,
                    right_is_real_edge=not self.right_quoin,
                    max_closer=self.brick_width))
                continue

            offset = (self.stretcher_spacing_u / 2) if (course % 2) else 0
            u = offset - self.stretcher_spacing_u  # Start before wall edge

            while u < self.u_length + self.stretcher_spacing_u:
                bricks.append(BrickDef(
                    index=0,
                    u=u, v=v,
                    course=course,
                    brick_type='stretcher',
                    width=self.brick_width,
                    height=self.brick_height,
                    depth=self.skin_depth,
                ))
                u += self.stretcher_spacing_u

        return bricks

    def _generate_english_bond(self) -> List[BrickDef]:
        """
        English Bond with proper queen closers.

        Pattern:
        - Stretcher courses: closer + stretchers + closer
        - Header courses: closer + headers + closer (offset so headers center over stretcher joints)

        The closers ensure the pattern fits exactly within the wall width.
        Headers are positioned to center over the joints between stretchers below.

        With left_quoin: both stretcher AND header courses are bounded
        between the quoin and the far boundary via _fit_run_between_boundaries
        (previously only stretcher courses had ANY quoin awareness at all --
        header courses ignored left_quoin/right_quoin entirely, a
        previously-undocumented gap fixed here as a side effect of the same
        change). Without any quoin, both course types keep their previous
        (unbounded, symmetric two-closer) behavior -- verified equivalent to
        the old _calculate_course_layout-based computation.
        """
        bricks = []

        for course in range(self.num_courses):
            v = course * self.course_spacing_v
            is_header_course = (course % 2) == 1
            width = self.header_width if is_header_course else self.stretcher_width
            brick_type = 'header' if is_header_course else 'stretcher'

            if self.left_quoin:
                # See _generate_stretcher_bond's comment on the same
                # -self.mortar adjustment.
                bricks.extend(self._emit_bounded_run(
                    v, course, self._quoin_fill_start(course) - self.mortar,
                    self._quoin_fill_end(course), width, brick_type,
                    left_is_real_edge=False, right_is_real_edge=not self.right_quoin,
                    max_closer=width))
            else:
                bricks.extend(self._emit_bounded_run(
                    v, course, 0.0, self.u_length, width, brick_type,
                    left_is_real_edge=True, right_is_real_edge=True,
                    target_left_closer=None, max_closer=None))

        return bricks

    def _generate_flemish_bond(self) -> List[BrickDef]:
        """
        Flemish Bond with queen closers.

        Without left_quoin:
          Even: C0 + S + H + S + ... + S + C0   (n+1 stretchers, n headers)
          Odd:  C1 + H + S + H + ... + H + C1   (n+1 headers,   n stretchers)
          C1 = C0 + (S - H) / 2  ensures both sum to W.

        With left_quoin only:
          The quoin column (external) occupies [0, quoin_width] on every course.
          The fill starts at quoin_width + mortar with the brick type opposite the
          quoin type for that course:
            quoin=S → fill leads with H: H m S m H m ... + C_right
            quoin=H → fill leads with S: S m H m S m ... + C_right
          Algebraically, C_right = W - (n+1)(S + H + 2m) regardless of course
          parity or which face is primary, so n and C_right are uniform.

        With left_quoin AND right_quoin (a wall spanning two quoin corners):
          The alternating run itself is identical to the left_quoin-only case —
          n is still chosen the same way, just with the search additionally
          required to leave room for the LARGER of the two possible right-quoin
          widths (max(S, H) + m), so it stays feasible for both course parities.
          The right closer then shrinks per-course by the actual right quoin's
          reserved width for that course (S or H, per right_quoin_primary),
          landing exactly on the right quoin's edge instead of the real wall
          edge. n stays uniform; only the closer width varies by course.
        """
        bricks = []
        S = self.stretcher_width
        H = self.header_width
        m = self.mortar
        W = self.u_length
        min_closer = m * 2
        TOPO_EPS = topo_eps(m)

        if self.left_quoin:
            # Quoin handles the left edge; the right edge is either the real
            # wall edge (right_quoin=False) or a second quoin column
            # (right_quoin=True) — both are a single closer computed against
            # a (possibly quoin-shrunk) right boundary.
            n = None
            base_C = None
            worst_right_reserve = (max(S, H) + m) if self.right_quoin else 0.0
            for test_n in range(100):
                test_C = W - (test_n + 1) * (S + H + 2 * m)
                if (test_C - worst_right_reserve) >= min_closer:
                    n = test_n
                    base_C = test_C
                else:
                    break

            if n is None:
                if self.right_quoin:
                    # Unlike the left-quoin-only fallback below, an infeasible
                    # fit here can't be papered over by overflow-clipping
                    # against the real wall edge — the right boundary is an
                    # internal quoin reservation, not a face edge. Fail loudly
                    # instead of emitting a brick that overlaps the right quoin.
                    raise ValueError(
                        f"u_length={W:.4f} is too narrow for a flemish "
                        f"dual-quoin fill (brick_width={S}, brick_depth={H}, "
                        f"mortar={m}): no course fits even one brick between "
                        f"both quoins.")
                # Left-quoin-only: preserve pre-existing fallback (a single
                # brick, relying on downstream overflow-clip against the real
                # wall edge — same as the non-quoin generators' behavior).
                n, base_C = 0, 0.0

            for course in range(self.num_courses):
                v = course * self.course_spacing_v
                # Primary face: S quoin on even → fill leads with H; H quoin on odd → S.
                # Return face: reversed parity.
                this_face_is_stretcher = (course % 2 == 0) == self.left_quoin_primary
                if this_face_is_stretcher:
                    u = S + m          # fill starts after stretcher quoin
                    first_type = 'header'
                    first_w, other_type, other_w = H, 'stretcher', S
                else:
                    u = H + m          # fill starts after header-return quoin
                    first_type = 'stretcher'
                    first_w, other_type, other_w = S, 'header', H

                # Pattern: first_type (m other_type m first_type) * n  m  C_right
                for i in range(n + 1):
                    bricks.append(BrickDef(0, u, v, course,
                                           first_type, first_w,
                                           self.brick_height, self.skin_depth))
                    u += first_w + m
                    if i < n:
                        bricks.append(BrickDef(0, u, v, course,
                                               other_type, other_w,
                                               self.brick_height, self.skin_depth))
                        u += other_w + m

                if self.right_quoin:
                    # Single source of truth for the right-quoin boundary:
                    # derive the closer width from _quoin_fill_end (u-coordinate
                    # where fill must stop) rather than re-deriving the reserved
                    # width inline. Verified equal to the prior inline formula
                    # (base_C - R - m) across course parities and primary/W
                    # combinations before this refactor landed.
                    C_right = self._quoin_fill_end(course) - u

                    # Bound the closer's upper size: without this, C_right
                    # can end up bigger than a full stretcher brick (3.82mm/
                    # 5.05mm confirmed live on a real 28.0276mm wall with
                    # brick_width=2.32) -- n is shared across both course
                    # parities (by design, for a uniform alternating count),
                    # but each parity's ACTUAL reservation varies with its
                    # own quoin width, so the leftover this shared n produces
                    # isn't itself bounded. Rather than search for a
                    # different global n (tried and confirmed ineffective --
                    # n only moves in whole stretcher+header PAIRS, a step
                    # of S+H+2m, which can jump straight over any reasonably
                    # tight window), insert ONE more single `other_type`
                    # brick on just this course when its own closer is
                    # oversized, shrinking it by that brick's own width -- a
                    # half-pair-granularity adjustment the shared-n search
                    # can't reach. Skipped if it would drop the closer below
                    # min_closer (a genuinely narrow case where the plain
                    # oversized closer is the only valid option).
                    if C_right > max(S, H) + m:
                        shrunk = C_right - (other_w + m)
                        if shrunk >= min_closer:
                            bricks.append(BrickDef(0, u, v, course,
                                                   other_type, other_w,
                                                   self.brick_height, self.skin_depth))
                            u += other_w + m
                            C_right = shrunk
                else:
                    C_right = base_C + TOPO_EPS  # push right edge slightly past wall boundary

                if C_right > 0:
                    bricks.append(BrickDef(0, u, v, course,
                                           'closer', C_right,
                                           self.brick_height, self.skin_depth))

        else:
            # Standard two-sided closer layout.
            n = 0
            C0 = 0.0
            for test_n in range(100):
                num_mortars = 2 * (test_n + 1)
                test_C0 = (W - (test_n + 1) * S - test_n * H - num_mortars * m) / 2
                if test_C0 >= min_closer:
                    n = test_n
                    C0 = test_C0
                else:
                    break

            C1 = C0 + (S - H) / 2
            C0 += TOPO_EPS
            C1 += TOPO_EPS

            for course in range(self.num_courses):
                v = course * self.course_spacing_v
                is_odd = (course % 2) == 1
                u = -TOPO_EPS

                if is_odd:
                    # C1 + H + S + H + ... + H + C1
                    if C1 > 0:
                        bricks.append(BrickDef(0, u, v, course, 'closer', C1,
                                               self.brick_height, self.skin_depth))
                        u += C1 + m
                    for i in range(n + 1):
                        bricks.append(BrickDef(0, u, v, course, 'header', H,
                                               self.brick_height, self.skin_depth))
                        u += H + m
                        if i < n:
                            bricks.append(BrickDef(0, u, v, course, 'stretcher', S,
                                                   self.brick_height, self.skin_depth))
                            u += S + m
                    if C1 > 0:
                        bricks.append(BrickDef(0, u, v, course, 'closer', C1,
                                               self.brick_height, self.skin_depth))
                else:
                    # C0 + S + H + S + ... + S + C0
                    if C0 > 0:
                        bricks.append(BrickDef(0, u, v, course, 'closer', C0,
                                               self.brick_height, self.skin_depth))
                        u += C0 + m
                    for i in range(n + 1):
                        bricks.append(BrickDef(0, u, v, course, 'stretcher', S,
                                               self.brick_height, self.skin_depth))
                        u += S + m
                        if i < n:
                            bricks.append(BrickDef(0, u, v, course, 'header', H,
                                                   self.brick_height, self.skin_depth))
                            u += H + m
                    if C0 > 0:
                        bricks.append(BrickDef(0, u, v, course, 'closer', C0,
                                               self.brick_height, self.skin_depth))

        return bricks
    
    def _generate_common_bond(self) -> List[BrickDef]:
        """
        Common Bond: N stretcher courses then 1 header course, repeating.
        N = self.common_bond_count.

        With left_quoin: both stretcher AND header courses are bounded
        between the quoin and the far boundary via _fit_run_between_
        boundaries (same convention as _generate_stretcher_bond/
        _generate_english_bond's own header courses). Header courses
        previously ran full-width regardless of quoin state -- confirmed
        live (2026-09-14, a real dual-quoin common-bond wall): at every
        header course, field bricks starting at u=-header_spacing_u landed
        squarely inside the quoin's own reserved region (e.g. quoin
        reserving [0, 1.2] while a header brick occupied [0.0, 1.09]),
        visibly overwriting the quoin's own alternating corner brick for
        that course with a plain full-width header row instead. This was
        the exact, already-documented gap english bond's header courses
        had before their own 2026-09-13 fix (see _generate_english_bond's
        docstring) -- common bond just never got the same treatment then.
        Without any quoin, header courses keep their previous (unbounded,
        full-width tile-and-clip) behavior unchanged.
        """
        bricks = []
        course = 0

        while course < self.num_courses:
            # Stretcher courses
            for _ in range(self.common_bond_count):
                if course >= self.num_courses:
                    break
                v = course * self.course_spacing_v
                if self.left_quoin:
                    # See _generate_stretcher_bond's comment on the same
                    # -self.mortar adjustment.
                    bricks.extend(self._emit_bounded_run(
                        v, course, self._quoin_fill_start(course) - self.mortar,
                        self._quoin_fill_end(course), self.brick_width,
                        'stretcher', left_is_real_edge=False,
                        right_is_real_edge=not self.right_quoin,
                        max_closer=self.brick_width))
                    course += 1
                    continue
                offset = (self.stretcher_spacing_u / 2) if (course % 2) else 0
                u = offset - self.stretcher_spacing_u
                while u < self.u_length + self.stretcher_spacing_u:
                    bricks.append(BrickDef(
                        index=0, u=u, v=v, course=course,
                        brick_type='stretcher',
                        width=self.brick_width,
                        height=self.brick_height,
                        depth=self.skin_depth,
                    ))
                    u += self.stretcher_spacing_u
                course += 1

            # Header course
            if course < self.num_courses:
                v = course * self.course_spacing_v
                if self.left_quoin:
                    # See _generate_stretcher_bond's comment on the same
                    # -self.mortar adjustment.
                    bricks.extend(self._emit_bounded_run(
                        v, course, self._quoin_fill_start(course) - self.mortar,
                        self._quoin_fill_end(course), self.brick_depth,
                        'header', left_is_real_edge=False,
                        right_is_real_edge=not self.right_quoin,
                        max_closer=self.brick_depth))
                else:
                    u = -self.header_spacing_u
                    while u < self.u_length + self.header_spacing_u:
                        bricks.append(BrickDef(
                            index=0, u=u, v=v, course=course,
                            brick_type='header',
                            width=self.brick_depth,
                            height=self.brick_height,
                            depth=self.skin_depth,
                        ))
                        u += self.header_spacing_u
                course += 1

        return bricks
