import unittest
import importlib.util
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[2]

pol_path = root / "src" / "candyconc" / "candyconc_copilot" / "policy_engine.py"
spec = importlib.util.spec_from_file_location(
    "candyconc_copilot.policy_engine", pol_path
)
pol_module = importlib.util.module_from_spec(spec)
metrics_path = root / "src" / "candyconc" / "services" / "backend" / "metrics.py"
metrics_spec = importlib.util.spec_from_file_location(
    "candyconc.services.backend.metrics", metrics_path
)
metrics_mod = importlib.util.module_from_spec(metrics_spec)
assert metrics_spec and metrics_spec.loader
metrics_spec.loader.exec_module(metrics_mod)  # type: ignore[arg-type]
sys.modules["candyconc.services.backend.metrics"] = metrics_mod
backend_pkg = sys.modules.setdefault("candyconc.services.backend", types.ModuleType("candyconc.services.backend"))
setattr(backend_pkg, "metrics", metrics_mod)
assert spec and spec.loader
spec.loader.exec_module(pol_module)  # type: ignore[arg-type]
PolicyEngine = pol_module.PolicyEngine
metrics = metrics_mod


class TestTokenUsage(unittest.TestCase):
    def setUp(self) -> None:
        metrics.reset()

    def test_usage_increments(self) -> None:
        policy = PolicyEngine(token_budget=10)
        start = metrics.get_token_usage()
        policy.check("user", "dummy", 2)
        self.assertEqual(policy.tokens_used, 2)
        self.assertEqual(metrics.get_token_usage(), start + 2)
        policy.check("user", "dummy", 3)
        self.assertEqual(policy.tokens_used, 5)
        self.assertEqual(metrics.get_token_usage(), start + 5)


if __name__ == "__main__":
    unittest.main()
