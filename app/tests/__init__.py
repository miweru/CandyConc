import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# RBAC OFF by default for the general test suite. Packaged/deploy defaults are
# fail-closed release defaults, so tests opt into local dev explicitly unless a
# security test overrides the mode itself.
# Pre-r7 this was "1" but inert (the old config read APP_CONFIG, not os.environ);
# the r7 config-precedence fix (env > toml) made it live and 401'd ~96 open-access
# tests. Security/RBAC tests enable RBAC explicitly themselves.
os.environ.setdefault("CANDYCONC_ENABLE_RBAC", "0")
os.environ.setdefault("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
os.environ.setdefault("COPILOT_ENDPOINT", "http://test")
os.environ.setdefault("COPILOT_API_KEY", "lm-studio")
os.environ.setdefault("CANDYCONC_EMB_BACKEND", "jina")
