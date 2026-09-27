import unittest

from candyconc.services.llm_client import _sanitize_messages


class TestMessageRoleNormalization(unittest.TestCase):
    """Belt-and-suspenders: ``_sanitize_messages`` is the single point every
    route branch passes through before payload building. Any role outside the
    ChatML set must be normalized to ``"user"`` so it cannot reach the wire and
    trigger an HTTP 400 from an OpenAI-compatible endpoint.
    """

    def test_non_standard_role_normalized_to_user(self):
        out = _sanitize_messages(
            [{"role": "guest", "content": "Wie häufig kommt Leute vor?"}],
            strip_media=True,
        )
        self.assertEqual(out[0]["role"], "user")
        self.assertEqual(out[0]["content"], "Wie häufig kommt Leute vor?")

    def test_standard_roles_preserved(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
            {"role": "tool", "content": "t", "tool_call_id": "x"},
        ]
        out = _sanitize_messages(msgs, strip_media=True)
        self.assertEqual([m["role"] for m in out], ["system", "user", "assistant", "tool"])
        # Non-role fields (e.g. tool_call_id) are preserved.
        self.assertEqual(out[-1].get("tool_call_id"), "x")

    def test_missing_role_normalized_to_user(self):
        out = _sanitize_messages([{"content": "no role"}], strip_media=True)
        self.assertEqual(out[0]["role"], "user")

    def test_none_and_empty_role_normalized_to_user(self):
        out = _sanitize_messages(
            [{"role": None, "content": "a"}, {"role": "", "content": "b"}],
            strip_media=True,
        )
        self.assertEqual([m["role"] for m in out], ["user", "user"])


if __name__ == "__main__":
    unittest.main()
