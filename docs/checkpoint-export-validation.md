# Checkpoint export validation

Executed locally with Python 3.12 and the repository's dev dependencies, based on
origin/main `81a85d2`. No real provider calls, discovery, operator credential reads,
Docker execution, deployment, tags or main push were performed. Tests prohibit
outbound transport; the unchanged fixture uses temporary dummy provider settings,
and the changed fixture and standalone example access no provider settings at all.

Commands:

```sh
python -m unittest discover -s tests -p test_checkpoint_export.py -v
python -m unittest discover -s tests -v
ruff check godseye/checkpoint_artifact.py godseye/checkpoint_export.py godseye/checkpoint_example.py godseye/server.py tests/test_checkpoint_export.py
git diff --check
python -m godseye.checkpoint_example --output /tmp/new-checkpoint-example
```

Dedicated suite: **8 tests passed**. Full suite: **182 discovered, 165 passed, 17 skipped**
(the opt-in Docker worker/evaluator/local setup tests). Ruff and whitespace checks
passed. The no-key example downloaded and reloaded **4** checkpoints, of which
**1** changed after a real development improvement; the overall measured held-out
verdict was **inconclusive**. Random run/manifest identifiers mean the artifact
content hash changes across invocations even when tensor hashes and scores match.

Executed checks include:

- Real HTTP attachment export, independent reload in a fresh Python process,
  original/selected hash equality, all paired held-out episode scores equal to the
  original selected checkpoint, exact delta reconstruction and original rollback.
- Earlier completed root probe and strict development improvement for every changed
  selection; a fixture that skips the root probe fails completion and cannot export.
- Explicit unchanged selections and empty deltas, original `paper` preservation,
  and byte preservation of registered original/reference checkpoint files.
- Bearer authorization, Host, Origin, cross-site and recorded-readonly refusal;
  same-service foreign manifest, foreign-service run and path traversal refusal.
- Missing, tampered and symlinked private artifacts, altered artifact path mapping,
  modified original and selected tensor files, malformed schemas and duplicate keys.
- Strict finite float32 values, shape/count/header/dtype/ZIP expansion checks before
  tensor allocation, wrong hashes, bad replacement preconditions, extra properties,
  and signed-zero-preserving replacement deltas in the independent loader.
- Repeated downloads return identical bytes and cannot invoke workers, evaluator
  tools/report, credentials or external transport; public body scans exclude private
  report canaries, secrets, paths and forbidden metadata fields.

Limits: only the fixed Breakout architecture; at most 32 cases per participant and
32 MiB artifact JSON; local filesystem/service operator trusted; content hashes
provide integrity, not authenticity. Browser UI integration belongs to the
coordinator. This fixture demonstrates usable checkpoint export and reproduction,
not intelligent repair, real-provider quality, Docker isolation or research success.
