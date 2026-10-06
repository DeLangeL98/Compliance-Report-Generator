"""
Shared endpoint fixtures for the provider, config and audit-trail tests.

Change a URL, host or port here and every test follows. Nothing in this module is
contacted: hosts under ``example.com`` / ``.example`` are reserved (RFC 2606) and
never resolve to a real service, and the one live test server binds an ephemeral
port chosen by the OS (see ``_Server`` in test_llm.py).
"""

# ---------------------------------------------------------------------------
# Ports: each one is chosen because it is what real deployments use
# ---------------------------------------------------------------------------

# Ollama's default port, the most common local OpenAI-compatible server.
# Used to prove a local endpoint is accepted, needs no API key, and keeps its port.
OLLAMA_PORT = 11434

# A typical alternative HTTPS port (not 443). Used to prove a non-default port
# survives endpoint sanitising and shows up in the recorded host.
ALT_HTTPS_PORT = 8443

# Default port of vLLM / uvicorn-style local servers. Paired with the IPv6 loopback
# literal ``[::1]`` to prove bracketed IPv6 hosts are parsed and re-emitted correctly.
LOCAL_SERVER_PORT = 8000

# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

HOSTED_HOST = "llm.example.com"          # a hosted OpenAI-compatible service
GATEWAY_HOST = "gw.example.com"          # a gateway that may carry credentials in the URL
INTERNAL_HOST = "llm.internal.example"   # a non-loopback host, to exercise the plain-http warning
SANITISE_HOST = "h.example.com"          # host used by the pure sanitiser examples

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

OPENAI_DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_DEFAULT_ENDPOINT = "https://api.anthropic.com"

LOCAL_OLLAMA_BASE = f"http://localhost:{OLLAMA_PORT}/v1"
LOCAL_OLLAMA_ENDPOINT = LOCAL_OLLAMA_BASE + "/chat/completions"
IPV6_LOOPBACK_BASE = f"http://[::1]:{LOCAL_SERVER_PORT}/v1"

HOSTED_ENDPOINT_WITH_PORT = f"https://{HOSTED_HOST}:{ALT_HTTPS_PORT}/v1/chat/completions"
INTERNAL_PLAIN_HTTP_BASE = f"http://{INTERNAL_HOST}/v1"
ANTHROPIC_PROXY_BASE = "https://gateway.example/anthropic"

# A URL carrying userinfo, a query-string key and a fragment: none may reach the audit file.
ENDPOINT_WITH_SECRETS = f"https://user:hunter2@{GATEWAY_HOST}/v1?api_key=SECRET#frag"
SECRET_FRAGMENTS = ("hunter2", "SECRET", "api_key", "frag", "user:")
ENDPOINT_WITH_QUERY_SECRET = f"https://{HOSTED_HOST}/v1/chat/completions?api_key=SECRET"

# Sanitiser input / expected output pair (userinfo, trailing slash, query, fragment stripped)
DIRTY_ENDPOINT = f"https://u:p@{SANITISE_HOST}/v1/?k=v#f"
CLEAN_ENDPOINT = f"https://{SANITISE_HOST}/v1"

# Config-resolution examples (flag vs env precedence, trailing-slash stripping)
ENV_BASE = "https://env.example"
ARG_BASE = "https://arg.example/v1"
SLASHED_BASE = "https://h.example/v1/"

# Rejected inputs
FTP_URL = f"ftp://{SANITISE_HOST}"
URL_WITH_CREDENTIALS = "https://user:pw@example.com"
