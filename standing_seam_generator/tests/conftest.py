import os
import sys

_tests_dir = os.path.dirname(__file__)
_generator_dir = os.path.dirname(_tests_dir)
_repo_root = os.path.dirname(os.path.dirname(_generator_dir))
_shared_dir = os.path.join(_repo_root, 'shared')

for _p in [_generator_dir, _shared_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
