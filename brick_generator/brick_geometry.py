"""
Brick Geometry Generator Library v5.0.2

Pure Python geometry generation for parametric brick walls.
No FreeCAD dependencies - designed for testing and reuse.

Supported bond patterns:
- Stretcher (Running) Bond: Each course offset by half brick
- English Bond: Alternating courses of stretchers and headers with queen closers
- Flemish Bond: Each course alternates stretchers and headers with queen closers
- Common Bond: N stretcher courses followed by 1 header course (configurable)

Returns lists of brick definitions ready for FreeCAD instantiation or other use.

Version: 5.0.1
Date: 2025-12-31
"""

__version__ = "5.0.2"

import math
from typing import List, Dict, Tuple, NamedTuple


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
            right_quoin: True when a second QuoinGeometry column occupies the right
                        edge (u=u_length) — for a wall that spans between two quoin
                        corners. Requires left_quoin=True and bond_type='flemish';
                        the right closer is shrunk per-course to also clear the
                        right quoin's reserved width instead of landing on the
                        real wall edge.
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

        if self.right_quoin and not self.left_quoin:
            raise ValueError("right_quoin requires left_quoin=True (dual-quoin walls only)")

        if self.right_quoin and self.bond_type != 'flemish':
            raise ValueError("right_quoin is only implemented for flemish bond")
        
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
        """
        if not self.right_quoin:
            return self.u_length
        this_face_is_stretcher = (course % 2 == 0) == self.right_quoin_primary
        quoin_w = self.stretcher_width if this_face_is_stretcher else self.header_width
        return self.u_length - quoin_w - self.mortar

    def get_quoin_reservation_defs(self) -> List[BrickDef]:
        """
        One BrickDef per course per active quoin side, covering the
        reserved-but-unfilled zone that left_quoin/right_quoin deliberately
        leave blank ([0, _quoin_fill_start(course)) and/or
        [_quoin_fill_end(course), u_length)).

        These are not real bricks — brick_type is 'quoin_reserved'. They
        exist so a consumer building a mortar-cut exclusion volume (e.g.
        BrickProxy's mortar-grid construction) can keep this zone out of
        the mortar cut entirely, leaving it flush at the skin-depth recess
        plane instead of carved down to mortar depth like an ordinary gap
        — ready for a later quoin-column engraving pass (QuoinProxy) to
        carve its own, independent mortar joints into flush material.
        Without this, the reserved zone would already read as "all mortar"
        by the time QuoinProxy runs, and a boolean cut can only remove
        material, never restore what BrickProxy's own mortar grid already
        took away.

        Only meaningful for flemish bond with left_quoin and/or right_quoin
        active; returns [] otherwise (including for non-flemish bonds,
        which don't support right_quoin and don't need this for left_quoin
        either — their reserved zone is only ever adjacent to a real quoin
        column that the caller is responsible for coordinating directly).
        """
        if not (self.left_quoin or self.right_quoin):
            return []
        m = self.mortar
        W = self.u_length
        TOPO_EPS = m * 0.1
        defs = []
        for course in range(self.num_courses):
            v = course * self.course_spacing_v
            if self.left_quoin:
                boundary = self._quoin_fill_start(course)
                defs.append(BrickDef(
                    index=0, u=-TOPO_EPS, v=v, course=course,
                    brick_type='quoin_reserved', width=boundary + TOPO_EPS,
                    height=self.brick_height, depth=self.skin_depth,
                ))
            if self.right_quoin:
                boundary = self._quoin_fill_end(course)
                defs.append(BrickDef(
                    index=0, u=boundary, v=v, course=course,
                    brick_type='quoin_reserved', width=(W - boundary) + TOPO_EPS,
                    height=self.brick_height, depth=self.skin_depth,
                ))
        return defs

    def _calculate_course_layout(self, wall_width: float, brick_width: float) -> Tuple[int, float]:
        """
        Calculate how many whole bricks fit in a course and the closer width needed.

        For a wall of given width, calculates how many whole bricks fit and what
        size queen closer bricks are needed at each end to fill the remaining space.

        Args:
            wall_width: Width of the wall (mm)
            brick_width: Width of the brick type being laid (stretcher or header width)

        Returns:
            Tuple of (n_whole_bricks, closer_width)
            - n_whole_bricks: Number of full-size bricks in the middle
            - closer_width: Width of queen closer bricks at each end (same on both sides)
        """
        spacing = brick_width + self.mortar

        # Calculate whole bricks that fit
        # Layout: closer + mortar + [brick + mortar] * n + closer
        # wall_width = 2 * closer + mortar + n * (brick + mortar)
        # Solving for n: n = (wall_width - 2*closer - mortar) / spacing

        # Start by seeing how many whole bricks fit if we use the remaining space for closers
        n_bricks = int((wall_width + self.mortar) / spacing)
        if n_bricks < 1:
            n_bricks = 1

        # Width used by whole bricks with mortar between them
        used_width = n_bricks * brick_width + (n_bricks - 1) * self.mortar

        # Leftover space for closers (split between both ends)
        # We need mortar on each side of the closer too
        leftover = wall_width - used_width - 2 * self.mortar
        closer_width = leftover / 2.0

        # If closer would be negative or very small, reduce brick count
        min_closer = self.mortar * 2  # Minimum practical closer width
        while closer_width < min_closer and n_bricks > 1:
            n_bricks -= 1
            used_width = n_bricks * brick_width + (n_bricks - 1) * self.mortar
            leftover = wall_width - used_width - 2 * self.mortar
            closer_width = leftover / 2.0

        # Ensure closer is at least 0
        if closer_width < 0:
            closer_width = 0

        return (n_bricks, closer_width)
        
    def generate(self) -> Dict:
        """
        Generate complete brick layout.
        
        Returns:
            Dictionary with:
                'bricks': List of BrickDef objects
                'metadata': Dict with generation metadata
        """
        if self.bond_type == 'stretcher':
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
    
    def _generate_stretcher_bond(self) -> List[BrickDef]:
        """
        Stretcher (Running) Bond.
        Each course offset by half brick width.
        All bricks are stretchers.

        With left_quoin=True the quoin column occupies [0, quoin_width]; fill
        tiles from quoin_width + mortar rightward, overflowing the right edge
        for OCCT to clip.
        """
        bricks = []

        for course in range(self.num_courses):
            v = course * self.course_spacing_v

            if self.left_quoin:
                u = self._quoin_fill_start(course)
            else:
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
        """
        bricks = []

        # Calculate layouts for both course types
        n_stretchers, stretcher_closer = self._calculate_course_layout(
            self.u_length, self.stretcher_width
        )
        n_headers, header_closer = self._calculate_course_layout(
            self.u_length, self.header_width
        )

        # TOPO_EPS: same coincident-face overflow fix as _generate_flemish_bond.
        # English bond closers also sum exactly to wall width; add a small overflow
        # so common() in _create_mortar_grid never sees coincident boundary faces.
        TOPO_EPS = self.mortar * 0.1
        stretcher_closer += TOPO_EPS
        header_closer += TOPO_EPS

        for course in range(self.num_courses):
            v = course * self.course_spacing_v
            is_header_course = (course % 2) == 1

            if is_header_course:
                # Header course
                # Layout: closer + mortar + header + mortar + ... + header + mortar + closer

                u = -TOPO_EPS  # start slightly before left wall edge

                # Left closer (if any)
                if header_closer > 0:
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='closer',
                        width=header_closer,
                        height=self.brick_height,
                        depth=self.skin_depth  # Same surface depth as stretchers
                    )
                    bricks.append(brick)
                    u += header_closer + self.mortar

                # Full headers
                for i in range(n_headers):
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='header',
                        width=self.header_width,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)
                    u += self.header_width + self.mortar

                # Right closer (if any)
                if header_closer > 0:
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='closer',
                        width=header_closer,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)

            else:
                # Stretcher course.
                # With left_quoin: skip left closer; tile from quoin edge rightward.
                if self.left_quoin:
                    u = self._quoin_fill_start(course)
                    while u < self.u_length + self.stretcher_spacing_u:
                        bricks.append(BrickDef(
                            index=0, u=u, v=v, course=course,
                            brick_type='stretcher',
                            width=self.stretcher_width,
                            height=self.brick_height,
                            depth=self.skin_depth,
                        ))
                        u += self.stretcher_spacing_u
                else:
                    u = -TOPO_EPS
                    if stretcher_closer > 0:
                        bricks.append(BrickDef(
                            index=0, u=u, v=v, course=course,
                            brick_type='closer', width=stretcher_closer,
                            height=self.brick_height, depth=self.skin_depth,
                        ))
                        u += stretcher_closer + self.mortar
                    for i in range(n_stretchers):
                        bricks.append(BrickDef(
                            index=0, u=u, v=v, course=course,
                            brick_type='stretcher', width=self.stretcher_width,
                            height=self.brick_height, depth=self.skin_depth,
                        ))
                        u += self.stretcher_width + self.mortar
                    if stretcher_closer > 0:
                        bricks.append(BrickDef(
                            index=0, u=u, v=v, course=course,
                            brick_type='closer', width=stretcher_closer,
                            height=self.brick_height, depth=self.skin_depth,
                        ))

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
        TOPO_EPS = m * 0.1

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
                    right_is_stretcher = (course % 2 == 0) == self.right_quoin_primary
                    R = S if right_is_stretcher else H
                    C_right = base_C - R - m
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

        With left_quoin: stretcher courses start from the quoin fill offset;
        header courses run full-width (quoin treatment for header courses is
        deferred to a future version).
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
                    u = self._quoin_fill_start(course)
                else:
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

            # Header course — no quoin treatment (full-width tile-and-clip)
            if course < self.num_courses:
                v = course * self.course_spacing_v
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
