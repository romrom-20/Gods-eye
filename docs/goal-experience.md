# Goal experience

The default `/lab#goal` view guides a user through describe → review goal and
limits → explicit start → progress/cancel → result/compare/keep original.
The existing Overview, Tensor lab, Evaluations, Run history, recorded demo, and
local four-weight preset remain accessible. No backend/provider/adapter changes
are part of this branch.

## Implementation status

**The entire natural-language journey is mocked.** Planning, start, progress,
status reconnection, cancellation, outcomes, comparison, and keeping the original
are local UI actions. They make no network requests, read no provider settings or
saved keys, create no checkpoints, and consume no programmer requests. Progress
only advances when the user presses “Show next sample step”; no timers impersonate
work. No numeric result, patch, artifact, price estimate, or improvement is invented.
Keeping the original acknowledges that this mock changed nothing.

The page's pre-existing initialization still reads the local lab API for tensors,
checkpoints, jobs and recorded runs. The separately accessible tensor/evaluation
controls still perform real local operations only when explicitly used. They do
not call a programmer provider. The no-key guided example opens the existing
four-weight ablation preset, instructs the user to preview/apply it and explicitly
compare it with `paper`. Static visitors can inspect recorded evidence; execution
requires the local server. This known-circuit example establishes mechanics, not
AI discovery or repair quality.

## Contract coordination

Read `docs/roadmap.md` and the published version-1
`docs/experiment-contract.md` in the neighboring `goal-contract` worktree while
implementing this branch. That contract was available during implementation but
is not yet committed on this UI branch. It defines transport-neutral messages,
not live HTTP endpoints. Do not invent endpoint names or send the UI's illustrative
plan to the existing evaluation API as though it were a runnable experiment.

The UI follows its conservative normalization/three-phrase allowlist. Other
Breakout wording asks for clarification; non-Breakout wording is unsupported.
Request text is displayed using `textContent`, never executed or parsed as HTML.
The editable target is Breakout; programmer selection does not make a programmer's
own weights editable. The repair baseline is the registered case roots, distinct
from the clean `paper` checkpoint in the guided example.

Advanced options expose a dummy programmer provider/model, route preference and
all seven limit concepts: request count, reported input tokens, total reported
output tokens, elapsed seconds, rounds, tool calls, and output tokens per response.
These map respectively to `max_requests`, `max_input_tokens`,
`max_total_output_tokens`, `max_seconds`, `max_rounds`, `max_calls`, and
`max_output_tokens`. The review repeats selection and limits. The placeholder
`explicit-tool-model` asserts no availability or tool compatibility. All limits
are illustrative; no live spending is authorized. Unknown provider charges stay
unknown. No automatic retries, provider fallback, connection checks or catalog
loads occur.

A future integration must replace the mock controller with strict version-1
message validation, registered baseline/suite identity, actual evaluation limits,
server-issued draft/spec hash, atomic idempotent admission, authenticated scoped
run identity, status/cancel/results operations, and verified evidence/artifact
references. Bind confirmation to the exact reviewed spec; changes require a new
review. Reject stale/unknown versions and invalid responses without discarding the
draft or launching work. Never expose private seeds, labels, keys, paths, or raw
provider errors. Existing evaluator and provider setup retain their own owners.

Execution status and evidence verdict are separate. A complete real report can
show improved, no improvement or inconclusive. Improvement requires positive
paired mean, mean minus two standard errors above zero, and no control regression;
the rule is descriptive, not a calibrated significance guarantee. Missing evidence
is not zero. The current mock's completed response has no measurements and is
explicitly labeled improvement unproven, **not** a valid `results_response`.
Likewise the mock has no canonical `spec` or valid `ready` plan.

## Recovery and interaction

- Review does not start execution. A separate checkbox and start button are
  required; editing a goal/selection/limit invalidates the previous review.
- Active mock walkthroughs lock the draft and options against accidental changes;
  repeated starts cannot restart them. Cancellation ends only the mock. Copy
  explains that real cancellation needs worker acknowledgment, not a closed tab.
- Advanced scenarios cover unsupported requests, clarification, programmer
  unavailability, planning rate limits, budget exhaustion, execution failure,
  disconnect/reconnect and interruption. No recovery action silently launches work.
- Draft text, programmer selection and numeric limits are saved in this tab's session storage. Storage
  failures leave the in-page draft intact and advise copying it before reload.
  There is no cross-device or closed-tab recovery guarantee. Reload restores the
  draft but never confirmation or execution; a previously active mock is marked
  interrupted. No saved provider keys are accessed.
- Status uses a polite live region; controls have labels and visible keyboard
  focus. Advanced options and the guided instructions use native details/summary.
  Layout stacks on small screens. No animation is required to understand progress.

## Checks

Run the offline UI checks:

```sh
node --check godseye/static/app.js
node --test tests/ui/goal_experience.test.cjs
```

The dedicated tests execute the actual mock controller with minimal DOM/storage
adapters and fail on any network/API access. They exercise authorization,
duplicate starts, review invalidation, conservative interpretation, failure and
recovery scenarios, no-evidence completion, comparison, keeping the original,
reload interruption and unavailable storage. They are not a real service
integration or a usability study.

Browser QA uses a temporary local HTTP server (no provider connection). Check the
sample flow through comparison, keyboard labels/focus, native form bounds,
390px layout without horizontal overflow, reload recovery, scenarios, and the
four-weight preset navigation. For actual guided CPU execution use an isolated
`GODSEYE_DATA_DIR`, start the local server, preview/apply the preset, explicitly
run a small comparison and inspect the saved result. Never use a saved provider
key for these checks.

Verification on this branch (2026-11-10): 14 dedicated UI checks passed,
`node --check` passed, and all 10 existing `test_platform.py` tests passed.
Browser QA verified sample completion/comparison, all error scenarios, native
limit validation, zero network requests from mock actions, interruption after
reload, and desktop/390px layouts without horizontal overflow. A separate local
server with an isolated temporary data directory verified the guided preset:
preview reported 4 changed weights, apply created a child checkpoint, and a real
2-episode, 20-step CPU comparison saved successfully with `paper` still available.
This is a small compatibility smoke test, not evidence of improvement. No provider
calls, saved-key reads, deployment, or formal new-user study were performed.
