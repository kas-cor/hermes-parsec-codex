"""Parsec Codex routing plugin for Hermes Agent.

Owns the built-in ``openai-codex`` provider endpoint and restores live account
model discovery in the Hermes model picker when Codex traffic is routed through
a local parsec compression proxy.

Why this exists
---------------
Hermes' model picker treats a configured ``model.base_url`` that differs from
the provider's canonical endpoint as a *relay*, and for relay routes it only
probes providers whose profile ``auth_type == "api_key"``
(``hermes_cli/models.py::_relay_model_catalog``). ``openai-codex`` is
``oauth_external``, so the probe is declined and the picker degrades to the
curated offline catalog: account-gated slugs such as ``gpt-6.2-sol`` /
``gpt-6.2-astra`` never show up, while inference through the proxy works fine.

This plugin uses the sanctioned model-provider override surface
(``$HERMES_HOME/plugins/...``, last-writer-wins; see the Hermes developer guide
"Model Provider Plugins"): it re-registers the built-in ``openai-codex`` profile
with the parsec endpoint as its OWN canonical ``base_url``. The relay branch then
no longer triggers (configured base == profile base), the built-in live Codex
catalog fetcher runs, and it probes ``<parsec>/models?client_version=...`` with
the ChatGPT account headers — the live account catalog, through the proxy, with
no direct vendor egress.

No Hermes core file is edited. OAuth credential resolution, the ``codex_responses``
wire, reasoning-effort vocabulary, large-context variants and account usage stay
core-owned: the profile mirrors the bundled field values.

Endpoint selection
------------------
1. ``PARSEC_CODEX_BASE_URL`` env var (loopback http URL). An explicitly empty
   value disables the plugin entirely (built-in canonical routing restored).
2. Otherwise the parsec-managed ``openai_base_url`` from the Codex CLI config
   (``$CODEX_HOME/config.toml``, default ``~/.codex/config.toml``), accepted only
   when it is a loopback http URL.
3. Otherwise the plugin registers nothing: hosts without a parsec-routed Codex
   CLI keep the built-in provider untouched.

The plugin never reads, stores or logs tokens; credential handling remains in
Hermes core (read-only resolution for the picker catalog hook).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from providers import register_provider
from providers.base import ProviderProfile

#: Built-in canonical endpoint, mirrored from the bundled openai-codex profile.
CANONICAL_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_loopback_http(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS


def _codex_config_base_url() -> str:
    """The parsec-managed openai_base_url from the Codex CLI config, if loopback."""
    codex_home = Path(os.getenv("CODEX_HOME", "").strip() or str(Path.home() / ".codex"))
    try:
        payload = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    base = str(payload.get("openai_base_url") or "").strip().rstrip("/")
    return base if _is_loopback_http(base) else ""


def _live_codex_catalog(force_refresh: bool = False):
    """Provider-owned picker catalog: the account's live Codex slugs via parsec.

    Delegates to Hermes core (``hermes_cli.codex_models``) so client_version
    probing, ChatGPT-Account-ID headers, forward-compat and large-context
    synthesis stay core-owned. Returns None on any failure so callers fall back
    to their curated list.
    """
    try:
        from hermes_cli.auth import (
            _codex_access_token_is_expiring,
            resolve_codex_runtime_credentials,
        )
        from hermes_cli.codex_models import get_codex_model_ids

        creds = resolve_codex_runtime_credentials(read_only=True)
        token = str(creds.get("api_key") or "")
        base = str(creds.get("base_url") or "")
        if not token or _codex_access_token_is_expiring(token, 0):
            return None
        ids = get_codex_model_ids(access_token=token, base_url=base or None)
        return list(ids) or None
    except Exception:
        return None


def _register() -> None:
    raw = os.getenv("PARSEC_CODEX_BASE_URL")
    if raw is not None:
        if not raw.strip():
            return  # explicit empty value = plugin disabled
        base = raw.strip().rstrip("/")
        if not _is_loopback_http(base):
            return  # refuse non-loopback targets: credentials must stay local
    else:
        base = _codex_config_base_url()
        if not base:
            return  # no parsec-routed Codex CLI on this host: stay inert

    # Mirror of the bundled openai-codex profile: same aliases, wire mode, empty
    # env_vars and oauth_external auth. Only base_url changes ownership, plus a
    # provider-owned picker catalog as a second live path.
    register_provider(
        ProviderProfile(
            name="openai-codex",
            aliases=("codex", "openai_codex"),
            api_mode="codex_responses",
            env_vars=(),
            base_url=base,
            auth_type="oauth_external",
            display_name="OpenAI Codex (parsec)",
            description="ChatGPT Codex via the local parsec compression proxy",
            picker_catalog=_live_codex_catalog,
        )
    )


_register()