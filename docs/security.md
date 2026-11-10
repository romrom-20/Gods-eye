# Local security contract

The server is a single-user local research tool. `godseye serve` binds to
127.0.0.1 and refuses writable non-loopback binding. Do not put it behind a
public reverse proxy. `--demo` serves public bundled evidence read-only;
`export-demo` produces static files and is the preferred public demo path.

## Implemented protections

- Allowlisted Host header, same-origin requests, rejection of cross-site Fetch
  Metadata, no permissive CORS, and no executable patch language.
- A streamed 64 KiB body limit before JSON parsing; strict typed request fields;
  finite weight bounds, exact tensor shapes, and at most 200 assignments.
- Optional `GODSEYE_API_TOKEN` checked with constant-time byte comparison on all
  API routes. Tokens stay in browser memory and are not persisted by the UI.
  This token is a single-user secret, not a tenant or role system.
- Parent hash preconditions, immutable checkpoint copies, metadata published
  after tensor data, atomic file replacement, and path-constrained artifact IDs.
- One worker, four active/queued jobs, a 250,000-forward-call admission budget,
  and cooperative cancellation at each MinAtar step. Job status survives
  restart; unfinished jobs become `interrupted`, not silently replayed.
- 256 MiB storage admission limit. Already admitted work can cross that limit;
  there is no OS-level quota or automatic deletion.
- Self-hosted scripts/styles, CSP, frame denial, no external fonts or analytics,
  and no arbitrary user HTML interpolation.

## Known limits

The job worker is a thread in the server process, not a sandbox. Only the
trusted bundled backend is exposed by the web server. CLI-installed backends
are trusted Python with the user's permissions. Public plugin installation or
uploaded executables would invalidate this boundary.

Run exactly one server process per writable workspace. The queue is not a
distributed scheduler; two processes would not share admission locks. The API
bounds work but does not rate-limit a malicious local process. Admission
quotas do not bound HTTP concurrency outside the documented CLI server.

Filesystem ownership is the OS user's responsibility. The local user can
alter checkpoint files and run JSON directly. SHA256 detects tensor equality;
it is not a signature. Atomic replacement prevents partial file reads but does
not make the entire multi-file checkpoint creation a database transaction.
An interruption can leave an unreferenced tensor file. Cancellation after
result publication returns success, because the complete artifact already
exists. Job status and result publication are separate atomic writes: a crash
between them can leave a saved run whose job is marked interrupted on restart.

Network-level request deadlines, distributed rate limits, OS resource caps,
worker isolation, per-tenant authorization, retention enforcement, transactional
job/result publication, and a tamper-resistant audit log are prerequisites for
a public execution service. See [roadmap.md](roadmap.md).

## Verification

`python -m unittest discover -s tests -v` exercises executable/malformed patches,
invalid types, work budgets, missing/path-traversal IDs, Host/Origin rejection,
request-size/content-type restrictions, optional tokens, read-only demo,
immutable previews, parent hashes, idempotency conflicts, cancellation, queue
capacity, restart handling, and static export boundaries.

Use synthetic inputs for security reports. Never include private model weights,
API keys, or user data in a public issue.

## Repair evaluator boundary

The optional [isolated repair evaluator](isolated-evaluator.md) runs the private
weights/state in a separate container and gives the model only authenticated,
scoped tensor/patch/probe/freeze tools. It is separate from the single-user lab.
Host/daemon operators remain trusted. The source-free agent image has no private
volume, repo mount or shell tool. The container boundary has an opt-in Docker
test; same-user HTTP tests do not establish filesystem isolation. Container and
real-agent execution were unavailable on the implementation host, and no
production security claim is made.
