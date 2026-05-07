"""pytest path setup — makes shingle_geometry and roof_geometry importable."""
import sys
import os

_tests_dir    = os.path.dirname(__file__)
_generator_dir  = os.path.dirname(_tests_dir)
_shared_dir   = os.path.join(os.path.dirname(_generator_dir), '_shared')

for _p in [_generator_dir, _shared_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
