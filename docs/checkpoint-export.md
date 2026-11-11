# Checkpoint export v1

`POST /api/v1/experiments/export` takes exactly
`{"schema_version":1,"experiment_id":"<run ID>","artifact_id":"<candidate_manifest_id>"}`.
Use the completed results' `evidence.candidate_manifest_id`. Existing local operator
Bearer token (when configured), Host, Origin and cross-site checks apply. Recorded
read-only mode refuses export. IDs and content hashes are not credentials. This is
one local operator scope, not tenant isolation.

The JSON attachment has `schema_version:1`, `format:"godseye-checkpoint-v1"`,
`experiment_id`, `spec_hash`, `artifact_id`, `baseline_id`, `checkpoints`,
`instructions:{reload,rollback}`, and `content_sha256`. Each checkpoint contains
`slot` (zero-based display index), `outcome` (`changed` or `unchanged`),
`original_sha256`, `selected_sha256`, `original` (the six named flat float32 numeric
arrays in W1,b1,W2,b2,W3,b3 order), and `delta` (ordered replacements containing
`tensor,index,before,after`). Tensor shapes are fixed by MinAtar Breakout v1.
Replacement values preserve float32 bits, including signed zero; subtraction/addition
would not guarantee exact reconstruction. Roots selected by the agent explicitly
have `outcome:"unchanged"`, equal hashes and empty deltas. The artifact contains only
agent cases: no clean reference checkpoint, other participant reports, case IDs,
labels, seeds, credentials, provider text or filesystem paths.

`content_sha256` hashes canonical JSON of all fields except itself (UTF-8,
`sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False`). It detects
corruption, not operator authenticity: retain its expected value through a trusted
channel. Tensor hashes use core.digest's ordered names and little-endian float32
bytes. The loader requires the externally expected content hash.

Only completed runs with complete trusted evidence export. Membership, registered
roots, frozen selections, prior successful root-before-candidate comparisons,
manifest/delta/report consistency and tensor hashes are checked on every read.
Missing, foreign, tampered or traversing IDs/files fail closed with the existing v1
safe error envelope (404 not_found); incomplete runs return 409 result_not_ready.
Malformed requests return 400. These reads do not invoke providers, workers,
evaluation, repairs, reveal or retries. v1 plan/status/results remain unchanged.

`godseye.checkpoint_artifact.reload_artifact(raw, expected_sha256=...)` independently
validates the bounded strict JSON schema, numeric sizes, exact float32 values,
finite tensors, replacement preconditions and original/selected hashes, returning
independent `(original, selected)` array pairs. Original arrays are never mutated.
Use core.save_weights to save selected or original as a non-pickle NPZ accepted by
the existing Breakout loader. Do not overwrite the original checkpoint. Rollback
means loading the exported original and verifying original_sha256. Export JSON is
at most 32 MiB, at most 32 cases, exactly 20,486 parameters per checkpoint, and no
executable expressions, archives, URLs or user-controlled filenames. Internal NPZ
sources are independently bounded before NumPy opens them.

No-key reproduction and executable acceptance: run
`python -m unittest discover -s tests -p test_checkpoint_export.py -v`.
The tests build temporary evaluator suites, run local real rollouts with scripted
numeric selections, download via HTTP, independently reload in a fresh Python
process and compare hash and paired evaluation with the selected checkpoint.
They do not claim intelligent repair, paid-provider performance or container isolation.

Request schema: [checkpoint-export-request-v1.schema.json](checkpoint-export-request-v1.schema.json).
Artifact schema: [checkpoint-export-v1.schema.json](checkpoint-export-v1.schema.json).
Semantic checks (hashes, exact float32 values, delta ordering/preconditions and
byte limits) are additionally mandatory; JSON Schema alone is insufficient.

To keep a usable no-key example on disk, with dev dependencies installed:

```sh
python -m godseye.checkpoint_example --output /tmp/new-checkpoint-example
```

This uses an explicitly scripted numeric worker and actual local development and
held-out rollouts. The selected model name is an inert fixture label: no API key,
provider, discovery or external connection is used. Each case probes its root
first, probes one sign inversion, and chooses the candidate only when its measured
development mean is strictly higher. All selections freeze before held-out reveal.
The output includes `checkpoints.json`, `expected-sha256.txt`, and usable
`original-N.npz` / `selected-N.npz` files. Existing output directories are refused.
The command prints the actual count of changed selections and measured verdict;
a changed selection does not guarantee a successful overall held-out verdict.
All private evaluator files and credentials-free service state are temporary.

Independent reload from those retained files in another Python process:

```python
from pathlib import Path
from godseye.checkpoint_artifact import reload_artifact
from godseye.core import digest, save_weights
folder = Path('/tmp/new-checkpoint-example')
pairs = reload_artifact((folder / 'checkpoints.json').read_bytes(),
                        expected_sha256=(folder / 'expected-sha256.txt').read_text().strip())
original, selected = pairs[0]
print(digest(original), digest(selected))
# Save to NEW filenames. Loading original is rollback; selected is the chosen model.
save_weights(folder / 'independently-reloaded-selected.npz', selected)
```

Bounds intentionally reject suites above 32 cases per participant (the evaluator
can create 40); this is a safe export refusal, not a partial artifact. The service
and its local filesystem operator remain trusted. Validation does not authenticate
an attacker who controls both the artifact and its externally retained hash, nor
does it defend against a hostile administrator racing filesystem mutations.
