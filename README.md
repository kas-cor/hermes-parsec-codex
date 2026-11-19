# hermes-parsec-codex

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) **model-provider
plugin** that makes the built-in `openai-codex` provider work properly behind a
local [parsec](https://github.com/parsec-ai/parsec) compression proxy:

- the provider's canonical endpoint becomes your local parsec Codex route, and
- the Hermes model picker (CLI `/model`, Desktop model selector) lists the **live
  ChatGPT account catalog** — including account-gated models such as
  `gpt-6.2-sol` / `gpt-6.2-astra` — instead of the curated offline fallback.

No Hermes core files are patched. The plugin uses the sanctioned
[model-provider override surface](https://hermes-agent.nousresearch.com/docs/developer-guide/model-provider-plugin)
(`register_provider()` last-writer-wins from `$HERMES_HOME/plugins/`).

## The problem it fixes

Hermes' picker treats a configured `model.base_url` that differs from the
provider's canonical endpoint as a *relay*. For relay routes it only probes
providers whose profile `auth_type == "api_key"`; `openai-codex` is
`oauth_external`, so the probe is declined and the picker silently degrades to
the curated static list (no newest account-gated models). Inference is
unaffected, which makes the symptom look like "the proxy hides models" even
though the proxy relays `/chatgpt/models` byte-identically.

By making the parsec endpoint the profile's **own canonical** `base_url`, the
relay branch no longer triggers, and Hermes' built-in live Codex catalog fetcher
probes `<parsec>/models?client_version=…` with the ChatGPT account headers —
through the proxy, never directly to the vendor host. A `picker_catalog` hook
provides the same live list as a second path.

Everything else stays core-owned: OAuth credential resolution, the
`codex_responses` wire, reasoning-effort vocabulary, large-context (`-900k`)
variants and account usage.

## Requirements

- Hermes Agent with the model-provider plugin surface (recent releases).
- A local parsec proxy with the Codex wire enabled (`parsec setup codex`), i.e.
  a loopback `openai_base_url` in your Codex CLI config, **or** an explicit
  `PARSEC_CODEX_BASE_URL`.
- Codex signed in via the Codex CLI (`codex login`) — the plugin never handles
  tokens itself; Hermes core resolves them read-only for the picker.

## Install

```bash
hermes plugins install kas-cor/hermes-parsec-codex --enable
```

Install it in **every profile home** that should use it (a multiplexed gateway
resolves plugins per bound profile home):

```bash
hermes -p <profile> plugins install kas-cor/hermes-parsec-codex --enable
```

Updates arrive through the normal plugin update path (`hermes plugins update`,
Desktop Plugins tab, or unattended auto-update via `hermes plugins auto-update on`);
the provider registry re-scans lazily, so a running gateway picks up new versions
without a restart.

## Configuration

| Setting | Effect |
|---|---|
| unset | endpoint auto-detected from the parsec-managed `openai_base_url` in `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`); loopback http only |
| `PARSEC_CODEX_BASE_URL=http://127.0.0.1:<port>/chatgpt` | explicit endpoint override (loopback http only) |
| `PARSEC_CODEX_BASE_URL=` (empty) | plugin disabled; built-in canonical routing restored |
| no parsec route detected and no env var | plugin registers nothing; host keeps the built-in provider |

Keep Hermes' configured `model.base_url` equal to the plugin endpoint (that is
what `parsec setup codex` writes). If they diverge, the relay branch returns and
the picker falls back to the curated list again.

Non-loopback targets are refused by design: Codex credentials must never leave
the machine through this plugin.

## Verify

```bash
hermes -p <profile> plugins list          # parsec-codex installed, enabled
python - <<'PY'
from providers import get_provider_profile
from hermes_cli.models import provider_model_ids
print(get_provider_profile("openai-codex").base_url)   # your loopback parsec route
ids = provider_model_ids("openai-codex")
print(len(ids), [m for m in ids if m.startswith("gpt-6.2")])
PY
```

Expect the loopback parsec URL and a live list containing the newest
account-gated slugs. With the kill switch set, the same call returns the curated
fallback instead.

## Security notes

- The plugin reads only the Codex CLI config's `openai_base_url` (a URL, not a
  credential) and environment variables. It never reads, stores, logs or
  transmits tokens; all credential handling stays in Hermes core.
- Only loopback `http://` endpoints are accepted, so the OAuth bearer is never
  sent to a remote host by this plugin's routing.
- The repository contains no secrets, hostnames or account identifiers.

## License

MIT — see [LICENSE](LICENSE).