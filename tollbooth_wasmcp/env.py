"""Refresh os.environ at call time from the channels that cross the wasmcp
composition boundary.

componentize-py freezes os.environ in the pre-init snapshot, so runtime config
(the operator nsec, the bridge URL) must be re-read on each call from the live
WASI environment (``spin up --env``) and Spin variables (wasi:config/store).

``CONFIG_TO_ENV`` maps DPYC-standard Spin variable names → the env-var names the
tollbooth-dpyc wheel reads. It is host-standard; operators do not change it.
"""

import os

CONFIG_TO_ENV = {
    "operator_nsec": "TOLLBOOTH_NOSTR_OPERATOR_NSEC",
    "bridge_url": "BRIDGE_URL",
}


def sync_os_environ():
    """Populate os.environ from Spin variables and the live WASI environment.
    Both sources are optional; whichever is present wins (env last)."""
    try:
        from wit_world.imports import store as _spin_config  # wasi:config/store
        for cfg_key, env_key in CONFIG_TO_ENV.items():
            try:
                val = _spin_config.get(cfg_key)
                if val:
                    os.environ[env_key] = val
            except Exception:
                pass
    except Exception:
        pass
    try:
        from wit_world.imports import environment as _wasi_environment  # wasi:cli/environment
        for k, v in _wasi_environment.get_environment():
            os.environ[k] = v
    except Exception:
        pass
