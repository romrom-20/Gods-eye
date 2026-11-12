# Local Breakout checkpoint import

Import one data-only NPZ into the local writable workspace as an independent root.
This supports the built-in `minatar-breakout-v1` backend only. It does not register
models with the isolated repair evaluator, support arbitrary architectures, run
inference, select a provider, or start an experiment. Imported weights are untested
until you explicitly evaluate them. Finite tensors alone do not establish useful
behavior or numerical stability during evaluation.

## Browser workflow

Start the local server, open the lab, and choose **Import checkpoint** from
**Edit weights** or **Saved versions**. Select your NPZ, enter a name and optional
source/license notes, then explicitly submit. Source notes are user-provided,
unverified metadata. The imported original is selected for inspection and editing.
Create a child edit, then select the original and child in **Compare** to evaluate.
The bundled original remains available. Reload preserves both versions and results.

If an upload loses its response, refresh saved versions and inspect the list before
submitting again: the import may already have succeeded. No automatic retry occurs.
Recorded demos disable import; servers without the capability show it as unsupported.

## Local CLI and client

```sh
godseye import-checkpoint --file ./weights.npz --name 'Local candidate' \
  --provenance 'Author supplied, revision 2'
godseye inspect CHECKPOINT_ID
godseye patch --base CHECKPOINT_ID --file ./change.edits --hypothesis 'My test'
godseye compare --base CHECKPOINT_ID --candidate CHILD_ID --episodes 2 --max-steps 100
```

The import prints JSON including the checkpoint ID, tensor `sha256`, and source
file `source_sha256`. `GODSEYE_DATA_DIR` selects the workspace as for other CLI
commands. Provenance defaults to an empty string; the local source path is never
automatically persisted. Supply provenance you are comfortable storing in history.

```python
from godseye.client import Client

client = Client()  # contacts the local server only when a method is called
record = client.import_checkpoint('./weights.npz', 'Local candidate', 'Revision 2')
print(record['id'], record['sha256'])
```

The CLI and client read at most 128 KiB plus one overflow-detection byte from a
regular local file. The client performs one HTTP attempt with no automatic retry.
A lost response can mean the checkpoint was saved: inspect state before retrying.

## HTTP contract

`POST /api/v1/checkpoints/import`, `Content-Type: application/json`, takes exactly
these fields, with no duplicates or additional fields:

```json
{"name":"Local candidate","provenance":"Revision 2","npz_base64":"..."}
```

`name` is a nonblank string of 1–80 characters. `provenance` is a string of 0–2,000
characters. `npz_base64` is canonical standard base64 with required padding, no
whitespace, and no data-URL prefix. The decoded NPZ must be at most 128 KiB.

Only this exact POST route admits a JSON body up to 192 KiB. Every other route,
method, and trailing-slash variant retains the 64 KiB bound, checked during
streaming before JSON parsing. Host, same-origin, cross-site, optional bearer token,
and JSON content-type protections remain in force. The recorded demo rejects
imports. `GET /api/v1/state` advertises `checkpoint_import` only for the writable
built-in Breakout backend.

Success is HTTP 201 with a record containing `schema_version`, `backend`, `id`,
`name`, `parent: null`, `sha256`, `source_sha256`, `provenance`, and `created` (Unix
seconds). `source_sha256` hashes the exact uploaded NPZ bytes; `sha256` uses the
existing ordered W1/b1/W2/b2/W3/b3 tensor digest. The stored NPZ retains those exact
uploaded bytes. There is no fabricated patch, diff, or parent hash. The root can be
inspected, used as a patch parent, evaluated using the ordinary bounded job API,
and reloaded alongside its descendants and persisted runs.

Invalid schema, base64, NPZ, or incompatible backend returns 400. Authorization,
read-only, media-type, streamed body-size, and workspace quota failures retain
401/403/415/413/507 behavior. A concurrent import returns 429 with no automatic
retry. Import errors do not include archive contents or server paths.

## Exact tensor archive

Use `godseye.core.save_weights(path, weights)` to produce a supported archive, or
`numpy.savez` / `numpy.savez_compressed` with exactly the following six archive
keys (NumPy appends `.npy`):

- `actor/dense1/kernel`: shape `(600, 32)`, internal tensor `W1`.
- `actor/dense1/bias`: shape `(32,)`, internal tensor `b1`.
- `actor/dense2/kernel`: shape `(32, 32)`, internal tensor `W2`.
- `actor/dense2/bias`: shape `(32,)`, internal tensor `b2`.
- `actor/logits/kernel`: shape `(32, 6)`, internal tensor `W3`.
- `actor/logits/bias`: shape `(6,)`, internal tensor `b3`.

All values must be finite, little-endian float32 (`<f4`), C order, NPY version 1.0.
Archive order may vary; tensor hashing always follows the existing `NAMES` order.
Other dtypes, Fortran order, NPY versions, JSON checkpoint exports, pickle, object
arrays, model code, and ambiguous encodings are unsupported. A JSON experiment
checkpoint export must first be independently reloaded using its documented loader
and saved as the fixed raw tensor NPZ; it is not an import payload itself.

ZIP entries may use stored or raw-deflate compression. The reader requires exactly
six unique known members, a single ZIP directory, contiguous local entries, matching
local/directory sizes and CRCs, and no encryption, data descriptors, comments,
preamble, trailing payload, or central-directory extras. The standard NumPy local
ZIP64 size extra is supported. Other ZIP extensions are intentionally rejected.

Before creating arrays, the reader bounds raw file size, each expanded entry, total
expanded data (100 KiB), and each NPY header (1 KiB); it verifies exact declared
shapes and payload sizes. Deflate output is capped even when directory sizes lie.
It never extracts files, calls `numpy.load`, accepts executable Python, or allocates
an attacker-declared shape.

## Publication, limits, and verification

One HTTP import at a time is admitted before body buffering; a second request is
rejected instead of waiting with another large archive. Direct Store imports also
have a nonblocking per-Store guard. This is a single-process local workspace feature,
not a multi-process or multi-tenant import service. Existing 256 MiB server workspace
admission limits apply; the direct CLI follows existing Store disk behavior.

The source archive is atomically written and checkpoint metadata is atomically
published last. List/history readers only discover complete records. A metadata
write failure removes the unpublished archive. A process crash between those two
writes can leave an unlisted orphan NPZ; it cannot expose a partially listed root.
Existing checkpoint metadata, original weights, tensor hashes, and archive bytes
are preserved. Repeated successful imports intentionally create independent roots.

Reproduce focused evidence without credentials, provider calls, or Docker:

```sh
python -m unittest discover -s tests -p test_checkpoint_import.py -v
python -m unittest discover -s tests -p test_platform.py -v
```

The import tests own an ephemeral loopback HTTP server and cover import → inspect →
patch → bounded CPU evaluation → Store reload, original-byte preservation, CLI,
malicious ZIP/NPY/base64 inputs, streamed bounds, admission, atomic visibility and
failure cleanup, auth, read-only mode, and custom-backend refusal.

Verification on this branch: Python 3.12 full discovery ran 208 tests in 36.7 seconds,
with 18 opt-in container/package checks skipped, and passed. The final focused import
suite ran nine tests and passed; Ruff and `git diff --check` also passed. No provider,
Docker, deployment, or existing server was used for this verification.
