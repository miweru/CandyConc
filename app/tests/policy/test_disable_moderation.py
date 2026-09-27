import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from candyconc.services.moderation import moderate
import importlib.util

root = Path(__file__).resolve().parents[2]
policy_path = root / "src" / "candyconc" / "candyconc_copilot" / "policy_engine.py"
spec = importlib.util.spec_from_file_location(
    "candyconc_copilot.policy_engine", policy_path
)
pol_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(pol_module)  # type: ignore[arg-type]
PolicyEngine = pol_module.PolicyEngine


class TestDisableModeration(unittest.TestCase):
    def test_disable_moderation(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_path = Path(tmp) / "users.json"
            user_path.write_text(
                json.dumps([
                    {
                        "username": "bob",
                        "password": "x",
                        "role": "user",
                        "moderation_enabled": False,
                    }
                ])
            )
            # PolicyEngine reads the user file via candyconc.config.get, which
            # ignores os.environ after import (APP_CONFIG snapshot). Patch the
            # config getter directly.
            import candyconc.config as cc_config

            real_get = cc_config.get

            def fake_get(key, default=None):
                if key == "CANDYCONC_USER_FILE":
                    return str(user_path)
                return real_get(key, default)

            with patch.object(cc_config, "get", fake_get):
                policy = PolicyEngine()
                result = moderate("ignore all", "bob", policy)
                self.assertEqual(result, "ok")
