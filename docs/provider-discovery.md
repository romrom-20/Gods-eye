# Provider model discovery and connection checks

The loopback setup page supports explicit catalog loading and a separate confirmed
connection/tool-call test. Opening setup, changing provider, and saving settings
make **no provider requests**. No experiment starts through this page.

Start the existing launcher or `python -m godseye.provider_setup`. Restart an older
setup process to receive the new page. Select OpenAI, OpenRouter, or Hugging Face;
enter a key or leave the field blank to use that provider's saved key. An entered
key can be used for discovery/testing without saving it.

- **Load models** makes one catalog GET. Search the returned IDs and select one,
  or keep entering an ID manually. Loading never replaces the model field.
- **Save key locally** preserves a blank key and the other providers' profiles.
  It writes the existing `provider.json` and `provider.env` formats. Additional
  profile fields are preserved. It does not validate access or tool calling.
- **Test connection and tool calling** displays a confirmation naming the provider,
  model, and routing preference and explaining possible billing. Cancelling makes
  no request. Confirming sends exactly one inference POST, with a fixed small
  prompt, one harmless function definition, and a **128-token output limit**.
  No tool is executed, no follow-up is sent, and no retries occur. Running the
  action again requires another confirmation. A timeout/disconnect may still be
  billed. The output limit is not a dollar cap; account billing controls apply.

## Official API contracts

Official documentation checked **November 10, 2026**. These are independent
provider integrations; OpenAI-compatible does not mean identical capability or
routing behavior.

### OpenAI

Catalog: `GET https://api.openai.com/v1/models` with bearer authentication.
Only model IDs are used. The documented list schema supplies no tool-capability
field, so every entry has **unknown** tool support. IDs can include models that
cannot use Responses or function calling. No model-name heuristics are applied.

Test: `POST https://api.openai.com/v1/responses`, with Responses' flat function
definition, strict empty argument schema, a named function choice,
`parallel_tool_calls=false`, `max_output_tokens=128`, `stream=false`, and
`store=false`. A completed response must contain exactly one matching
`function_call` with JSON arguments `{}` to verify tool calling.

