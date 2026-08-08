import sys, os
_gen  = os.path.join(os.path.dirname(__file__), '..')
_shared = os.path.join(os.path.dirname(__file__), '..', '..', 'shared')
# standing_seam_generator/ too: TestRibPositionMatchesRealPanelSeams (full-
# review finding #14) cross-checks calculate_rib_u_positions() against the
# real standing_seam_geometry panel/seam layout it's meant to sit on top of.
_standing_seam = os.path.join(os.path.dirname(__file__), '..', '..', 'standing_seam_generator')
for _p in (_gen, _shared, _standing_seam):
    if _p not in sys.path:
        sys.path.insert(0, _p)
