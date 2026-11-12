# Free local Qwen2.5 CPU execution slice

This separate target is `Qwen/Qwen2.5-0.5B-Instruct`, revision
`7ae557604adf67be50417f59c2c2f167def9a775`. It is independent of the existing
Qwen3.5 CUDA/Modal pilot. No provider, GPU, cloud fallback, server, or UI is involved.
The slice runs pretrained inference and a fixed reversible edit; it does not learn
an edit or establish repair quality. Free here means no paid inference service;
local hardware, electricity, bandwidth and disk still have costs.

The official [revision metadata](https://huggingface.co/api/models/Qwen/Qwen2.5-0.5B-Instruct/revision/7ae557604adf67be50417f59c2c2f167def9a775?blobs=true)
and [model card](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/blob/7ae557604adf67be50417f59c2c2f167def9a775/README.md)
were retrieved anonymously on 2026-11-13 before downloading weights. The card
specifies Apache-2.0, native Qwen2, 24 layers, hidden size 896, intermediate size
4864 and tied embeddings. Official metadata reports 494,032,768 parameters and
988,097,824 weight bytes. Expected `model.safetensors` SHA256:
`fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`.
The downloader checks immutable revision, license, size and expected LFS SHA256
before retrieving weights, then verifies the complete file. Small config/tokenizer
files have pinned Git blob hashes. These hashes establish integrity, not authorship.

## Install and run

Use a fresh external Python 3.12 virtual environment. Do not install optional
packages into the user's environment or change the base package dependencies.

```sh
python3.12 -m venv /tmp/godseye-lm-local-venv
/tmp/godseye-lm-local-venv/bin/python -m pip install -r requirements-lm-local.txt
python3 -S -m experiments.local_lm
/tmp/godseye-lm-local-venv/bin/python -m unittest discover -s tests -p test_lm_local.py -v
/tmp/godseye-lm-local-venv/bin/python -m experiments.local_lm --execute --output /tmp/godseye-lm-local-real-20261113
```

The dry run is stdlib-only, imports no Torch/Transformers and performs no network
access or output writes. Execution requires `--execute`, including internal child
modes. The output directory must not exist. The supervisor first downloads into
`weights/`, with a 240-second cooperative transfer deadline and a 250-second outer
process timeout, at most 1.1 GB total public response data (under the authorized
2 GB weights allowance). Failed partial files are removed when Python can unwind;
a killed process can leave a `.part` file. No retry or resume is automatic.

Downloads use only anonymous HTTPS requests to Hugging Face and its public
redirect domains. This path does not use Hugging Face cache/token helpers, netrc,
saved credentials, provider settings, authentication headers, cookies or proxies.
Only seven explicitly named data files are fetched, plus public metadata.
Loading is entirely offline from that verified directory, using native
`Qwen2ForCausalLM`, `trust_remote_code=False`, safetensors only and float32 CPU.
There is no pickle checkpoint load or executable model repository code.
Direct dependencies are pinned in `requirements-lm-local.txt`; all installed
transitive versions are recorded in evidence. This is not a hash-locked dependency
supply chain. Model Apache-2.0, Transformers/safetensors Apache-2.0, Torch BSD-3-Clause
and NumPy BSD-3-Clause licenses remain applicable; repository code is MIT.

Execution uses one model at a time, two intra-op CPU threads and one inter-op
thread. The smoke and subsequent fresh-process delta check run sequentially under
one aggregate 300-second execution deadline, separate from download. Four
16-new-token generations are planned, below the authorized eight generations and
32-token caps. Failure exits nonzero and retains available evidence. The supervisor
kills and waits for a timed-out direct child; no child model grandchildren are
created. Cooperative token stopping checks cannot interrupt a blocking native
kernel. Use this process supervisor when an actual wall deadline is required.

## Integration interface

All imports below are lazy with respect to optional numerical dependencies.
`plan()` returns the fixed model identity and limits without executing anything.
Download/loading must stay behind the caller's explicit execution authorization.
The coordinator can prepare the cache with `download(directory)` under an outer
process timeout, then run the following in a supervised CPU process:

```python
from godseye.lm.local_runtime import Runtime
from godseye.lm.local_delta import make_delta, applied, save_delta, load_delta

runtime = Runtime(verified_directory)
try:
    original = runtime.generate(prompt, max_new_tokens=16, seconds=20)
    delta = make_delta(runtime.model, column=0, scale=0.0)
    save_delta(new_delta_path, delta)  # refuses to overwrite
    with applied(runtime.model, load_delta(new_delta_path)):
        candidate = runtime.generate(prompt, max_new_tokens=16, seconds=20)
finally:
    runtime.close()
```

`Runtime(directory)` verifies the fixed local files and exact optional versions,
loads one CPU model and exposes `identity` and `model`. A second live runtime is
rejected; call `close()` when done. The synchronous runtime is intended for one
caller; integration should serialize calls rather than share it across threads.
There is no arbitrary model ID, device, parameter path or download URL argument.

`generate(prompt, max_new_tokens=32, seconds=20)` accepts 1–512 characters,
1–32 new tokens, and finite seconds in `(0, 30]`. After the fixed user chat template,
input is capped at 128 tokens and total context at 160. It uses greedy decoding,
one beam, repetition penalty 1.0, fixed seed 1729 and deterministic Torch algorithms.
Each native generation attempt reserves one of eight process-wide generations,
including an attempt that throws; invalid requests do not reserve a generation.
It returns a dict with `output`, exact `prompt` and `rendered_prompt`, `input_tokens`,
`generated_tokens`, `generated_token_ids`, `latency_seconds`, `termination`,
`deadline_exceeded`, `generation_config` and `memory`. If preprocessing consumes
the deadline, no native generation is attempted and `generation_config` is absent.
Latency includes tokenization, native inference and decoding. Reasons are `eos`,
`token_cap` or `walltime`; `deadline_exceeded` separately records an elapsed-time
overrun even if EOS/cap also occurred. Native failures raise and are retained as
errors by the smoke runner. Determinism on this measured machine is not a promise
of identical text across hardware or future dependency versions.

## Edit and artifact semantics

The only supported parameter is `model.layers.0.mlp.down_proj.weight`, shape
`[896,4864]`, CPU float32. Only column 0 or 1 and scale 0.0 or 0.5 are accepted.
The smoke fixes column 0 to zero before observing any output. It is a mechanism
probe, not a selected or learned repair and not evidence of a particular neuron.

`make_delta()` exports `godseye-local-column-v1`: exact model/revision/weight hash,
parameter/shape/dtype, column/scale, original/replacement values, base and edited
full tensor hashes, and canonical JSON content SHA256. Only a column and bounded
64-row hashing chunks are copied; no entire model is copied per candidate.
Pretrained BF16 values are loaded into float32; multiplication and rounding use
float32, not a claim of editing a BF16 deployment. Hash bytes are little-endian
float32 with shape/dtype prefix, including signed zero. Exported values must be
finite and exactly representable as float32. Validation independently checks
float32 replacement arithmetic with the stdlib; application checks exact base
hash, exact original column bytes and exact edited tensor hash.

`load_delta()` rejects unknown/missing/duplicate fields, unsupported identities,
nonfinite/overflow values, wrong shapes, arbitrary paths and files over 100 KB.
`applied()` validates a private artifact snapshot, changes one column, and restores
that column in `finally`, including generation exceptions or edited hash failure.
It verifies the exact full tensor hash after rollback. It cannot restore concurrent
unrelated edits, and deliberately raises if the full hash differs. No executable
code, pickle or whole-model checkpoint is exported. The delta is usable on a newly
loaded pinned model through the same loader; hashes are integrity preconditions,
not a signature or permission grant.

## Evidence and limitations

The compact committed report is `experiments/local_lm_validation.json`. Raw local
files include `execution.json`, per-stage logs, `smoke.json`, `fresh.json`,
`delta.json`, public source metadata and verified weights in the output directory.
No secrets or private prompts are used. The report distinguishes synthetic tests
from real pretrained execution and records exact commands, versions and hashes.
Memory uses `resource.getrusage().ru_maxrss`: bytes on macOS, normalized from KiB on
Linux. It is process lifetime peak RSS, including model loading, not current RSS,
physical memory ownership, energy or allocator-only model size.

This slice does not integrate Store/API/UI, implement task scoring, search, train,
claim held-out improvement, or establish broad laptop compatibility. One prompt
and a fixed hand edit cannot establish quality or cost savings. Local artifacts
and the isolated environment can be removed by deleting the explicitly named
`/tmp/godseye-lm-local-*` directories after reviewing/exporting needed evidence.
No remote storage, paid deployment or persistent server was created.

Measured on 2026-11-13: macOS arm64 with 24 GiB RAM, Python 3.12.14. All ten
focused tests passed. Anonymous verified download took 194.58 seconds; the CPU
smoke plus sequential fresh-process reload took 6.36 seconds. The prompt was
`Answer with only the number: What is 2 + 3?`; original, candidate, rollback and
export reload all produced `5`, each with two generated tokens including EOS.
Measured generation latencies were 0.1893, 0.0928, 0.0958 and 0.0926 seconds.
These warm-up-sensitive timings do not establish an edit speedup. The smoke
process lifetime peak RSS was 3,303,456,768 bytes (about 3.08 GiB).

The base/rollback tensor hash was
`cdba20f7429dd67092a8861e2d3d51e28318ecd4a6b007e7f417f1c5aeac3ee5`;
the edited hash was
`a5287989d14914fe1aba521739d1c1cc96decbddfa659c8d3f37b2ded1e78577`.
A fresh model process independently reloaded the exported delta and confirmed
both hashes and exact rollback without generating again. The edit changed no
observed output; quality remains inconclusive. Transformers emitted a sliding
window/eager attention warning, retained in evidence; this pinned model's verified
config has `use_sliding_window=false`. No pretrained checkpoint or credentials
were committed. Raw data and the usable numeric delta remain in the explicitly
named local output directory.
