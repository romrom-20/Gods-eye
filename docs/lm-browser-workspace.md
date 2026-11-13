# Local Qwen browser workspace

This child-branch slice adds `/lab#language-model` using only the frozen
[service contract](lm-browser-service-contract.md). The Qwen navigation entry opens
a full-width workspace and hides the Breakout board and inspector. Returning to a
Breakout view restores them. Existing controllers, local CPU example, checkpoint
import, board layout controls, recorded playback and export asset list are retained.
The initial scripted UI slice performed no inference, provider call, dependency
installation or weight download. The separately authorized real integration below
subsequently exercised one local model run.

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

## Actual service/browser integration — 2026-11-13

The child branch merged local main `b3c4330`, including the actual LMService
(`2a41313`, coordinator integration of `efe4722`), before this separately authorized
execution. This check reproduced the fixed public task through the actual browser
transport; it is not an independent heldout quality experiment or tuning run.
No LM route/response was intercepted, no runtime/scorer/backend code was changed,
and no UI integration defect required a product fix.

The actual app used a temporary Breakout Store and a new private 0700 LM directory
under `/tmp/godseye-lm-browser-integration-20261113-01`. Only its dedicated
`127.0.0.1:18997` server was started. Operator configuration used the existing cache
`/tmp/godseye-lm-local-real-20261113/weights` and isolated interpreter
`/tmp/godseye-lm-local-venv/bin/python`. No token/key material, other running
servers, provider/cloud/GPU services, dependencies or weights were accessed or
changed beyond the authorized local runtime and its in-deadline validation.

The browser proved page load and preview had zero jobs and zero journals. The
server's canonical TaskSpec hash
`3a49a9cd1b743ba8935582e1e22673bf402d80e68a6136e559dd75fdf73aa08d`
passed review. Keyboard consent and explicit Start admitted exactly one job:
`44ba98e5-8d7a-4399-b95e-5acc9e238fc4`, created
`2026-11-13T01:56:04.550408Z`, terminal `2026-11-13T01:56:45.503900Z`.
Actual development progress included 19 finished/20 reserved, then 45 finished/46
reserved. Those intermediate observations came from read-only service HTTP
status during browser polling; screenshots capture the actual queued 0/0 and
terminal UI states. No intermediate-state screenshot was staged or recreated.

It terminated naturally as `failed/budget_limited`, report
`incomplete/not_evaluated`: 70 reserved and recorded development calls, 69 complete
responses and one decoding `dev-inventory` response capped at 96 tokens. There
were zero heldout calls, interrupted reservations or retries, no persisted freeze,
selected edit, selected-delta file or fresh selected-model reload. Usage was 6,515
input and 1,154 generated tokens including EOS. The worker reported 38.10 seconds;
admission-to-terminal elapsed 40.95 seconds. These timings are transport
reproduction observations, not speedup evidence. The CPU runtime used two threads;
its lifetime peak RSS was 3,402,596,352 bytes, including loading.

Observed development counts (10 JSON targets and 4 text controls per variant):

- Unchanged: 3 schema-valid, 1 semantically correct, 4 controls correct.
- Prompt: 1 schema-valid, 0 semantically correct, 4 controls correct.
- Decoding: 3 schema-valid, 1 semantically correct, 4 controls correct; incomplete arm due to the cap.
- Column 0 × 0: 2 schema-valid, 0 semantically correct, 4 controls correct.
- Column 1 × 0.5: 2 schema-valid, 0 semantically correct, 4 controls correct.

The UI truthfully displayed “Not evaluated”, zero heldout attempts, the token
limit, observed control counts/regressions, and no selected delta. Original and
candidate response strings exactly matched the service attempts, including the
partial 96-token response. Downloaded evidence JSON exactly equaled the service
result envelope. A separate stdlib check verified all 155 journal event hashes,
finish/report identity, all 70 attempt/spec bindings, equality of journal records
with raw report/service/download attempts, and all five exact rollback boundaries.
The journal file SHA256 is
`d6456ddb32a56a07e540ff80a3443250ed87a5420f153d2d62aef8d779f353a0`;
attachment SHA256 is
`970ba7b1c0fdde6539eda8cbdc2e105378b4e2e9780e9defe2ee366f0397891c`.
Original and final tensor hashes both remain
`cdba20f7429dd67092a8861e2d3d51e28318ecd4a6b007e7f417f1c5aeac3ee5`.
Weights were not rehashed outside the authorized worker validation.

Reload, history selection and read-only resolution with the recorded admission key
reopened the same job; the final audit contains exactly one Start POST and no
cancellation POST. Desktop and 390px mobile reading had no horizontal page overflow.
The real 13-file static export made zero API requests with both mock flags.
Desktop review/results and mobile workspace/capped-response screenshots were
visually inspected. Screenshots, actual attachment, HTTP audit, installed versions,
raw journal/report and browser verification are retained in that private directory.
See [the compact integration evidence report](lm-browser-integration-evidence.json)
for hashes, identities, environment, counts and screenshot filenames.

The incoming selected-delta attachment fix was merged from local main `f9c8a28`
(coordinator integration of `f18c78f`) only after the real job terminated. It did
not restart the job or generate additional text. The existing synthetic actual-HTTP
selected-delta download/save/direct-load test passed against the corrected code.
Real selected-delta behavior cannot be claimed from this no-selection run.
Existing synthetic process tests supplied cancellation and lost-ACK coverage;
no extra pretrained run was used to exercise those paths.

Commands for this authorized integration (the new real fixture refuses an existing
evidence directory; the browser driver records a durable one-Start intent and
reuses any admitted job read-only):

```sh
GODSEYE_LM_CACHE=/tmp/godseye-lm-local-real-20261113/weights \
GODSEYE_LM_PYTHON=/tmp/godseye-lm-local-venv/bin/python PYTHONPATH=. \
/tmp/godseye-goal-contract-venv/bin/python tests/browser/lm_workspace_real_backend.py \
  --directory /tmp/godseye-lm-browser-integration-20261113-01 --port 18997
ego-browser nodejs < tests/browser/lm_workspace_real_journey.cjs
python3 tests/browser/lm_workspace_real_verify.py /tmp/godseye-lm-browser-integration-20261113-01
node --test tests/ui/*.test.cjs
PYTHONPATH=.:tests /tmp/godseye-goal-contract-venv/bin/python -m unittest \
  test_lm_service.ServiceTests.test_simultaneous_duplicate_start_lost_ack_and_no_backlog \
  test_lm_service.ServiceTests.test_cancel_waits_kills_and_retains_partial_evidence \
  test_lm_service.ServiceTests.test_real_http_selected_delta_download_loads_without_unwrapping -v
PYTHONPATH=. /tmp/godseye-goal-contract-venv/bin/python -m unittest discover -s tests/browser -p test_ui_contract.py -v
```

The 106 focused UI checks, bundled contract check and three named synthetic service
checks passed. The browser task was finished and the owned server was stopped only
after confirming its one terminal job and no child process; evidence/cache remain
intact. Ego Lite reported an update; no upgrade was performed. There is no useful
selected edit or new heldout quality claim, and no new execution is authorized by
these reproduction results.
