"""
SAAF — Config provider / model / endpoint resolution (explicit arg > env > default).

Run with:
    python -m unittest tests.test_config -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from tests import endpoints as E


def _env(**kw):
    """Replace the whole environment so a developer's real keys never leak in."""
    return patch.dict("os.environ", kw, clear=True)


class TestConfigDefaults(unittest.TestCase):

    def test_default_is_anthropic_with_unchanged_model(self):
        with _env(ANTHROPIC_API_KEY="k"):
            c = Config()
        self.assertEqual((c.provider, c.model, c.base_url, c.api_key),
                         ("anthropic", "claude-opus-4-6", "", "k"))

    def test_missing_anthropic_key_raises(self):
        with _env(), self.assertRaises(EnvironmentError) as ctx:
            Config()
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))


class TestConfigProviders(unittest.TestCase):

    def test_openai_requires_a_model(self):
        with _env(OPENAI_API_KEY="k"), self.assertRaises(EnvironmentError) as ctx:
            Config(provider="openai")
        self.assertIn("--model", str(ctx.exception))

    def test_openai_uses_openai_key_env(self):
        with _env(OPENAI_API_KEY="ok"):
            c = Config(provider="openai", model="gpt-x")
        self.assertEqual(c.api_key, "ok")

    def test_openai_hosted_without_key_raises(self):
        with _env(), self.assertRaises(EnvironmentError):
            Config(provider="openai", model="gpt-x")

    def test_custom_endpoint_needs_no_key_for_openai_compatible(self):
        with _env():
            c = Config(provider="openai", model="llama3", base_url=E.LOCAL_OLLAMA_BASE)
        self.assertEqual((c.api_key, c.base_url), ("", E.LOCAL_OLLAMA_BASE))

    def test_anthropic_still_requires_key_with_custom_endpoint(self):
        with _env(), self.assertRaises(EnvironmentError):
            Config(base_url=E.ANTHROPIC_PROXY_BASE)

    def test_unknown_provider_rejected(self):
        with _env(), self.assertRaises(EnvironmentError):
            Config(provider="gemini")


class TestConfigPrecedence(unittest.TestCase):

    def test_env_vars_apply(self):
        with _env(SAAF_PROVIDER="OpenAI", SAAF_MODEL="m1", SAAF_BASE_URL=E.SLASHED_BASE,
                  SAAF_API_KEY="generic"):
            c = Config()
        self.assertEqual((c.provider, c.model, c.base_url, c.api_key),
                         ("openai", "m1", E.SLASHED_BASE.rstrip("/"), "generic"))

    def test_explicit_arguments_beat_env(self):
        with _env(SAAF_PROVIDER="anthropic", SAAF_MODEL="env-model", SAAF_BASE_URL=E.ENV_BASE,
                  ANTHROPIC_API_KEY="k"):
            c = Config(provider="openai", model="arg-model", base_url=E.ARG_BASE,
                       api_key="arg-key")
        self.assertEqual((c.provider, c.model, c.base_url, c.api_key),
                         ("openai", "arg-model", E.ARG_BASE, "arg-key"))

    def test_saaf_api_key_beats_provider_key(self):
        with _env(SAAF_API_KEY="generic", ANTHROPIC_API_KEY="specific"):
            self.assertEqual(Config().api_key, "generic")

    def test_invalid_base_url_raises_environment_error(self):
        with _env(ANTHROPIC_API_KEY="k"), self.assertRaises(EnvironmentError):
            Config(base_url="not-a-url")


if __name__ == "__main__":
    unittest.main()
