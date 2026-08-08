"""
Quoin Geometry Generator v1.1.0

Generates coordinated corner-column brick definitions for two adjacent
wall faces meeting at a 90-degree exterior corner.

Designed for use alongside BrickGeometry: this module produces the
quoin column for both faces, and BrickGeometry with left_quoin=True
produces the field fill for each face.

Face A is the "primary" face: even courses show a stretcher on Face A
and a header-return on Face B. Odd courses reverse. Either face may be
designated primary; the result differs only by one course of offset.

Usage:
    qg = QuoinGeometry(wall_height=50, brick_width=2.32, brick_height=0.65,
                       brick_depth=1.09, mortar=0.11, bond_type='flemish')
    result = qg.generate()
    # Pass result['face_a_bricks'] to the proxy for Face A.
    # Pass result['face_a_fill_start'] to BrickGeometry(left_quoin=True,
    #     left_quoin_primary=True) so its fill begins after the quoin column.
    # For a right-edge quoin (dual-quoin wall), mirror the same column:
    #     mirror_to_right_edge(result['face_a_bricks'], span=u_length)

Version History:
- 1.1.0: Add mirror_to_right_edge() — lets BrickProxy place the same
         deterministic column at a face's right edge (RightQuoin) without
         reimplementing the topo_eps position math.
- 1.0.0: Initial release.
"""

__version__ = "1.1.0"

import math
import sys
from pathlib import Path
from typing import Dict, List

_bg_path = str(Path(__file__).parent.parent / 'brick_generator')
if _bg_path not in sys.path:
    sys.path.insert(0, _bg_path)

from brick_geometry import BrickDef  # noqa: E402

_TOPO_EPS_FACTOR = 0.1  # fraction of mortar — matches brick_geometry convention


class QuoinGeometry:
    """
    Generates corner-column BrickDefs for a 90-degree exterior corner.

    One brick per course per face, alternating type per course:
      even: Face A = stretcher (brick_width wide), Face B = header-return (brick_depth wide)
      odd:  Face A = header-return,                Face B = stretcher

    fill_start_u[course] tells BrickGeometry(left_quoin=True) where to begin
    the field pattern: quoin_width + mortar for that course.
    """

    def __init__(
        self,
        wall_height: float,
        brick_width: float,
        brick_height: float,
        brick_depth: float,
        mortar: float,
        bond_type: str = 'stretcher',
        skin_depth: float = None,
    ):
        """
        Args:
            wall_height:  Wall height in mm.
            brick_width:  Brick width along the stretcher face (mm).
            brick_height: Brick height (mm).
            brick_depth:  Brick depth / header face width (mm).
            mortar:       Mortar joint thickness (mm).
            bond_type:    'stretcher', 'english', 'flemish', or 'common'.
                          Recorded in metadata; does not change the quoin column.
            skin_depth:   Engraving depth for quoin bricks (mm).
                          Defaults to mortar if not supplied.
        """
        if any(x <= 0 for x in [wall_height, brick_width, brick_height, brick_depth, mortar]):
            raise ValueError("All dimensions must be positive")
        if bond_type.lower() not in ('stretcher', 'english', 'flemish', 'common'):
            raise ValueError(f"Unknown bond type: {bond_type!r}")

        self.wall_height = wall_height
        self.brick_width = brick_width
        self.brick_height = brick_height
        self.brick_depth = brick_depth
        self.mortar = mortar
        self.bond_type = bond_type.lower()
        self.skin_depth = skin_depth if skin_depth is not None else mortar
        self.course_spacing_v = brick_height + mortar
        self.num_courses = math.ceil(wall_height / self.course_spacing_v) + 2
        self._topo_eps = mortar * _TOPO_EPS_FACTOR

    def generate(self) -> Dict:
        """
        Generate quoin column bricks for both faces.

        Returns:
            face_a_bricks       List[BrickDef]  — corner column for Face A
            face_b_bricks       List[BrickDef]  — corner column for Face B
            face_a_fill_start   List[float]     — per-course u-offset for Face A fill
            face_b_fill_start   List[float]     — per-course u-offset for Face B fill
            num_courses         int
            metadata            dict
        """
        eps = self._topo_eps
        face_a_bricks: List[BrickDef] = []
        face_b_bricks: List[BrickDef] = []
        face_a_fill_start: List[float] = []
        face_b_fill_start: List[float] = []

        for course in range(self.num_courses):
            v = course * self.course_spacing_v

            if course % 2 == 0:
                a_type, a_w = 'stretcher', self.brick_width
                b_type, b_w = 'header',    self.brick_depth
            else:
                a_type, a_w = 'header',    self.brick_depth
                b_type, b_w = 'stretcher', self.brick_width

            face_a_bricks.append(BrickDef(
                index=len(face_a_bricks),
                u=-eps, v=v, course=course,
                brick_type=a_type, width=a_w,
                height=self.brick_height, depth=self.skin_depth,
            ))
            face_b_bricks.append(BrickDef(
                index=len(face_b_bricks),
                u=-eps, v=v, course=course,
                brick_type=b_type, width=b_w,
                height=self.brick_height, depth=self.skin_depth,
            ))

            # Fill starts after the quoin brick + one mortar joint.
            # We do not subtract topo_eps here: the fill generator applies
            # its own OCCT boundary handling independently.
            face_a_fill_start.append(a_w + self.mortar)
            face_b_fill_start.append(b_w + self.mortar)

        return {
            'face_a_bricks':     face_a_bricks,
            'face_b_bricks':     face_b_bricks,
            'face_a_fill_start': face_a_fill_start,
            'face_b_fill_start': face_b_fill_start,
            'num_courses':       self.num_courses,
            'metadata': {
                'bond_type':    self.bond_type,
                'num_courses':  self.num_courses,
                'brick_width':  self.brick_width,
                'brick_height': self.brick_height,
                'brick_depth':  self.brick_depth,
                'mortar':       self.mortar,
            },
        }


def mirror_to_right_edge(bricks: List[BrickDef], span: float) -> List[BrickDef]:
    """
    Mirror a left-anchored quoin column (as returned in generate()'s
    face_a_bricks/face_b_bricks) to sit at the right edge of a face segment
    `span` wide instead of the left edge.

    generate() always anchors each brick at u=-topo_eps, i.e. it overlaps the
    true left face edge (u=0) by topo_eps and its inner edge falls topo_eps
    short of the nominal quoin width — the same coincident-boundary-avoidance
    convention BrickGeometry uses elsewhere in this codebase. Mirroring keeps
    that convention on the opposite side: the returned bricks overlap the
    true right edge (u=span) by the same topo_eps, with everything else
    (width, course, brick_type, v) unchanged.

    Used by BrickProxy for RightQuoin (dual-quoin walls spanning two
    corners) — the same deterministic column, just placed at the other end.
    """
    mirrored = []
    for i, bd in enumerate(bricks):
        topo_eps = -bd.u  # generate() always sets u = -topo_eps
        mirrored.append(bd._replace(
            index=i,
            u=span - bd.width + topo_eps,
        ))
    return mirrored
