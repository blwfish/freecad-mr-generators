"""Tests for standing seam geometry library."""

import pytest
import math
from standing_seam_geometry import (
    validate_parameters,
    calculate_panel_layout,
    generate_panel_profile,
    get_roof_coordinate_system,
    is_planar,
    calculate_face_bounds,
    find_eave_and_ridge_vertices,
)


# ---------------------------------------------------------------------------
# validate_parameters
# ---------------------------------------------------------------------------

class TestValidateParameters:
    def test_valid_ho_defaults(self):
        ok, errs = validate_parameters(3.0, 0.35, 0.4, 0.15)
        assert ok
        assert errs == []

    def test_zero_panel_width(self):
        ok, errs = validate_parameters(0.0, 0.35, 0.4, 0.15)
        assert not ok
        assert any('panel_width' in e for e in errs)

    def test_negative_panel_width(self):
        ok, errs = validate_parameters(-1.0, 0.35, 0.4, 0.15)
        assert not ok

    def test_zero_seam_height(self):
        ok, errs = validate_parameters(3.0, 0.0, 0.4, 0.15)
        assert not ok
        assert any('seam_height' in e for e in errs)

    def test_zero_seam_width(self):
        ok, errs = validate_parameters(3.0, 0.35, 0.0, 0.15)
        assert not ok
        assert any('seam_width' in e for e in errs)

    def test_zero_panel_thickness(self):
        ok, errs = validate_parameters(3.0, 0.35, 0.4, 0.0)
        assert not ok
        assert any('panel_thickness' in e for e in errs)

    def test_seam_width_equals_panel_width(self):
        ok, errs = validate_parameters(3.0, 0.35, 3.0, 0.15)
        assert not ok
        assert any('seam_width' in e for e in errs)

    def test_seam_width_greater_than_panel_width(self):
        ok, errs = validate_parameters(3.0, 0.35, 4.0, 0.15)
        assert not ok

    def test_panel_thickness_equals_seam_height(self):
        ok, errs = validate_parameters(3.0, 0.35, 0.4, 0.35)
        assert not ok
        assert any('panel_thickness' in e for e in errs)

    def test_panel_thickness_greater_than_seam_height(self):
        ok, errs = validate_parameters(3.0, 0.35, 0.4, 0.5)
        assert not ok

    def test_multiple_errors_reported(self):
        ok, errs = validate_parameters(-1.0, 0.0, 0.4, 0.15)
        assert not ok
        assert len(errs) >= 2

    def test_minimal_valid(self):
        ok, errs = validate_parameters(1.0, 0.5, 0.1, 0.1)
        assert ok

    def test_large_scale_values(self):
        # N scale: narrower panels
        ok, errs = validate_parameters(1.5, 0.2, 0.2, 0.08)
        assert ok


# ---------------------------------------------------------------------------
# calculate_panel_layout
# ---------------------------------------------------------------------------

class TestCalculatePanelLayout:
    def test_exact_multiple(self):
        result = calculate_panel_layout(12.0, 3.0)
        assert result['num_panels'] >= 4  # at least ceiling(12/3)
        assert result['start_u'] == -3.0

    def test_non_multiple_rounds_up(self):
        # 10mm face, 3mm panels → 4 panels needed, should get ≥4 + buffer
        result = calculate_panel_layout(10.0, 3.0)
        assert result['num_panels'] >= 4

    def test_start_u_is_negative_panel_width(self):
        result = calculate_panel_layout(20.0, 4.0)
        assert result['start_u'] == -4.0

    def test_full_coverage(self):
        # panels starting at start_u and spaced panel_width apart must cover [0, face_width]
        panel_width = 3.0
        face_width = 17.5
        result = calculate_panel_layout(face_width, panel_width)
        last_start = result['start_u'] + (result['num_panels'] - 1) * panel_width
        assert last_start >= face_width  # last panel extends past right edge

    def test_very_narrow_face(self):
        result = calculate_panel_layout(0.5, 3.0)
        assert result['num_panels'] >= 1

    def test_face_width_exactly_one_panel(self):
        result = calculate_panel_layout(3.0, 3.0)
        assert result['num_panels'] >= 1

    def test_wide_face(self):
        result = calculate_panel_layout(100.0, 3.0)
        # ceil(100/3)=34, +2 = 36
        assert result['num_panels'] >= 36


# ---------------------------------------------------------------------------
# generate_panel_profile
# ---------------------------------------------------------------------------

