"""Single-source configuration guards (Track D9).

These tests pin two invariants:

1. **Precedence** ``set() > init > env > toml(pyproject) > field defaults``.
   The historical bug was ``AppConfig(**pyproject_defaults)`` which made the
   pyproject values outrank real environment variables (init beats env in
   pydantic-settings). ``load_settings`` now seeds ``os.environ`` for absent
   keys only, then builds ``AppConfig()`` with no init kwargs, so env wins.

2. **CI guard**: no model-field name is read out of ``os.environ`` anywhere in
   ``src/``. Runtime code must read configuration via ``APP_CONFIG`` /
   ``config.get`` so that there is a single source of truth. Writes of a
   model-field name into ``os.environ`` are only allowed inside
   ``config.set()`` (its write-through).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, wie candyconc.config
    import tomli as tomllib

from candyconc.config import AppConfig, load_settings

APP_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = APP_DIR / "src"
CONFIG_PY = SRC_DIR / "candyconc" / "config.py"
MODEL_FIELDS = frozenset(AppConfig.model_fields.keys())


def _spawn_config(env_overrides: dict[str, str], *, expect_ok: bool = True):
    """Import config in a clean subprocess and return selected values.

    A subprocess is used because ``APP_CONFIG`` is constructed at import time;
    we need a pristine ``os.environ`` snapshot to prove precedence.
    """

    env = dict(os.environ)
    # Drop any pre-existing values for the keys we drive so the test is
    # deterministic regardless of the developer's shell.
    for key in ("COPILOT_MODEL", "COPILOT_TIMEOUT", "CANDYCONC_LOG_LEVEL", "CANDYCONC_CONFIG_FILE"):
        env.pop(key, None)
    # Keep a real user configuration file on the developer's machine out of
    # the test unless a test points at its own file.
    env["CANDYCONC_CONFIG_FILE"] = str(APP_DIR / "tests" / "unit" / "no-such-config.toml")
    env.update(env_overrides)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import json; import candyconc.config as c;"
        "print(json.dumps({"
        "'COPILOT_MODEL': c.APP_CONFIG.COPILOT_MODEL,"
        "'COPILOT_TIMEOUT': c.APP_CONFIG.COPILOT_TIMEOUT,"
        "'CANDYCONC_LOG_LEVEL': c.APP_CONFIG.CANDYCONC_LOG_LEVEL,"
        "}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(APP_DIR),
    )
    if not expect_ok:
        return proc
    assert proc.returncode == 0, proc.stderr
    import json

    return json.loads(proc.stdout.strip().splitlines()[-1])


def _checkout_profile() -> dict:
    with (APP_DIR / "pyproject.toml").open("rb") as source:
        return tomllib.load(source).get("tool", {}).get("candyconc", {})


def test_pyproject_default_applies_when_env_absent() -> None:
    """With no env override, the [tool.candyconc] pyproject value wins."""
    defaults = _checkout_profile()
    if "COPILOT_MODEL" not in defaults:
        import pytest

        pytest.skip("this checkout carries no [tool.candyconc] profile")
    values = _spawn_config({})
    assert values["COPILOT_MODEL"] == defaults["COPILOT_MODEL"]
    # pyproject.toml setzt COPILOT_TIMEOUT (ueberschreibt die 30.0 im Schema).
    # Der Wert wurde am 2026-08-29 auf Nutzervorgabe von 120,0 auf 8.000.000
    # angehoben, nachdem neun von zwoelf gemessenen Turns exakt am Backstop
    # aufschlugen. Der Test prueft die DURCHREICHE von pyproject, nicht die
    # Hoehe des Limits, deshalb wandert der Pin mit statt gestrichen zu
    # werden. Er haelt zugleich die Richtung fest: dieser Wert darf steigen,
    # nie fallen.
    assert values["COPILOT_TIMEOUT"] == 8_000_000.0
    assert values["COPILOT_TIMEOUT"] > 120.0, (
        "COPILOT_TIMEOUT wurde gesenkt. Das ist ausdruecklich untersagt: ein "
        "laufender Aufruf ist ein Modell, das am Thema arbeitet."
    )


def test_env_overrides_pyproject_default() -> None:
    """The headline precedence fix: env beats pyproject (env > toml)."""
    values = _spawn_config(
        {"COPILOT_MODEL": "env-model", "COPILOT_TIMEOUT": "5.5"}
    )
    assert values["COPILOT_MODEL"] == "env-model"
    assert values["COPILOT_TIMEOUT"] == 5.5


def test_field_default_when_neither_env_nor_pyproject() -> None:
    """A field absent from both env and pyproject falls back to its default."""
    values = _spawn_config({})
    # CANDYCONC_LOG_LEVEL is not set in pyproject -> field default "INFO".
    assert values["CANDYCONC_LOG_LEVEL"] == "INFO"


def test_set_write_through_to_environ() -> None:
    """``config.set`` updates APP_CONFIG and writes through to os.environ."""
    import candyconc.config as c

    original = os.environ.get("CANDYCONC_LOG_LEVEL")
    try:
        c.set("CANDYCONC_LOG_LEVEL", "WARNING")
        assert c.APP_CONFIG.CANDYCONC_LOG_LEVEL == "WARNING"
        assert os.environ["CANDYCONC_LOG_LEVEL"] == "WARNING"
    finally:
        if original is None:
            os.environ.pop("CANDYCONC_LOG_LEVEL", None)
        else:
            os.environ["CANDYCONC_LOG_LEVEL"] = original


def test_set_non_field_does_not_touch_environ() -> None:
    """Non model-field keys are not written through to os.environ."""
    import candyconc.config as c

    os.environ.pop("NOT_A_MODEL_FIELD", None)
    c.set("NOT_A_MODEL_FIELD", "value")
    assert "NOT_A_MODEL_FIELD" not in os.environ


def test_load_settings_is_idempotent() -> None:
    """Repeated load_settings calls keep precedence stable (no kwargs leak)."""
    cfg = load_settings()
    assert isinstance(cfg, AppConfig)
    assert cfg.COPILOT_MODEL == load_settings().COPILOT_MODEL


# ---------------------------------------------------------------------------
# T11 (B6): validate_assignment coerces raw-string assignments to bool fields.
# ---------------------------------------------------------------------------


def test_set_coerces_string_to_bool_field() -> None:
    """``config.set('DRY_RUN', 'false')`` must store a real ``False`` bool.

    Before ``validate_assignment=True`` the raw ``"false"`` string was stored on
    the bool field and evaluated truthy ("false-string-as-True"). The coercion
    must turn every falsy spelling into ``False`` and truthy spellings into
    ``True`` — not leave a string.
    """
    import candyconc.config as c

    original = c.APP_CONFIG.DRY_RUN
    try:
        for falsy in ("false", "0", "no", "off"):
            c.set("DRY_RUN", falsy)
            assert c.APP_CONFIG.DRY_RUN is False, f"{falsy!r} -> {c.APP_CONFIG.DRY_RUN!r}"
        for truthy in ("true", "1", "yes", "on"):
            c.set("DRY_RUN", truthy)
            assert c.APP_CONFIG.DRY_RUN is True, f"{truthy!r} -> {c.APP_CONFIG.DRY_RUN!r}"
    finally:
        c.APP_CONFIG.DRY_RUN = bool(original)


def test_real_bool_and_string_assignments_still_work() -> None:
    """A native bool on a bool field and a string on a string field round-trip."""
    import candyconc.config as c

    orig_rbac = c.APP_CONFIG.CANDYCONC_ENABLE_RBAC
    orig_level = c.APP_CONFIG.CANDYCONC_LOG_LEVEL
    try:
        c.APP_CONFIG.CANDYCONC_ENABLE_RBAC = True
        assert c.APP_CONFIG.CANDYCONC_ENABLE_RBAC is True
        c.APP_CONFIG.CANDYCONC_ENABLE_RBAC = False
        assert c.APP_CONFIG.CANDYCONC_ENABLE_RBAC is False

        c.set("CANDYCONC_LOG_LEVEL", "WARNING")
        assert c.APP_CONFIG.CANDYCONC_LOG_LEVEL == "WARNING"
    finally:
        c.APP_CONFIG.CANDYCONC_ENABLE_RBAC = bool(orig_rbac)
        c.APP_CONFIG.CANDYCONC_LOG_LEVEL = orig_level


def test_after_validator_stays_idempotent_under_assignment() -> None:
    """validate_assignment must not corrupt derived LM-studio fields.

    Assigning an UNRELATED field re-runs the mode='after' validator; the derived
    COPILOT_ENDPOINT / LM_STUDIO_TRANSPORT must stay stable (the re-entrancy
    guard prevents infinite recursion and keeps the derivation a fixed point).
    """
    import candyconc.config as c

    orig_level = c.APP_CONFIG.CANDYCONC_LOG_LEVEL
    try:
        before_ep = c.APP_CONFIG.COPILOT_ENDPOINT
        before_transport = c.APP_CONFIG.LM_STUDIO_TRANSPORT
        c.set("CANDYCONC_LOG_LEVEL", "INFO")
        c.set("CANDYCONC_LOG_LEVEL", "DEBUG")
        assert c.APP_CONFIG.COPILOT_ENDPOINT == before_ep
        assert c.APP_CONFIG.LM_STUDIO_TRANSPORT == before_transport
    finally:
        c.APP_CONFIG.CANDYCONC_LOG_LEVEL = orig_level


# ---------------------------------------------------------------------------
# CI guard: no model-field name read via os.environ in src/
# ---------------------------------------------------------------------------


def _iter_src_py() -> list[Path]:
    return sorted(SRC_DIR.rglob("*.py"))


def _env_read_field_names(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, field_name) for os.environ reads of model-field names."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        key_arg: ast.expr | None = None
        # os.environ.get("KEY") / os.getenv("KEY")
        if isinstance(func, ast.Attribute):
            if func.attr == "get" and _is_os_environ(func.value):
                key_arg = node.args[0] if node.args else None
            elif func.attr == "getenv" and _is_os(func.value):
                key_arg = node.args[0] if node.args else None
        if isinstance(key_arg, ast.Constant) and isinstance(key_arg.value, str):
            if key_arg.value in MODEL_FIELDS:
                hits.append((node.lineno, key_arg.value))
    # os.environ["KEY"] subscript reads
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_os_environ(node.value)
        ):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                if sl.value in MODEL_FIELDS:
                    hits.append((node.lineno, sl.value))
    return hits


def _env_write_field_names(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, field_name) for os.environ[...] = ... writes."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for tgt in targets:
            if (
                isinstance(tgt, ast.Subscript)
                and _is_os_environ(tgt.value)
                and isinstance(tgt.slice, ast.Constant)
                and isinstance(tgt.slice.value, str)
                and tgt.slice.value in MODEL_FIELDS
            ):
                hits.append((node.lineno, tgt.slice.value))
    return hits


def _is_os(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


def _is_os_environ(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and _is_os(node.value)
    )


def test_no_model_field_read_via_os_environ_in_src() -> None:
    """Runtime code must never read a model-field name out of os.environ."""
    offenders: list[str] = []
    for path in _iter_src_py():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for lineno, name in _env_read_field_names(tree):
            offenders.append(f"{path.relative_to(SRC_DIR)}:{lineno} reads {name}")
    assert not offenders, (
        "model-field config must be read via APP_CONFIG/config.get, "
        "not os.environ:\n" + "\n".join(offenders)
    )


def test_model_field_environ_writes_only_in_config_set() -> None:
    """Only config.set() may write a model-field name into os.environ."""
    offenders: list[str] = []
    for path in _iter_src_py():
        if path == CONFIG_PY:
            # config.set()'s write-through is the single sanctioned writer.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for lineno, name in _env_write_field_names(tree):
            offenders.append(f"{path.relative_to(SRC_DIR)}:{lineno} writes {name}")
    # Seam F: the previously-redundant os.environ pokes in startup.py / server.py
    # were removed now that config.set() write-throughs into os.environ. This is
    # a hard CI guard so no track reintroduces a second source of truth.
    assert not offenders, (
        "only config.set()'s write-through may write a model-field name into "
        "os.environ:\n" + "\n".join(offenders)
    )


def test_user_config_file_applies_when_env_absent(tmp_path) -> None:
    """The user configuration file (CANDYCONC_CONFIG_FILE) sets values."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('COPILOT_MODEL = "from-file"\nCANDYCONC_LOG_LEVEL = "WARNING"\n', encoding="utf-8")
    values = _spawn_config({"CANDYCONC_CONFIG_FILE": str(config_file)})
    assert values["COPILOT_MODEL"] == "from-file"
    assert values["CANDYCONC_LOG_LEVEL"] == "WARNING"


