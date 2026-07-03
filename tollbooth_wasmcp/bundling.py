"""Pre-init helpers that adapt the tollbooth-dpyc wheel to componentize-py's
frozen snapshot.

- ``force_bundle_wheel`` imports every ``tollbooth.*`` submodule so componentize-py
  (which only snapshots modules imported before the freeze) bundles the lazily-
  imported ``tools/*``, ``pricing``, etc. Natives (coincurve) fail and are skipped.
- ``install_version_shim`` pins ``importlib.metadata.version("tollbooth-dpyc")`` to
  the value resolvable at pre-init, since the frozen runtime can't scan the
  filesystem for ``.dist-info`` and would otherwise report ``"unknown"``.
"""

import importlib
import importlib.metadata as _ilm
import os as _os
import pkgutil

WHEEL = "tollbooth-dpyc"
_WHEEL_DIST = WHEEL.replace("-", "_")


def force_bundle_wheel():
    import tollbooth as _tb
    for _m in pkgutil.walk_packages(_tb.__path__, _tb.__name__ + "."):
        try:
            importlib.import_module(_m.name)
        except Exception:
            pass


def _resolve_wheel_version():
    try:
        return _ilm.version(WHEEL)
    except Exception:
        import glob
        import sys as _sys
        for _d in _sys.path:
            for _p in glob.glob(_os.path.join(_d, f"{_WHEEL_DIST}-*.dist-info")):
                base = _os.path.basename(_p)
                return base[len(_WHEEL_DIST) + 1:-len(".dist-info")]
    return "unknown"


def install_version_shim():
    version = _resolve_wheel_version()
    orig = _ilm.version
    _ilm.version = lambda name: version if name == WHEEL else orig(name)
    return version