class TestGeneratePanelProfile:
    def test_returns_six_points(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        assert len(pts) == 6

    def test_first_point_at_origin(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        assert pts[0] == (0.0, 0.0)

    def test_bottom_right_at_panel_width(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        u, z = pts[1]
        assert abs(u - 3.0) < 1e-9
        assert abs(z) < 1e-9

    def test_seam_top_right_at_seam_height(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        u, z = pts[2]
        assert abs(u - 3.0) < 1e-9
        assert abs(z - 0.35) < 1e-9

    def test_seam_top_left_at_flat_width(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        fw = 3.0 - 0.4  # flat_width = panel_width - seam_width
        u, z = pts[3]
        assert abs(u - fw) < 1e-9
        assert abs(z - 0.35) < 1e-9

    def test_flat_top_right(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        fw = 3.0 - 0.4
        u, z = pts[4]
        assert abs(u - fw) < 1e-9
        assert abs(z - 0.15) < 1e-9

    def test_flat_top_left_at_origin_u(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        u, z = pts[5]
        assert abs(u) < 1e-9
        assert abs(z - 0.15) < 1e-9

    def test_all_u_coords_in_range(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        for u, z in pts:
            assert -1e-9 <= u <= 3.0 + 1e-9

    def test_all_z_coords_non_negative(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        for u, z in pts:
            assert z >= -1e-9

    def test_seam_top_higher_than_panel_top(self):
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        seam_z = pts[2][1]
        panel_z = pts[5][1]
        assert seam_z > panel_z

    def test_profile_forms_closed_polygon_when_repeated(self):
        # The profile is intended to be closed by connecting last to first
        pts = generate_panel_profile(3.0, 0.35, 0.4, 0.15)
        # Check no two adjacent points are identical (would fail Part.makeLine)
        for i in range(len(pts)):
            a = pts[i]
            b = pts[(i + 1) % len(pts)]
            dist = math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)
            assert dist > 1e-6, f"points {i} and {(i+1)%len(pts)} are coincident"

    def test_different_seam_widths_change_flat_width(self):
        pts_narrow = generate_panel_profile(3.0, 0.35, 0.2, 0.15)
        pts_wide   = generate_panel_profile(3.0, 0.35, 0.6, 0.15)
        # seam top-left U = flat_width = panel_width - seam_width
        fw_narrow = pts_narrow[3][0]
        fw_wide   = pts_wide[3][0]
        assert fw_narrow > fw_wide


# ---------------------------------------------------------------------------
# Shared geometry sanity checks (re-exported from roof_geometry)
# ---------------------------------------------------------------------------

class TestSharedGeometryReexports:
    def test_is_planar_flat_roof(self):
        verts = [(0,0,0), (10,0,0), (10,10,0), (0,10,0)]
        assert is_planar(verts)

    def test_is_planar_non_planar(self):
        verts = [(0,0,0), (10,0,0), (10,10,1), (0,10,0)]
        assert not is_planar(verts)

    def test_calculate_face_bounds_simple(self):
        verts = [(0,0,0), (10,0,0), (10,10,5), (0,10,5)]
        bounds = calculate_face_bounds(verts)
        assert bounds['z_min'] == 0.0
        assert bounds['z_max'] == 5.0

    def test_find_eave_vertices_gable(self):
        verts = [(0,0,0), (20,0,0), (20,10,10), (0,10,10)]
        result = find_eave_and_ridge_vertices(verts)
        for v in result['eave_vertices']:
            assert v[2] == 0.0
        for v in result['ridge_vertices']:
            assert v[2] == 10.0

    def test_coordinate_system_gable_face(self):
        # Simple gable: slopes up from z=0 to z=10 over y=0..10
        verts = [(0,0,0), (20,0,0), (20,10,10), (0,10,10)]
        normal = (0.0, -1/math.sqrt(2), 1/math.sqrt(2))
        cs = get_roof_coordinate_system(verts, normal)
        # V should point upslope (increasing Z)
        assert cs['v_vec'][2] > 0

    def test_coordinate_system_gable_right_face(self):
        # Hip face: slopes up diagonally, previously triggered the zero dot-product bug
        verts = [(50,0,50), (50,100,50), (100,100,0), (100,0,0)]
        n_raw = (1.0, 0.0, 1.0)
        mag = math.sqrt(2)
        normal = (n_raw[0]/mag, n_raw[1]/mag, n_raw[2]/mag)
        cs = get_roof_coordinate_system(verts, normal)
        assert cs['v_vec'][2] > 0, "V should point upslope (positive Z)"

    def test_coordinate_system_u_perpendicular_to_v(self):
        verts = [(0,0,0), (20,0,0), (20,10,10), (0,10,10)]
        normal = (0.0, -1/math.sqrt(2), 1/math.sqrt(2))
        cs = get_roof_coordinate_system(verts, normal)
        dot = sum(cs['u_vec'][i]*cs['v_vec'][i] for i in range(3))
        assert abs(dot) < 1e-6

    def test_coordinate_system_u_perpendicular_to_normal(self):
        verts = [(0,0,0), (20,0,0), (20,10,10), (0,10,10)]
        normal = (0.0, -1/math.sqrt(2), 1/math.sqrt(2))
        cs = get_roof_coordinate_system(verts, normal)
        dot = sum(cs['u_vec'][i]*cs['normal'][i] for i in range(3))
        assert abs(dot) < 1e-6
