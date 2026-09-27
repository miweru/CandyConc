import unittest
from candyconc.config import APP_CONFIG, get, set, load_settings

class TestConfigGetSet(unittest.TestCase):
    def test_get_known_field(self):
        APP_CONFIG.COPILOT_MODEL = "test-model"
        self.assertEqual(get("COPILOT_MODEL"), "test-model")

    def test_get_bool_field(self):
        APP_CONFIG.CANDYCONC_ENABLE_RBAC = True
        self.assertEqual(get("CANDYCONC_ENABLE_RBAC"), "1")
        APP_CONFIG.CANDYCONC_ENABLE_RBAC = False
        self.assertEqual(get("CANDYCONC_ENABLE_RBAC"), "0")

    def test_get_default_for_unknown(self):
        self.assertEqual(get("UNKNOWN", "default"), "default")

    def test_set_updates_setting(self):
        set("COPILOT_MODEL", "other-model")
        self.assertEqual(APP_CONFIG.COPILOT_MODEL, "other-model")

    def test_load_settings_survives_module_set_function(self):
        cfg = load_settings()
        self.assertTrue(hasattr(cfg, "COPILOT_ENDPOINT"))
