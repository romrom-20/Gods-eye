# Local Qwen browser workspace

This child-branch slice adds `/lab#language-model` using only the frozen
[service contract](lm-browser-service-contract.md). The Qwen navigation entry opens
a full-width workspace and hides the Breakout board and inspector. Returning to a
Breakout view restores them. Existing controllers, local CPU example, checkpoint
import, board layout controls, recorded playback and export asset list are retained.
No model inference, provider call, dependency installation or weight download was
performed for this UI work.

## Request and evidence

Use the sample “Improve JSON schema adherence”, review the server's exact fixed
TaskSpec, check the consent box, then explicitly Start. Opening the view checks
capabilities/history only; planning does not load or execute a model. The target is
Qwen/Qwen2.5-0.5B-Instruct on local CPU. The review shows the public 28-case fixture,
two fixed column edits, unchanged/prompt/decoding baselines and finite
126-attempt / 96-output-token / 1800-second ceilings. Expand the specification for
all limits, exact revisions, dataset identity and specification SHA256. Browser
hash verification preserves Python TaskSpec float spelling for scale and repetition
penalty; a changed spec hash cannot enter review.

Observed jobs display the service's phase and finished/reserved attempt counts,
without estimating percent complete. The compact relationship strip contains only
the reviewed specification, actual job ID and reported evidence availability.
Results keep development and heldout separate, distinguish schema-valid JSON from
semantic correctness, show observed control regressions where complete paired
control records exist, and leave unavailable counts unknown. Empty heldout arms
say they were not evaluated. Case/split/variant controls compare actual original
and candidate text via `textContent`; no output is interpreted as markup.

A terminal failure can still expose its evidence JSON. A selected delta button
appears only when the server explicitly reports `selected_delta_available`; it
requires a click and never exports an unused candidate as a selection. Its visible
instructions refer to `godseye.lm.local_delta.load_delta` and `applied` with the
pinned original and matching hashes. The context manager verifies application and
rolls back on exit; reload the untouched pinned original and verify its original
tensor hash for independent rollback. No browser download applies weights.

## Recovery and boundaries

Before the first Start POST, sessionStorage receives only the exact
schema/plan/spec-hash/UUID tuple. It also retains a known job ID; it never stores the
request, full spec, bearer token or model output. Duplicate in-flight Start clicks
are disabled. Any uncertain acknowledgment preserves the tuple and locks fresh
planning. `/resolve` reconciles it without execution; only a contract-v1
`not_found` response permits an explicit same-tuple retry. A bare old-server 404
cannot authorize retry. No automatic write retry or replacement UUID exists.
A rejected expired/conflicting plan can be released only explicitly after resolve
confirms no admission. Browser storage failure prevents dispatch.

Reload reopens the known job or resolves the pending tuple. Status/result responses
are fenced against newer job selections and cancellation, checked against job and
spec identity, and reject malformed attempt envelopes. Polling is bounded to 200
checks, with 5/10/20-second failure backoff before pausing; hidden tabs pause timers.
Refresh status resumes read-only observation. Cancellation needs an explicit click
and remains cancelling until the server confirms its terminal state. Nothing
resumes or retries execution automatically.

Existing Connection settings supplies the optional local API bearer token from
page memory. Unavailable, read-only, 401 and old-server states show actionable
setup text and GitHub documentation links. The operator configures
GODSEYE_LM_CACHE, GODSEYE_LM_PYTHON and GODSEYE_LM_DIR per the contract. Neither
subscription connections nor arbitrary natural-language weight editing are claimed.
Static exports return before registering LM transport handlers: including mock
query flags, they show the local-only explanation and expose no executable LM
actions. All Qwen assets remain inside the existing index/app/style files.

## Deterministic verification

Commands executed in this workspace:

```sh
node --check godseye/static/app.js
node --test tests/ui/*.test.cjs
PYTHONPATH=. /tmp/godseye-goal-ui-venv/bin/python -m unittest discover -s tests/browser -p test_ui_contract.py -v
PYTHONPATH=. /tmp/godseye-goal-ui-venv/bin/python -m unittest discover -s tests -p test_web_assets.py -v
PYTHONPATH=. /tmp/godseye-goal-ui-venv/bin/python tests/browser/lm_workspace_backend.py --port 18996
ego-browser nodejs < tests/browser/lm_workspace_journey.cjs
git diff --check
```

The 80 existing Node UI checks and 26 focused Qwen checks pass (106 total).
The bundled browser-contract check and both asset/export revision checks pass.
The browser journey is an Ego script (top-level await, matching the other journey
files), not a standalone CommonJS Node program.

The dedicated temporary loopback fixture was the only server started for this
work. It calls the real app for existing Breakout reads and creates the real
13-file static export, but intercepts LM routes with **SCRIPTED UI TRANSPORT**.
Its historical evidence input is the committed first/only pretrained validation
artifact: exactly 70 development attempts, one token cap, zero heldout attempts,
`incomplete` / `not_evaluated`, no selected delta. It converts those attempts to
the exact public record envelope, validates them and recomputes the report using
the pure scorer. Job admission, progress and cancellation in this fixture are
scripted, not model execution. The unit-only complete-negative, inconclusive and
verified-availability/export cases are injected transport checks; they do not
establish model quality or a useful edited checkpoint.

The actual browser journey passed: desktop request/review/explicit keyboard Start,
progress inspection, historical token-capped response comparison, evidence download,
read-only reload, lost-acknowledgment reconciliation without a second admission,
confirmed cancellation, Breakout board restoration, mobile width 390px with no
horizontal overflow, setup states, and zero API requests from the actual static
export with `goalMode=mock&lmMode=mock`. The scoped fixture denied LM execution by
construction; no live inference tests or auto-retry execution controls were used.

Screenshots and attachment, stored locally in `/tmp` (all browser runs are scripted):

- `/tmp/qwen-scripted-desktop-request.png`
- `/tmp/qwen-scripted-desktop-review.png`
- `/tmp/qwen-scripted-desktop-running.png`
- `/tmp/qwen-scripted-desktop-result.png`
- `/tmp/qwen-scripted-desktop-responses.png`
- `/tmp/qwen-scripted-mobile-workspace.png`
- `/tmp/qwen-scripted-mobile-result.png`
- `/tmp/qwen-scripted-mobile-responses.png`
- `/tmp/qwen-static-local-only.png`
- `/tmp/qwen-scripted-evidence.json`

Desktop request/result and mobile capped-response screenshots were visually
inspected. Screenshots show scripted transport and replay of historical text;
they are not evidence of a newly executed model experiment. Subsequent small
validation/message refinements were checked with the deterministic UI suite.
Ego Lite reported an available update; no upgrade was performed.

## Remaining integration

The independent backend service commit was not present in this child workspace.
The coordinator must integrate it and separately verify the actual capability,
plan/admission/resolve, cancellation, partial result, and evidence attachment
lifecycle on a dedicated port. Real runtime execution still requires explicit
authorization; these scripted browser checks do not authorize or substitute for
it. In particular, verify the operator setup and selected-delta export/rollback
against real verified service artifacts when such an artifact exists. No useful
selected Qwen edit is claimed by this slice or by the historical run.