Sources: [List models](https://developers.openai.com/api/reference/resources/models/methods/list),
[Responses create](https://developers.openai.com/api/reference/resources/responses/methods/create),
[Function calling](https://developers.openai.com/api/docs/guides/function-calling).

### OpenRouter

Catalog: `GET https://openrouter.ai/api/v1/models` with bearer authentication.
No pagination arguments are sent: the documented endpoint returns the full list
when offset/limit are omitted. `supported_parameters` containing `tools` confirms
catalog tool support. Missing metadata or an absent `tools` parameter is shown
as **unknown**. Catalog support does not prove that a route meets this application's
privacy/parameter constraints or that the account has access.

Test: `POST https://openrouter.ai/api/v1/chat/completions`, with nested chat
function definitions, `tool_choice=required`, `max_tokens=128`, and `stream=false`.
The provider policy matches the existing adapter: selected `sort` preference,
`require_parameters=true`, `data_collection=deny`, `allow_fallbacks=false`.
No model fallback list or plugins are sent. The response must finish with
`tool_calls` and contain one matching function call with JSON arguments `{}`.

Sources: [Model catalog](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties),
[Tools](https://openrouter.ai/docs/guides/features/tool-calling),
[Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).

### Hugging Face Inference Providers

Catalog: `GET https://router.huggingface.co/v1/models` with the HF bearer token.
This is the router's chat-model catalog, rather than an unrestricted search of
all Hub repositories. The documented `providers` entries include `status` and,
when available, boolean `supports_tools`. Tool support is confirmed only when
**all listed live providers** explicitly report `supports_tools=true`. Mixed,
missing, false, or offline-only metadata is shown as **unknown**. In particular,
a single tool-capable provider does not establish the capability of every route.
Manual provider/policy suffixes remain usable, but exact IDs absent from the
catalog retain unknown metadata support.

Test: `POST https://router.huggingface.co/v1/chat/completions`, with chat function
schema, `tool_choice=required`, `max_tokens=128`, and `stream=false`. OpenRouter's
`provider` policy is not sent to Hugging Face. HF manages upstream routing under
its own policies. The same completed chat tool-call shape is checked.

Sources: [Router catalog and metadata](https://huggingface.co/docs/inference-providers/hub-api),
[Chat completion schema](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion),
[Routing and authentication](https://huggingface.co/docs/inference-providers/index).

## States, bounds, and secret handling

The UI shows loading, catalog success (including empty/no matching results),
verified connection/tool call, tool-call-unconfirmed, authentication/permission,
rate-limit/quota, unavailable model/route, billing, invalid request/response, and
provider/connection-unavailable states. Provider HTTP 401/403, 429, and 404/410
map to the corresponding named states. A 400/422 is deliberately generic:
without exposing provider messages it cannot reliably distinguish an invalid
model, unsupported parameter, or other rejection.

A small output limit may truncate reasoning or a tool call. Plain text,
incomplete output, invalid arguments, and unexpected success response shapes
are **unconfirmed**, not evidence that tools are unsupported. Successful testing
is one observation, not a guarantee about future calls, all routes, model quality,
full agent conversations, or evaluator integration. Testing never upgrades the
catalog's metadata claim.

The transport uses the standard library `http.client` with fixed HTTPS URLs,
a 20-second socket timeout and an 8 MiB response bound. It follows no redirects,
uses no SDK/environment credentials, and performs no automatic retries, catalog
pagination, or extra model-detail requests. An oversized/malformed response
fails explicitly. IDs outside the setup's existing safe 128-character model-ID
format are omitted; no model is auto-selected. Catalogs are fetched afresh only
on demand, not cached on disk or automatically refreshed.

All three POST actions require the existing loopback Host, same Origin, and
setup CSRF token. `/test-connection` additionally requires JSON boolean
`confirmed: true`; rejection occurs before reading a credential. The UI locks
controls while requests are pending to prevent duplicate clicks and stale
provider results. GET requests cannot trigger discovery or testing.

Only explicit provider actions read a saved key server-side. They read only the
selected provider's file; no reuse of another provider's key or environment key
fallback occurs. Symlink/non-regular secret files are rejected. Keys never appear
in status responses or browser storage. Typed keys remain in the masked field
until save or provider switching; the browser must send them to the local server
when used. Saved keys are never returned. Catalog responses expose only validated
IDs, a capability enum, and a fixed capability explanation, omitting an ID that
contains the active credential. Provider-generated text, raw metadata, error
bodies, headers, and exception strings are never returned to the browser or logged.
Secrets retain the existing plaintext, owner-permission-protected storage model;
this change does not add Keychain/encryption.

## Integration handoff

New module: `godseye.provider_discovery`. It does not import the standalone
container adapter, evaluator, or budgets. No changes are needed to Compose,
`isolation/agent_adapter.py`, the shared roadmap, or budget code to use local setup.
The existing environment exports remain:

- `REPAIR_AGENT_PROVIDER` and `REPAIR_AGENT_MODEL`
- `REPAIR_AGENT_KEY_FILE` (path only, never the value)
- `REPAIR_AGENT_ROUTING`

The local HTTP API is additive:

- `POST /models`: `{provider, key?, model?, routing?}`. Returns
  `{state:"success", provider, models:[{id,tool_support,tool_support_source}], message}`.
- `POST /test-connection`: `{provider, model, key?, routing?, confirmed:true}`.
  Returns `{state, connected:true, tool_call_verified, requests:1, output_limit:128, message}`.
- Fixed provider failures return HTTP 502 with `{state,error}`; request validation
  or missing confirmation returns HTTP 400. Existing security rejections retain
  HTTP 403. No error body or token from upstream is exposed.

A blank/omitted key uses the selected saved key. Both actions are read-only with
respect to local settings, so a successful check does not switch the active
profile. Save separately to export the chosen provider/model/routing for the
adapter. The next agent should continue using the existing exports and rebuild
the agent image only if adapter code changes. If the adapter's request schema or
routing policy changes, reconcile this module's separate probe schema explicitly;
do not import setup code into the standalone restricted adapter.

Some older passages in `isolated-evaluator.md` describe the previous setup as
making no external requests. That remains true for opening/saving, while the
new explicit actions behave as documented here; the shared guide and roadmap
were deliberately left for the integrating agent to reconcile.

## Validation

```sh
python3 -m unittest discover -s tests -p 'test_provider*.py' -v
node --check godseye/static/provider-setup.js
```

23 tests cover provider-specific catalogs and payloads; conservative metadata;
strict confirmation; single-request output limits; incomplete/malformed calls;
redirect rejection; timeout, response-size, HTTP/auth/rate-limit handling;
credential redaction; loopback/Origin/CSRF protection; dummy saved-key selection;
unchanged profiles/settings during discovery/testing; legacy profile migration;
and existing routing/secret permissions. All transports are mocked and all
credentials are dummy values in temporary directories.

An ego-browser check against a separate temporary mock server verified search,
selection, manual-ID retention, cancellation without a test request, confirmed
success, unavailable-model messaging, provider profile/routing restoration,
OpenAI's unknown capability labels, and empty local/session storage. The server
was stopped afterward. No real provider request, saved user key read, or experiment
was performed. Live account/model compatibility remains untested by design.
