import unittest
import importlib.util
import sys
import types
from pathlib import Path

from tests.ai._sysmod_guard import preserve_sys_modules  # noqa: E402

root = Path(__file__).resolve().parents[2]

# load real PolicyEngine module bypassing stubs.  All production-name
# sys.modules entries (and the backend package's ``metrics`` attribute) are
# restored afterwards so no other test module observes the private copies
# (cross-directory isolation: tests/backend patches dotted candyconc paths).
_MISSING = object()
with preserve_sys_modules(
    (
        "candyconc.project",
        "candyconc.services.backend",
        "candyconc.services.backend.metrics",
    )
):
    pol_path = root / "src" / "candyconc" / "candyconc_copilot" / "policy_engine.py"
    spec = importlib.util.spec_from_file_location(
        "candyconc_copilot.policy_engine", pol_path
    )
    pol_module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("candyconc.project", type("x", (), {"Project": object}))
    metrics_path = root / "src" / "candyconc" / "services" / "backend" / "metrics.py"
    metrics_spec = importlib.util.spec_from_file_location(
        "candyconc.services.backend.metrics", metrics_path
    )
    metrics_mod = importlib.util.module_from_spec(metrics_spec)
    assert metrics_spec and metrics_spec.loader
    metrics_spec.loader.exec_module(metrics_mod)  # type: ignore[arg-type]
    sys.modules["candyconc.services.backend.metrics"] = metrics_mod
    backend_pkg = sys.modules.setdefault(
        "candyconc.services.backend", types.ModuleType("candyconc.services.backend")
    )
    _prev_metrics_attr = getattr(backend_pkg, "metrics", _MISSING)
    setattr(backend_pkg, "metrics", metrics_mod)
    try:
        assert spec and spec.loader
        spec.loader.exec_module(pol_module)  # type: ignore[arg-type]
    finally:
        # ``backend_pkg`` may be the REAL backend package; undo the attribute
        # override (sys.modules entries are handled by the guard).
        if _prev_metrics_attr is _MISSING:
            try:
                delattr(backend_pkg, "metrics")
            except AttributeError:
                pass
        else:
            setattr(backend_pkg, "metrics", _prev_metrics_attr)
PolicyEngine = pol_module.PolicyEngine


class DummyProject:
    def __init__(self) -> None:
        self.settings = {}
        self.ops: list[str] = []
        self.outputs: list[str] = []

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    def log_op(self, op: str) -> None:  # pragma: no cover - required by orchestrator
        self.ops.append(op)

    def add_ai_output(self, data: str) -> None:  # pragma: no cover - required by orchestrator
        self.outputs.append(data)


class TestDynamicPolicy(unittest.TestCase):
    def test_project_overrides(self):
        proj = DummyProject()
        proj.set_setting("token_budget", "1")
        proj.set_setting("tool_acl", "dummy")
        policy = PolicyEngine(project=proj)

        res = policy.check("user", "dummy", 2)
        self.assertEqual(res["status"], "error")
        self.assertIn("budget", res["message"])

        proj.set_setting("token_budget", "5")
        policy.reset()
        res = policy.check("user", "dummy", 2)
        self.assertEqual(res["status"], "ok")

        proj.set_setting("tool_acl", "")
        policy.reset()
        res = policy.check("user", "dummy", 1)
        self.assertEqual(res["status"], "error")
        self.assertIn("Permission", res["message"])


if __name__ == "__main__":
    unittest.main()
