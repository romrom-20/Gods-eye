# First-use study: five new users

Protocol only. No participants have been observed and no usability results are claimed.
Recruit five researchers/developers who have not used this lab. Run individual
15-minute sessions on the local lab with temporary data, no saved operator keys,
and no paid provider calls. Include one narrow-screen session and one keyboard-only
session. Ask participants to think aloud; do not explain navigation or correct
mistakes until each timed task ends. Record any coaching as an assisted task.

## Tasks and facilitator script

1. “You have no AI key. Find a working example, run it, and explain what changed.”
   Start at `/lab`; stop after the saved paired comparison appears. Record seconds
   to find the example and to first result, wrong turns, errors and assistance.
   Ask which version is original and whether this demonstrates a discovered repair.
2. On the scripted service fixture, provide the dummy model ID
   `scripted-acceptance` and its finite test limits (40 requests, 10,000 input
   tokens, 2,000 total output tokens, 30 seconds, 40 rounds, 80 calls, 100 output
   tokens per response). “Request a Breakout score improvement. Before starting,
   tell me which model changes and what authorizes execution.” Ask the participant
   to locate all seven limits, original identity, evaluation conditions and exact
   specification hash. Do not start anything on a real configured operator server.
3. “Change one limit after review, review again, and start only when satisfied.”
   Record whether confirmation clears, whether a fresh review is completed, and
   whether the participant understands review itself makes no AI call.
4. Use a blocked scripted run with a deliberately lost start acknowledgment.
   “Reload, find out what happened, then cancel.” Record whether the participant
   uses reconciliation instead of attempting a new run, and distinguishes an
   acknowledgment of cancellation from a guarantee about remote provider charges.
5. “Explain this completed result and find the download.” Use a completed scripted
   result; ask for measured outcome, original preservation, sample count,
   uncertainty and control regression evidence. A fixture selecting unchanged
   roots is expected to show no improvement. Ask the participant to request an
   unsupported target (for example, editing Qwen) and explain the response.

## Measurable acceptance

At least four of five participants complete the supported journey without coaching,
find the no-key example within 60 seconds, and reach its saved result within five
minutes (record machine/runtime separately). At least four correctly distinguish
target from programmer, enumerate seven limits before Start, and explain that
completion alone does not establish improvement. At least four locate original
preservation, sample count, uncertainty, regression evidence and the download
within two minutes of the result. All five must avoid an unintended start; any
such event is a release blocker. Keyboard and narrow-screen tasks must have no
unreachable required field, trapped focus or horizontal page overflow.

Record one row per participant/task: elapsed time, unassisted success, assistance,
wrong turns, exact confusing wording, failure point and suggested fix. Report
counts out of five and anonymized observations, including failures. This small
study is a product check, not proof of broad usability or intelligent repair.

## Engineering evidence (2026-11-11)

Automated checks exercise the real local CPU path with no configured orchestration
service, plus the actual scripted worker/evaluator fixture. Temporary fixtures
block outbound provider transports and use dummy credentials only. They do not
establish provider compatibility or repair quality. All 50 Node UI checks and the Python bundled-contract check passed. The real
unconfigured CPU browser path passed, and the scripted browser journey passed
unsupported-goal handling, keyboard/invalid-field focus, seven-limit review,
duplicate start, expired-plan recovery, uncertain-start reconciliation, reload,
cancellation, real 5/10/20-second backoff, adapter budget stop, service unavailability,
mock separation and original preservation. UI checks retain exact spec
hash confirmation, bounded retry tuples, unknown-admission reconciliation,
reload/cancel behavior, activity gap fences, demo/mock gating and safe download.

Reproduce the focused checks from the repository root:

```sh
node --test tests/ui/*.test.cjs
python -m unittest discover -s tests/browser -p test_ui_contract.py -v
GODSEYE_BROWSER_PORT=18980 PYTHONPATH=. python tests/browser/first_use_backend.py
# Separate terminal; stop only the fixture server you started afterwards:
ego-browser nodejs < tests/browser/first_use_journey.cjs
GODSEYE_BROWSER_PORT=18979 PYTHONPATH=. python tests/browser/goal_backend.py
# goal_journey.cjs defaults to 8879; substitute its base URL with 18979 in a
# temporary copy when running a dedicated port, then pass that copy to ego-browser.
```

Browser screenshots are written to `/tmp/godseye-first-use-request.png`,
`/tmp/godseye-first-use-mobile.png`, `/tmp/godseye-first-use-review.png`,
`/tmp/godseye-first-use-result.png`, and `/tmp/godseye-first-use-cpu-result.png`.
They are local engineering artifacts, not participant evidence. The live service
still requires explicit operator setup; the no-key mechanics example is a separate
experiment. No compare/adopt/try-again execution is advertised for live results.
