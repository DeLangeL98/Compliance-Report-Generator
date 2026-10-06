"""
SAAF — model-agnostic LLM client tests.

The OpenAI-compatible client is tested end to end against a throwaway local HTTP
server (no network, no SDKs). Anthropic-provider tests run only if the SDK is installed.

Run with:
    python -m unittest tests.test_llm -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from saaf.core.llm import (
    AnthropicClient,
    LLMError,
    OpenAICompatibleClient,
    create_client,
    validate_base_url,
)
from tests import endpoints as E

HAS_ANTHROPIC = importlib.util.find_spec("anthropic") is not None


class _Server:
    """Local server answering every POST with a canned (status, body, headers)."""

    def __init__(self, status=200, body=None, headers=None):
        self.requests = []  # (path, headers, json_body)
        outer = self
        reply = (status, body, headers or {})

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append((self.path, dict(self.headers), json.loads(raw)))
                code, payload, extra = reply
                data = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
                self.send_response(code)
                for k, v in extra.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # silence test output
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _completion(content="{}", **extra):
    body = {
        "choices": [{"message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
    }
    body.update(extra)
    return body


class _ServerTestCase(unittest.TestCase):
    def serve(self, **kw) -> _Server:
        server = _Server(**kw)
        self.addCleanup(server.close)
        return server


class TestOpenAICompatibleClient(_ServerTestCase):

    def test_request_shape_and_response_parsing(self):
        server = self.serve(body=_completion('{"ok": true}'))
        client = OpenAICompatibleClient("sk-test", "my-model", 5, server.url + "/v1")
        resp = client.complete("SYS", "USER", 123)

        path, headers, body = server.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer sk-test")
        self.assertEqual(body["model"], "my-model")
        self.assertEqual(body["max_tokens"], 123)
        self.assertEqual(body["messages"], [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ])
        self.assertEqual(resp.text, '{"ok": true}')
        self.assertEqual((resp.input_tokens, resp.output_tokens, resp.stop_reason),
                         (11, 22, "stop"))

    def test_exposes_the_endpoint_it_calls(self):
        client = OpenAICompatibleClient("", "m", 5, E.LOCAL_OLLAMA_BASE)
        self.assertEqual(client.endpoint, E.LOCAL_OLLAMA_ENDPOINT)

    def test_trailing_slash_and_full_endpoint_url_both_work(self):
        server = self.serve(body=_completion())
        OpenAICompatibleClient("", "m", 5, server.url + "/v1/").complete("s", "u", 1)
        OpenAICompatibleClient("", "m", 5, server.url + "/x/chat/completions").complete("s", "u", 1)
        self.assertEqual([r[0] for r in server.requests],
                         ["/v1/chat/completions", "/x/chat/completions"])

    def test_no_api_key_sends_no_authorization_header(self):
        server = self.serve(body=_completion())
        OpenAICompatibleClient("", "m", 5, server.url).complete("s", "u", 1)
        self.assertNotIn("Authorization", server.requests[0][1])

    def test_think_blocks_are_stripped(self):
        server = self.serve(body=_completion('<think>use {braces} here</think>\n{"a": 1}'))
        resp = OpenAICompatibleClient("", "m", 5, server.url).complete("s", "u", 1)
        self.assertEqual(resp.text, '{"a": 1}')

    def test_null_content_becomes_empty_text(self):
        server = self.serve(body=_completion(None))
        resp = OpenAICompatibleClient("", "m", 5, server.url).complete("s", "u", 1)
        self.assertEqual(resp.text, "")

    def test_4xx_is_not_retryable(self):
        server = self.serve(status=401, body={"error": "bad key"})
        with self.assertRaises(LLMError) as ctx:
            OpenAICompatibleClient("k", "m", 5, server.url).complete("s", "u", 1)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("bad key", str(ctx.exception))

    def test_5xx_is_retryable(self):
        server = self.serve(status=503, body={"error": "overloaded"})
        with self.assertRaises(LLMError) as ctx:
            OpenAICompatibleClient("k", "m", 5, server.url).complete("s", "u", 1)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertTrue(ctx.exception.retryable)

    def test_connection_refused_is_retryable(self):
        server = _Server()
        url = server.url
        server.close()  # nothing listens on this port any more
        with self.assertRaises(LLMError) as ctx:
            OpenAICompatibleClient("", "m", 2, url).complete("s", "u", 1)
        self.assertTrue(ctx.exception.retryable)
        self.assertIsNone(ctx.exception.status_code)

    def test_non_chat_completions_response_is_rejected(self):
        server = self.serve(body={"unexpected": "shape"})
        with self.assertRaises(LLMError) as ctx:
            OpenAICompatibleClient("", "m", 5, server.url).complete("s", "u", 1)
        self.assertIn("choices[0].message.content", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)

    def test_non_json_response_is_rejected(self):
        server = self.serve(body=b"<html>gateway</html>")
        with self.assertRaises(LLMError):
            OpenAICompatibleClient("", "m", 5, server.url).complete("s", "u", 1)

    def test_redirect_is_not_followed_so_the_key_is_not_forwarded(self):
        target = self.serve(body=_completion())
        origin = self.serve(status=307, body={}, headers={"Location": target.url + "/steal"})
        with self.assertRaises(LLMError) as ctx:
            OpenAICompatibleClient("secret", "m", 5, origin.url).complete("s", "u", 1)
        self.assertEqual(ctx.exception.status_code, 307)
        self.assertEqual(target.requests, [])


class TestValidateBaseUrl(unittest.TestCase):

    def test_accepts_and_strips_trailing_slash(self):
        self.assertEqual(validate_base_url(f" {E.SLASHED_BASE} "), E.SLASHED_BASE.rstrip("/"))

    def test_rejects_bad_scheme_missing_host_and_embedded_credentials(self):
        for bad in (E.FTP_URL, "example.com/v1", "http://", E.URL_WITH_CREDENTIALS):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_base_url(bad)

    def test_plain_http_to_remote_host_warns_but_loopback_does_not(self):
        with self.assertLogs("saaf.llm", level="WARNING") as cm:
            validate_base_url(E.INTERNAL_PLAIN_HTTP_BASE)
        self.assertIn("unencrypted", cm.output[0])
        with self.assertRaises(AssertionError):  # assertLogs fails when nothing is logged
            with self.assertLogs("saaf.llm", level="WARNING"):
                validate_base_url(E.LOCAL_OLLAMA_BASE)


class TestCreateClient(unittest.TestCase):

    def _config(self, **kw):
        defaults = dict(provider="openai", model="m", api_key="", base_url="",
                        timeout_seconds=7)
        defaults.update(kw)
        return MagicMock(**defaults)

    def test_openai_provider_builds_compatible_client_with_custom_endpoint(self):
        client = create_client(self._config(base_url=E.LOCAL_OLLAMA_BASE))
        self.assertIsInstance(client, OpenAICompatibleClient)
        self.assertEqual(client.url, E.LOCAL_OLLAMA_ENDPOINT)
        self.assertEqual(client.timeout, 7)

    def test_openai_default_endpoint(self):
        client = create_client(self._config())
        self.assertEqual(client.url, E.OPENAI_DEFAULT_ENDPOINT)

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ValueError):
            create_client(self._config(provider="nope"))


@unittest.skipUnless(HAS_ANTHROPIC, "anthropic SDK not installed")
class TestAnthropicClient(unittest.TestCase):

    def test_timeout_and_custom_base_url_passed_to_sdk(self):
        with patch("anthropic.Anthropic") as sdk:
            AnthropicClient("k", "claude-x", 42, E.ANTHROPIC_PROXY_BASE)
        self.assertEqual(sdk.call_args.kwargs["timeout"], 42)
        self.assertEqual(sdk.call_args.kwargs["base_url"], E.ANTHROPIC_PROXY_BASE)

    def test_exposes_the_endpoint_the_sdk_will_call(self):
        with patch("anthropic.Anthropic") as sdk:
            sdk.return_value.base_url = E.ANTHROPIC_DEFAULT_ENDPOINT
            client = AnthropicClient("k", "claude-x", 42)
        self.assertEqual(client.endpoint, E.ANTHROPIC_DEFAULT_ENDPOINT)

    def test_base_url_omitted_when_not_set(self):
        with patch("anthropic.Anthropic") as sdk:
            AnthropicClient("k", "claude-x", 42)
        self.assertNotIn("base_url", sdk.call_args.kwargs)

    def test_sdk_errors_map_to_llm_errors(self):
        import anthropic
        with patch("anthropic.Anthropic") as sdk:
            client = AnthropicClient("k", "claude-x", 5)
        response = MagicMock(status_code=503)
        response.headers = {}
        sdk.return_value.messages.stream.side_effect = anthropic.APIStatusError(
            "overloaded", response=response, body=None)
        with self.assertRaises(LLMError) as ctx:
            client.complete("s", "u", 10)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertTrue(ctx.exception.retryable)

        sdk.return_value.messages.stream.side_effect = anthropic.APIConnectionError(
            request=MagicMock())
        with self.assertRaises(LLMError) as ctx:
            client.complete("s", "u", 10)
        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
