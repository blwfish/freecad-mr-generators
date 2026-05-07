"""
Radial Brick Geometry Generator Library v1.0.0

Pure Python geometry generation for parametric brick patterns on cylindrical
and conical surfaces. No FreeCAD dependencies - designed for testing and reuse.

Generates running bond brick layout for surfaces of revolution, returning
brick definitions ready for FreeCAD instantiation.

Primary use cases: smokestacks, water towers, silos, grain elevators.

Version: 1.0.0
Date: 2025-01-01
"""

import math
from typing import List, Dict, Tuple, NamedTuple, Callable, Optional


class RadialBrickDef(NamedTuple):
    """Represents a single brick on a radial (cylindrical/conical) surface."""
    index: int                    # Sequential brick number
    course: int                   # Course number (0-indexed from bottom)
    brick_in_course: int          # Brick position within course (0-indexed)
    z: float                      # Z position (bottom of brick)
    angle_start: float            # Start angle in radians
    angle_end: float              # End angle in radians
    radius: float                 # Radius at this Z position
    height: float                 # Brick height (always same)
    thickness: float              # Brick thickness (radial depth)
    is_concave: bool              # True for inner surface, False for outer


class RadialBrickGeometry:
    """
    Generates brick layout for cylindrical or conical surfaces.

    Coordinate system:
    - Z axis: vertical (bottom to top)
    - Radius: distance from Z axis
    - Angle: rotation around Z axis (radians, 0 = +X direction)

    For conical surfaces, radius varies linearly with Z.
    """

    # Default tolerance for axis alignment check (degrees from vertical)
    DEFAULT_AXIS_TOLERANCE_DEG = 15.0

    # Minimum bricks per course (warning threshold)
    MIN_BRICKS_PER_COURSE = 8

    def __init__(self,
                 z_min: float,
                 z_max: float,
                 radius_at_z_min: float,
                 radius_at_z_max: float,
                 brick_length: float,
                 brick_height: float,
                 brick_thickness: float,
                 mortar_thickness: float,
                 is_concave: bool = False,
                 bond_offset: float = 0.5):
        """
        Initialize radial brick geometry generator.

        Args:
            z_min: Bottom Z coordinate of the surface
            z_max: Top Z coordinate of the surface
            radius_at_z_min: Radius at z_min (for cylinder, same as radius_at_z_max)
            radius_at_z_max: Radius at z_max (for cylinder, same as radius_at_z_min)
            brick_length: Brick length along circumference (mm)
            brick_height: Brick height along Z (mm)
            brick_thickness: Brick thickness radially (mm)
            mortar_thickness: Average mortar joint thickness (mm)
            is_concave: True for inner surface (faces inward), False for outer
            bond_offset: Offset ratio for running bond (0.5 = half brick)
        """
        self.z_min = z_min
        self.z_max = z_max
        self.radius_at_z_min = radius_at_z_min
        self.radius_at_z_max = radius_at_z_max
        self.brick_length = brick_length
        self.brick_height = brick_height
        self.brick_thickness = brick_thickness
        self.mortar_thickness = mortar_thickness
        self.is_concave = is_concave
        self.bond_offset = bond_offset

        # Validate inputs
        self._validate_inputs()

        # Pre-calculate derived values
        self.surface_height = z_max - z_min
        self.course_spacing = brick_height + mortar_thickness
        self.num_courses = max(1, int(self.surface_height / self.course_spacing))

        # Taper calculation: how much radius changes per unit Z
        self.taper_rate = (radius_at_z_max - radius_at_z_min) / self.surface_height if self.surface_height > 0 else 0

    def _validate_inputs(self):
        """Validate all input parameters."""
        # Check positive dimensions
        if self.z_max <= self.z_min:
            raise ValueError(f"z_max ({self.z_max}) must be greater than z_min ({self.z_min})")

        if any(x <= 0 for x in [self.radius_at_z_min, self.radius_at_z_max,
                                 self.brick_length, self.brick_height,
                                 self.brick_thickness, self.mortar_thickness]):
            raise ValueError("All dimensions must be positive")

        if not (0 <= self.bond_offset <= 1):
            raise ValueError(f"bond_offset must be between 0 and 1, got {self.bond_offset}")

        # Check minimum radius constraint
        min_radius = min(self.radius_at_z_min, self.radius_at_z_max)
        min_circumference = 2 * math.pi * min_radius
        brick_with_mortar = self.brick_length + self.mortar_thickness
        min_bricks = int(min_circumference / brick_with_mortar)

        if min_bricks < self.MIN_BRICKS_PER_COURSE:
            raise ValueError(
                f"Radius too small: minimum circumference ({min_circumference:.2f}) "
                f"only fits {min_bricks} bricks per course. "
                f"Minimum recommended is {self.MIN_BRICKS_PER_COURSE}."
            )

    def radius_at_z(self, z: float) -> float:
        """
        Calculate radius at a given Z position.

        For cylinders, returns constant radius.
        For cones, linearly interpolates between z_min and z_max radii.

        Args:
            z: Z position

        Returns:
            Radius at that Z position
        """
        if z <= self.z_min:
            return self.radius_at_z_min
        if z >= self.z_max:
            return self.radius_at_z_max

        # Linear interpolation
        t = (z - self.z_min) / self.surface_height
        return self.radius_at_z_min + t * (self.radius_at_z_max - self.radius_at_z_min)

    def _calculate_bricks_per_course(self, radius: float) -> Tuple[int, float]:
        """
        Calculate number of bricks that fit around circumference at given radius.

        Returns:
            Tuple of (brick_count, angle_per_brick_radians)
        """
        circumference = 2 * math.pi * radius
        brick_with_mortar = self.brick_length + self.mortar_thickness

        # Use integer number of bricks to ensure clean wrap-around
        num_bricks = max(1, int(circumference / brick_with_mortar))

        # Calculate actual angle per brick (slightly adjusted for clean fit)
        angle_per_brick = 2 * math.pi / num_bricks

        return num_bricks, angle_per_brick

    def generate(self) -> Dict:
        """
        Generate complete radial brick layout.

        Returns:
            Dictionary with:
                'bricks': List of RadialBrickDef objects
                'metadata': Dict with generation metadata
        """
        bricks = []
        total_bricks_per_course = []

        for course in range(self.num_courses):
            z = self.z_min + course * self.course_spacing
            radius = self.radius_at_z(z)

            num_bricks, angle_per_brick = self._calculate_bricks_per_course(radius)
            total_bricks_per_course.append(num_bricks)

            # Running bond offset for odd courses
            start_offset = 0.0
            if course % 2 == 1:
                start_offset = angle_per_brick * self.bond_offset

            for brick_num in range(num_bricks):
                angle_start = start_offset + brick_num * angle_per_brick
                angle_end = angle_start + angle_per_brick

                # Normalize angles to [0, 2*pi)
                angle_start = angle_start % (2 * math.pi)
                angle_end = angle_end % (2 * math.pi)

                # Handle wrap-around case
                if angle_end < angle_start:
                    angle_end += 2 * math.pi

                brick = RadialBrickDef(
                    index=0,  # Will be filled in below
                    course=course,
                    brick_in_course=brick_num,
                    z=z,
                    angle_start=angle_start,
                    angle_end=angle_end,
                    radius=radius,
                    height=self.brick_height,
                    thickness=self.brick_thickness,
                    is_concave=self.is_concave
                )
                bricks.append(brick)

        # Assign sequential indices
        for i, brick in enumerate(bricks):
            bricks[i] = brick._replace(index=i)

        # Calculate metadata
        avg_bricks_per_course = sum(total_bricks_per_course) / len(total_bricks_per_course) if total_bricks_per_course else 0

        return {
            'bricks': bricks,
            'metadata': {
                'num_courses': self.num_courses,
                'total_bricks': len(bricks),
                'avg_bricks_per_course': avg_bricks_per_course,
                'min_bricks_per_course': min(total_bricks_per_course) if total_bricks_per_course else 0,
                'max_bricks_per_course': max(total_bricks_per_course) if total_bricks_per_course else 0,
                'z_min': self.z_min,
                'z_max': self.z_max,
                'radius_at_z_min': self.radius_at_z_min,
                'radius_at_z_max': self.radius_at_z_max,
                'surface_height': self.surface_height,
                'brick_length': self.brick_length,
                'brick_height': self.brick_height,
                'brick_thickness': self.brick_thickness,
                'mortar_thickness': self.mortar_thickness,
                'is_concave': self.is_concave,
                'bond_offset': self.bond_offset,
                'is_tapered': self.radius_at_z_min != self.radius_at_z_max,
            }
        }

    def get_brick_vertices(self, brick: RadialBrickDef) -> List[Tuple[float, float, float]]:
        """
        Calculate the 8 vertices of a brick in 3D space.

        For outer (convex) surfaces, bricks project outward.
        For inner (concave) surfaces, bricks project inward.

        Args:
            brick: RadialBrickDef defining the brick

        Returns:
            List of 8 (x, y, z) tuples defining brick vertices.
            Order: bottom-inner-start, bottom-inner-end, bottom-outer-end, bottom-outer-start,
                   top-inner-start, top-inner-end, top-outer-end, top-outer-start
        """
        z_bottom = brick.z
        z_top = brick.z + brick.height

        # Calculate radii for inner and outer faces
        if brick.is_concave:
            # Concave: brick projects inward
            r_outer = brick.radius
            r_inner = brick.radius - brick.thickness
        else:
            # Convex: brick projects outward
            r_inner = brick.radius
            r_outer = brick.radius + brick.thickness

        # Get angles
        a_start = brick.angle_start
        a_end = brick.angle_end

        # Calculate 8 vertices
        # Bottom face (z_bottom)
        v0 = (r_inner * math.cos(a_start), r_inner * math.sin(a_start), z_bottom)  # inner-start
        v1 = (r_inner * math.cos(a_end), r_inner * math.sin(a_end), z_bottom)      # inner-end
        v2 = (r_outer * math.cos(a_end), r_outer * math.sin(a_end), z_bottom)      # outer-end
        v3 = (r_outer * math.cos(a_start), r_outer * math.sin(a_start), z_bottom)  # outer-start

        # Top face (z_top) - same pattern
        v4 = (r_inner * math.cos(a_start), r_inner * math.sin(a_start), z_top)
        v5 = (r_inner * math.cos(a_end), r_inner * math.sin(a_end), z_top)
        v6 = (r_outer * math.cos(a_end), r_outer * math.sin(a_end), z_top)
        v7 = (r_outer * math.cos(a_start), r_outer * math.sin(a_start), z_top)

        return [v0, v1, v2, v3, v4, v5, v6, v7]

    def get_outer_face_vertices(self, brick: RadialBrickDef) -> List[Tuple[float, float, float]]:
        """
        Get the 4 vertices of the visible outer face of a brick.

        This is the face that would be visible on the exterior of a smokestack
        (or interior for concave surfaces).

        Args:
            brick: RadialBrickDef defining the brick

        Returns:
            List of 4 (x, y, z) tuples: bottom-start, bottom-end, top-end, top-start
        """
        vertices = self.get_brick_vertices(brick)

        if brick.is_concave:
            # For concave, the "visible" face is at r_inner (indices 0,1,5,4)
            return [vertices[0], vertices[1], vertices[5], vertices[4]]
        else:
            # For convex, the visible face is at r_outer (indices 3,2,6,7)
            return [vertices[3], vertices[2], vertices[6], vertices[7]]
