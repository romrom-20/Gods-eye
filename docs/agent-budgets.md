# Isolated repair agent budgets

The standalone adapter enforces cumulative provider admission limits in addition
to the existing round, tool-call, per-response output, and evaluator budgets.
These are research-run limits based on provider-reported tokens, **not a hard
dollar spending cap**. No prices or free usage are assumed. Configure account-side
billing controls independently before authorizing any real provider use.

## Configuration and defaults

CLI options override the corresponding environment variable. All values must be
positive integers; zero, negatives, fractional values, booleans, and unlimited
sentinels are rejected. Invalid CLI/environment budgets exit 2 before secret reads
or provider requests. Direct `run_agent` callers must pass positive Python `int`
values. The baseline participants do not use provider budgets.

- `--max-requests` / `REPAIR_AGENT_MAX_REQUESTS`: **80** attempted provider requests.
- `--max-input-tokens` / `REPAIR_AGENT_MAX_INPUT_TOKENS`: **200000** cumulative reported input tokens.
- `--max-total-output-tokens` / `REPAIR_AGENT_MAX_TOTAL_OUTPUT_TOKENS`: **20000** cumulative reported output tokens.
- `--max-seconds` / `REPAIR_AGENT_MAX_SECONDS`: **900** elapsed monotonic seconds.
- `--max-rounds` / `REPAIR_AGENT_MAX_ROUNDS`: **80** rounds, each admitting at most one provider request.
- `--max-calls` / `REPAIR_AGENT_MAX_CALLS`: **160** model-requested evaluator tool calls.
- `--max-output-tokens` / `REPAIR_AGENT_MAX_OUTPUT_TOKENS`: **2000** requested output tokens per provider response.

Compose forwards these seven variables with the same defaults. For example,
set the following in the trusted operator's environment before using the existing
launch flow in [isolated-evaluator.md](isolated-evaluator.md):

```sh
export REPAIR_AGENT_MAX_REQUESTS=20
export REPAIR_AGENT_MAX_INPUT_TOKENS=50000
export REPAIR_AGENT_MAX_TOTAL_OUTPUT_TOKENS=5000
export REPAIR_AGENT_MAX_SECONDS=300
```

Rebuild the agent image after integrating this adapter. Existing provider, model,
routing, secret-file, and evaluator launch configuration remains applicable.
The adapter still consists of one standard-library-only file. No evaluator
imports, mounts, endpoints, tools, network boundaries, retries, or provider
fallbacks are added. Evaluator development probe/forward reservations and freeze
rules remain enforced independently by the evaluator.

## Admission and accounting

Before every provider request the adapter checks elapsed time, attempted
requests, cumulative input/output tokens, tool calls, and the round ceiling.
Equality exhausts a limit. A request is counted and its reservation fsynced to
evidence **before** invoking provider transport; errors never refund it. Each
response is accounted before its tools can execute. Valid token usage requires
both nonnegative integer fields `input_tokens`/`output_tokens` (Responses), or
`prompt_tokens`/`completion_tokens` (chat completions). Both naming pairs, if
present, must agree. `total_tokens` alone cannot establish separate totals.
Zero counts are accepted; token details such as cached/reasoning counts are not
added again. Accounting trusts the reported aggregates and cannot verify them.

The admission check uses usage already received. **Reported-token accounting can
overshoot a limit by one in-flight request**, including that request's full input
context and output. The per-response output parameter remains unchanged and is
not a reservation against the cumulative output allowance. Provider billing may
include quantities outside these counters. These limits do not reserve money,
estimate prices, or guarantee that inference costs nothing.

When valid usage reaches a request/token limit, the current response's tools may
finish within tool/time limits; another provider request is forbidden. A final
response with no tools may still complete the run if all cases are frozen.
Nothing automatically freezes cases on exhaustion. Simultaneous exhaustion uses
this reason precedence: elapsed time, requests, input tokens, output tokens,
tool calls, then rounds. Elapsed time also gates each tool execution and response
processing. It starts when the claimed agent run begins, including evidence and
provider/tool latency, but excludes CLI configuration/secret loading.

Elapsed time is a cooperative admission ceiling, not a process watchdog or
remote cancellation guarantee. A synchronous provider or evaluator request can
finish after the deadline (the existing HTTP transport uses a 120-second socket
timeout, not a hard whole-request deadline). Its reported usage is still recorded;
no further tools/provider requests are admitted after expiry. Stopping a client
cannot prove that a remote provider stopped work or stopped billing.

