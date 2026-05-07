"""
Brick Geometry Generator Library v5.0.1

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

__version__ = "5.0.1"

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
                 skin_depth: float = None):
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
        
        # Validate inputs
        if any(x <= 0 for x in [u_length, v_length, brick_width, brick_height, brick_depth, mortar]):
            raise ValueError("All dimensions must be positive")
        
        if self.bond_type not in ['stretcher', 'english', 'flemish', 'common']:
            raise ValueError(f"Unknown bond type: {bond_type}")
        
        if self.bond_type == 'common' and common_bond_count < 1:
            raise ValueError("common_bond_count must be at least 1")
        
        # Pre-calculate spacing
        self.stretcher_spacing_u = brick_width + mortar
        self.header_spacing_u = brick_depth + mortar
        self.course_spacing_v = brick_height + mortar

        # Calculate coverage metrics
        self.num_courses = math.ceil(v_length / self.course_spacing_v) + 2

        # Header width (for bonds that use headers)
        self.header_width = brick_depth
        self.stretcher_width = brick_width

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
        """
        bricks = []
        
        for course in range(self.num_courses):
            v = course * self.course_spacing_v
            
            # Offset alternating courses by half stretcher width
            offset = (self.stretcher_spacing_u / 2) if (course % 2) else 0
            
            u = offset - self.stretcher_spacing_u  # Start before wall edge
            
            while u < self.u_length + self.stretcher_spacing_u:
                brick = BrickDef(
                    index=0,  # Will be filled in by generate()
                    u=u,
                    v=v,
                    course=course,
                    brick_type='stretcher',
                    width=self.brick_width,
                    height=self.brick_height,
                    depth=self.skin_depth
                )
                bricks.append(brick)
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

        for course in range(self.num_courses):
            v = course * self.course_spacing_v
            is_header_course = (course % 2) == 1

            if is_header_course:
                # Header course
                # Layout: closer + mortar + header + mortar + ... + header + mortar + closer

                u = 0.0

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
                # Stretcher course
                # Layout: closer + mortar + stretcher + mortar + ... + stretcher + mortar + closer

                u = 0.0

                # Left closer (if any)
                if stretcher_closer > 0:
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='closer',
                        width=stretcher_closer,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)
                    u += stretcher_closer + self.mortar

                # Full stretchers
                for i in range(n_stretchers):
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='stretcher',
                        width=self.stretcher_width,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)
                    u += self.stretcher_width + self.mortar

                # Right closer (if any)
                if stretcher_closer > 0:
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='closer',
                        width=stretcher_closer,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)

        return bricks
    
    def _generate_flemish_bond(self) -> List[BrickDef]:
        """
        Flemish Bond with proper queen closers.

        Pattern:
        - Even courses: C0 + S + H + S + H + ... + S + C0 (n+1 stretchers, n headers)
        - Odd courses:  C1 + H + S + H + S + ... + H + C1 (n+1 headers, n stretchers)

        The closer widths differ between even and odd courses to ensure both
        total to the same wall width while maintaining proper alignment:
        C1 = C0 + (stretcher_width - header_width) / 2

        This offset ensures headers center over stretchers in the course below.
        """
        bricks = []

        S = self.stretcher_width
        H = self.header_width
        m = self.mortar
        W = self.u_length

        # Calculate n (number of headers in even course = number of stretchers in odd course)
        # Even course: C0 + m + S + m + H + m + S + ... + S + m + C0
        #            = 2*C0 + (n+1)*S + n*H + 2*(n+1)*m
        # (there are n+1 stretchers, n headers, and mortar after each brick = 2*(n+1) mortars)
        # Solve for n, trying to maximize n while keeping C0 reasonable

        min_closer = m * 2  # Minimum practical closer width
        n = 0
        C0 = 0

        # Find largest n that gives a valid C0
        for test_n in range(100):
            # 2*C0 + (n+1)*S + n*H + 2*(n+1)*m = W
            # C0 = (W - (n+1)*S - n*H - 2*(n+1)*m) / 2
            num_mortars = 2 * (test_n + 1)
            test_C0 = (W - (test_n + 1) * S - test_n * H - num_mortars * m) / 2
            if test_C0 >= min_closer:
                n = test_n
                C0 = test_C0
            else:
                break

        # Odd course closer is offset
        C1 = C0 + (S - H) / 2

        for course in range(self.num_courses):
            v = course * self.course_spacing_v
            is_odd = (course % 2) == 1
            u = 0.0

            if is_odd:
                # Odd course: C1 + H + S + H + S + ... + H + C1
                # (n+1) headers, n stretchers

                # Left closer
                if C1 > 0:
                    brick = BrickDef(
                        index=0, u=u, v=v, course=course,
                        brick_type='closer',
                        width=C1,
                        height=self.brick_height,
                        depth=self.skin_depth  # Same surface depth as stretchers
                    )
                    bricks.append(brick)
                    u += C1 + m

                # Alternating H + S pairs, ending with H
                for i in range(n + 1):
                    # Header
                    brick = BrickDef(
                        index=0, u=u, v=v, course=course,
                        brick_type='header',
                        width=H,
                        height=self.brick_height,
                        depth=self.skin_depth  # Same surface depth for flat wall
                    )
                    bricks.append(brick)
                    u += H + m

                    # Stretcher (except after last header)
                    if i < n:
                        brick = BrickDef(
                            index=0, u=u, v=v, course=course,
                            brick_type='stretcher',
                            width=S,
                            height=self.brick_height,
                            depth=self.skin_depth
                        )
                        bricks.append(brick)
                        u += S + m

                # Right closer
                if C1 > 0:
                    brick = BrickDef(
                        index=0, u=u, v=v, course=course,
                        brick_type='closer',
                        width=C1,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)

            else:
                # Even course: C0 + S + H + S + H + ... + S + C0
                # (n+1) stretchers, n headers

                # Left closer
                if C0 > 0:
                    brick = BrickDef(
                        index=0, u=u, v=v, course=course,
                        brick_type='closer',
                        width=C0,
                        height=self.brick_height,
                        depth=self.skin_depth  # Stretcher depth
                    )
                    bricks.append(brick)
                    u += C0 + m

                # Alternating S + H pairs, ending with S
                for i in range(n + 1):
                    # Stretcher
                    brick = BrickDef(
                        index=0, u=u, v=v, course=course,
                        brick_type='stretcher',
                        width=S,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)
                    u += S + m

                    # Header (except after last stretcher)
                    if i < n:
                        brick = BrickDef(
                            index=0, u=u, v=v, course=course,
                            brick_type='header',
                            width=H,
                            height=self.brick_height,
                            depth=self.skin_depth
                        )
                        bricks.append(brick)
                        u += H + m

                # Right closer
                if C0 > 0:
                    brick = BrickDef(
                        index=0, u=u, v=v, course=course,
                        brick_type='closer',
                        width=C0,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)

        return bricks
    
    def _generate_common_bond(self) -> List[BrickDef]:
        """
        Common Bond.
        N stretcher courses followed by 1 header course, repeating.
        N = self.common_bond_count
        """
        bricks = []
        course = 0
        
        while course < self.num_courses:
            # Generate stretcher courses
            for _ in range(self.common_bond_count):
                if course >= self.num_courses:
                    break
                
                v = course * self.course_spacing_v
                
                # Offset alternating stretcher courses by half width
                offset = (self.stretcher_spacing_u / 2) if (_ % 2) else 0
                u = offset - self.stretcher_spacing_u
                
                while u < self.u_length + self.stretcher_spacing_u:
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='stretcher',
                        width=self.brick_width,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)
                    u += self.stretcher_spacing_u
                
                course += 1
            
            # Generate header course
            if course < self.num_courses:
                v = course * self.course_spacing_v
                u = -self.header_spacing_u
                
                while u < self.u_length + self.header_spacing_u:
                    brick = BrickDef(
                        index=0,
                        u=u,
                        v=v,
                        course=course,
                        brick_type='header',
                        width=self.brick_depth,
                        height=self.brick_height,
                        depth=self.skin_depth
                    )
                    bricks.append(brick)
                    u += self.header_spacing_u
                
                course += 1
        
        return bricks
