import sys, os
_shared = os.path.join(os.path.dirname(__file__), '..')
if _shared not in sys.path:
    sys.path.insert(0, _shared)
