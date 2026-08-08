import sys, os
_gen = os.path.join(os.path.dirname(__file__), '..')
_shared = os.path.join(os.path.dirname(__file__), '..', '..', 'shared')
for _p in (_gen, _shared):
    if _p not in sys.path:
        sys.path.insert(0, _p)
