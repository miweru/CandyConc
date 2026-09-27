import unittest

from fastapi.testclient import TestClient

from candyconc.services.backend import app, auth


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self._rbac_enabled = auth.RBAC_ENABLED
        self._tokens = dict(auth._tokens)
        self._roles = {name: user.role for name, user in auth._USERS.items()}
        auth.RBAC_ENABLED = True

    def tearDown(self):
        auth.RBAC_ENABLED = self._rbac_enabled
        auth._tokens.clear()
        auth._tokens.update(self._tokens)
        for name, role in self._roles.items():
            auth.set_role(name, role)

    def _login(self, username: str, password: str) -> str:
        resp = self.client.post(
            "/api/v1/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(resp.status_code, 200)
        token = resp.json().get("token")
        self.assertIsInstance(token, str)
        return token

    def test_role_enforcement_uses_problem_responses(self):
        # Admin-gated route (route matrix prefix /api/v1/system): the middleware
        # must serialize role failures as problem+json with the instance path.
        user_token = self._login("bob", "bob")
        user_resp = self.client.get("/api/v1/system/info", params={"token": user_token})
        self.assertEqual(user_resp.status_code, 403)
        self.assertEqual(user_resp.json().get("instance"), "/api/v1/system/info")

        anonymous_resp = self.client.get("/api/v1/system/info")
        self.assertEqual(anonymous_resp.status_code, 401)
        self.assertEqual(anonymous_resp.json().get("instance"), "/api/v1/system/info")

        admin_token = self._login("alice", "alice")
        admin_resp = self.client.get("/api/v1/system/info", params={"token": admin_token})
        self.assertEqual(admin_resp.status_code, 200)

    def test_role_update_reflects_in_enforcement(self):
        # Role changes go through the auth module API (set_role); a promoted
        # user's fresh token must pass the admin gate.
        user_token = self._login("bob", "bob")
        forbidden = self.client.get("/api/v1/system/info", params={"token": user_token})
        self.assertEqual(forbidden.status_code, 403)

        auth.set_role("bob", "admin")
        promoted_token = self._login("bob", "bob")
        promoted = self.client.get(
            "/api/v1/system/info", params={"token": promoted_token}
        )
        self.assertEqual(promoted.status_code, 200)


if __name__ == "__main__":
    unittest.main()
