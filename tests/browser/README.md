# Live goal browser integration

From the repository root, using Python 3.9–3.12 with `.[dev]` installed:

```sh
PYTHONPATH=. python tests/browser/goal_backend.py
# In another terminal, with ego-browser installed:
ego-browser nodejs < tests/browser/goal_journey.cjs
```

The backend binds only `127.0.0.1:8879`. Stop it with Ctrl-C after the test;
its temporary directory is then removed. Do not point the browser test at an
operator service. `/__fixture/*` routes exist only in this test fixture.

This runs the actual browser, production static UI and real five-operation HTTP
service. The acceptance scripted worker uses the real adapter and tiny evaluator
rollouts, temporary provider settings, and scripted provider responses. Outbound
urllib/httpx provider transports throw. No default settings or saved credentials
are read. No paid provider or Docker calls are made. This does not test isolation.

Assertions cover real expired-plan rejection using an injected service clock, explicit
Review again without execution, fresh review and renewed confirmation, preservation
of uncertain start tuples, review versus explicit start, review invalidation, review reload,
duplicate start, actual root-selected negative measurements, terminal reload,
malformed/lost start acknowledgment, retained exact tuple, explicit reconciliation,
running and cancelling reload, cancellation acknowledgment, unknown activity,
5/10/20-second bounded retries across changing error codes, exhausted-retry reload,
service unavailable, adapter budget exhaustion, separate mock transport, and the
one-click CPU example with the original checkpoint preserved. The test waits for
observable UI conditions and does not replace the browser's timers or fetch.

The fixture's dropped acknowledgment occurs **after real admission** and replaces
the response with incomplete JSON. Unit tests separately cover transport rejection,
invalid versions, duplicate JSON keys, malformed envelopes, unsafe retry metadata,
unknown usage and inconsistent phase/evidence. A selected checkpoint cannot be
downloaded: the backend has no scoped export route. Known activity phases cannot
be demonstrated by this backend, which returns unknown until its trusted journal
exists. Neither limitation is papered over by a fixture download or fabricated phase.

The compact `experimentContract` literal in `static/app.js` is generated from
`experiment_spec.SCHEMAS`, `MESSAGES`, `_SAFE_PATHS` and `retry_guidance`. It is
bundled in the existing served asset because the server intentionally allowlists
asset filenames. Backend and isolation files are unchanged. UI state uses a
separate `godseye.goal-live.v1` tab-storage key; mock mode is selected explicitly
with `?goalMode=mock`. A reload restores drafts but never restores a ready review.
Admitted identities restore via status/results only; an unknown start requires
explicit same-tuple reconciliation. Automatic retries are disabled for recovered
pending actions. Credentials remain in the existing connection control's memory.

Run quick UI checks with `node --test tests/ui/*.test.cjs`.

CI explicitly discovers `tests/browser/test_ui_contract.py` on Python 3.9 and 3.12.