## Failure policy and evidence

Missing/malformed usage stops immediately with `missing_or_malformed_usage`;
no tools from that response execute and no further request is sent. Complete
usage pairs from earlier responses remain in totals; `usage_complete=false`
marks unknown additional consumption, rather than treating it as zero.
Transport errors stop with `provider_request_failed`. A rejected/incomplete chat
response retains usable reported counts even though routing raises an error.
An incomplete/error Responses payload with usable usage records that usage and
stops with `provider_response_incomplete`. No automatic retry or fallback occurs.

Catchable provider interruption (`KeyboardInterrupt` or `SystemExit`) records
`provider_request_interrupted` and re-raises. A transport failure or interruption
leaves `request_in_flight=true`: remote execution/charges are unknown. SIGKILL,
default SIGTERM, host loss, or evidence disk failures may prevent a terminal row;
the last fsynced `request` row then represents an unresolved request. Never infer
zero usage from a missing response. A process killed between reservation and
transport may conservatively count a request that was never sent.

The `start` row contains selected limits. `request`, `response`, completion and
stop rows contain cumulative requests, normalized input/output counts, model
tool calls, elapsed seconds, usage completeness, and in-flight status. Explicit
budget stop reasons are `provider_request_limit`, `input_token_limit`,
`output_token_limit`, `elapsed_time_limit`, `tool_call_limit`, and `round_limit`.
Early model termination uses `agent_stopped_before_all_freezes`; other adapter
failures use `runtime_failure`. Existing model/route metadata and tool evidence
remain. Raw usage extras and provider exception text/bodies are not copied into
accounting evidence. Credentials never enter provider model input or budget
records. Evidence is exclusive, incrementally flushed and fsynced; unavailable
evidence prevents further admission. Treat all evidence as private research data.

## Restart and resume

**Resume is unsupported.** One dedicated evidence directory identifies one agent
run, paired with its fresh evaluator state. Before admitting work the adapter
exclusively creates and fsyncs `.agent-run.claim` in that directory. Every later
agent invocation in the same directory is rejected with `resume_rejected`, even
if given another JSONL filename, higher limits, or a different provider. This
also prevents concurrent invocations in that directory. Reusing an existing
JSONL path is already refused by exclusive evidence-file creation. Failures,
interruptions, and successful runs all retain the claim. Even a crash before
sending the first request leaves the run non-resumable.

Keep the evidence bind mount and its claim across Compose restarts. Never delete
the claim, rename/change the evidence directory, or point a new evidence directory
at the same evaluator run to bypass refusal. Run identity here is operator-managed
filesystem state; the standalone adapter has no trusted global registry and
cannot detect deliberate replacement/loss of that state or an alternate mount.
This is not a tamper-resistant spending control. A new agent run requires fresh
private evaluator state and a fresh dedicated evidence directory. Do not reset
evaluator reservations or reuse a run to cherry-pick repairs. Baseline participant
files may share the directory; they do not claim an agent run.

An incomplete budget stop returns exit 1, missing configuration/invalid CLI
configuration returns exit 2, and completion returns 0. Provider/runtime failures
raise a redacted `RuntimeError` (CLI exit 1). Catchable interruption retains its
normal process exit behavior. Resume rejection returns exit 1 when a fresh
JSONL filename allows a rejection record; reusing the original filename fails
before opening it and preserves the original evidence.

## Offline integration checks

```sh
python3 -m unittest discover -s tests -p test_agent_budgets.py -v
python3 -m unittest discover -s tests -p test_provider_routing.py -v
```

Budget tests use fake providers and clients, deterministic clocks, temporary
files, and dummy values; they require no saved keys, provider requests, Docker,
or repair experiment. They cover boundary equality, overshoot, zero reports,
malformed/missing reports, errors, interruption, durable reservation ordering,
resume refusal, configuration validation and redaction.

Existing scripted evaluator/container provider fixtures that omit usage must
supply synthetic complete usage on **every** response, including the last empty
output response, for example `usage={'input_tokens': 1, 'output_tokens': 1}`.
Their omission now intentionally stops the agent. This fixture integration is
required before expecting those completion tests to pass; it does not justify
relaxing accounting for real providers. The legacy evaluator tests and provider
setup/discovery files are outside this change's ownership.
