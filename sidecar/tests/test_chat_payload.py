import unittest

from uncloud_engine.chat import build_chat_payload


class PlainChatPayloadTest(unittest.TestCase):
    def test_gguf_chat_disables_unbounded_thinking(self) -> None:
        payload = build_chat_payload(
            [{"role": "user", "content": "Hello"}],
            temperature=0.7,
            max_tokens=1024,
            engine="gguf",
        )
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(payload["thinking_budget_tokens"], 0)
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["max_tokens"], 1024)

    def test_mlx_chat_keeps_the_portable_openai_payload(self) -> None:
        payload = build_chat_payload(
            [{"role": "user", "content": "Hello"}],
            temperature=0.7,
            max_tokens=1024,
            engine="mlx",
        )
        self.assertNotIn("chat_template_kwargs", payload)
        self.assertNotIn("thinking_budget_tokens", payload)
        self.assertNotIn("reasoning_effort", payload)


if __name__ == "__main__":
    unittest.main()
