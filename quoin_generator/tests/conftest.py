import sys, os
_gen    = os.path.join(os.path.dirname(__file__), '..')
_brick  = os.path.join(os.path.dirname(__file__), '..', '..', 'brick_generator')
_shared = os.path.join(os.path.dirname(__file__), '..', '..', 'shared')
for _p in (_gen, _brick, _shared):
    if _p not in sys.path:
        sys.path.insert(0, _p)
