import os
import importlib
import unittest

# NOTE: no module-level sys.modules.pop here — pytest imports all test
# modules at collection time, and popping cached packages re-imports them
# fresh, breaking references other test modules bound earlier
# (tests/ai/test_observability pattern).  A plain import resolves the real
# server: the conftest only stubs leaf modules.
server = importlib.import_module("candyconc.services.backend.server")
auth = server.auth


class TestGuestAccess(unittest.TestCase):
    def setUp(self):
        os.environ["CANDYCONC_ENABLE_RBAC"] = "0"
        # Other test modules pop candyconc.services.backend from sys.modules
        # at import time; reload() needs the parent package present.
        importlib.import_module("candyconc.services.backend")
        importlib.reload(auth)
        importlib.reload(server)

    def tearDown(self):
        os.environ.pop("CANDYCONC_ENABLE_RBAC", None)
        importlib.import_module("candyconc.services.backend")
        importlib.reload(auth)
        importlib.reload(server)

    def test_user_key_guest(self):
        self.assertEqual(auth.username_for_token(None), "guest")
        key = server._user_key(None, "default")
        self.assertEqual(key, "default:guest")


if __name__ == "__main__":
    unittest.main()