def test_env_beats_user_config_file(tmp_path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('COPILOT_MODEL = "from-file"\n', encoding="utf-8")
    values = _spawn_config({"CANDYCONC_CONFIG_FILE": str(config_file), "COPILOT_MODEL": "from-env"})
    assert values["COPILOT_MODEL"] == "from-env"


def test_user_config_file_beats_checkout_profile(tmp_path) -> None:
    """Order: environment > user file > checkout profile > field default."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('COPILOT_MODEL = "from-file"\nCOPILOT_TIMEOUT = 9000000.0\n', encoding="utf-8")
    values = _spawn_config({"CANDYCONC_CONFIG_FILE": str(config_file)})
    assert values["COPILOT_MODEL"] == "from-file"
    assert values["COPILOT_TIMEOUT"] == 9_000_000.0


def test_invalid_user_config_file_names_the_file(tmp_path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("COPILOT_MODEL = \n", encoding="utf-8")
    proc = _spawn_config({"CANDYCONC_CONFIG_FILE": str(config_file)}, expect_ok=False)
    assert proc.returncode != 0
    assert str(config_file) in proc.stderr
    assert "not valid TOML" in proc.stderr


def test_user_config_file_rejects_tables(tmp_path, monkeypatch) -> None:
    import pytest

    import candyconc.config as c

    config_file = tmp_path / "config.toml"
    config_file.write_text("[copilot]\nmodel = 'x'\n", encoding="utf-8")
    monkeypatch.setenv("CANDYCONC_CONFIG_FILE", str(config_file))
    with pytest.raises(c.ConfigFileError, match="single value"):
        c._load_user_config()


def test_copilot_is_optional() -> None:
    """Without a model endpoint the configuration is valid (KI-free use)."""
    cfg = AppConfig(COPILOT_ENDPOINT=None, LM_STUDIO_BASE_URL=None)
    cfg.validate()
    assert cfg.copilot_configured is False
    assert AppConfig(COPILOT_ENDPOINT="http://127.0.0.1:1234/v1/responses").copilot_configured is True


def test_installed_package_defaults_need_no_pyproject() -> None:
    """Field defaults carry every value the start needs (no pyproject.toml)."""
    fields = AppConfig.model_fields
    assert fields["COPILOT_ENDPOINT"].default is None
    assert fields["COPILOT_TIMEOUT"].default == 8_000_000.0
    assert fields["CANDYCONC_SECURITY_MODE"].default == "local_dev_unsafe"
    assert fields["CANDYCONC_ENABLE_RBAC"].default is False
    assert fields["index_dir"].default == ""
    assert fields["CANDYCONC_PROJECT_FILE"].default == ""
