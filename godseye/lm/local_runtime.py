"""Fixed Qwen2.5 CPU target; importing/planning requires only the stdlib."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import time
import threading
import urllib.request
import weakref

MODEL = 'Qwen/Qwen2.5-0.5B-Instruct'
REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'
WEIGHT_SHA256 = 'fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe'
WEIGHT_BYTES = 988097824
VERSIONS = {'torch': '2.6.0', 'transformers': '4.51.3', 'safetensors': '0.5.3',
            'numpy': '2.2.6', 'huggingface-hub': '0.30.2', 'tokenizers': '0.21.1'}
FILES = ('config.json', 'generation_config.json', 'tokenizer.json',
         'tokenizer_config.json', 'merges.txt', 'vocab.json', 'model.safetensors')
BLOBS = {'config.json': '0dbb161213629a23f0fc00ef286e6b1e366d180f',
         'generation_config.json': 'dfc11073787daf1b0f9c0f1499487ab5f4c93738',
         'merges.txt': '20024bfe7c83998e9aeaf98a0cd6a2ce6306c2f0',
         'tokenizer.json': '443909a61d429dff23010e5bddd28ff530edda00',
         'tokenizer_config.json': '07bfe0640cb5a0037f9322287fbfc682806cf672',
         'vocab.json': '4783fe10ac3adce15ac8f358ef5462739852c569'}
_active = None
_slot_lock = threading.Lock()
_generations = 0


def plan():
    return dict(target='qwen2.5-0.5b-instruct-cpu', model=MODEL, revision=REVISION,
                weight_sha256=WEIGHT_SHA256, weight_bytes=WEIGHT_BYTES, device='cpu',
                dtype='float32', threads=2, max_prompt_chars=512, max_input_tokens=128,
                max_context_tokens=160, max_new_tokens=32, max_generations=8,
                execution_deadline_seconds=300, download_deadline_seconds=240,
                download_max_bytes=1100000000, packages=VERSIONS)


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _opener():
    # urllib does not consult HF caches, tokens, netrc, cookies, or provider profiles.
    class PublicRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            from urllib.parse import urlparse
            p = urlparse(newurl)
            if (p.scheme != 'https' or p.username or p.password or not p.hostname
                    or not any(p.hostname == d or p.hostname.endswith('.' + d)
                               for d in ('huggingface.co', 'hf.co', 'xethub.hf.co'))):
                raise ValueError('non-public download redirect')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicRedirect())


def download(directory):
    """Anonymous allowlisted files only. CLI additionally bounds this process to 250s."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 240
    opener = _opener()
    used = 0

    def fetch(url, limit, dest=None):
        nonlocal used
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('download deadline')
        data = bytearray()
        count = 0
        out = open(dest, 'wb') if dest else None
        try:
            with opener.open(url, timeout=min(10, remaining)) as response:
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('download deadline')
                    block = response.read(min(1024 * 1024, limit - count + 1))
                    if not block:
                        break
                    count += len(block)
                    used += len(block)
                    if count > limit or used > 1100000000:
                        raise ValueError('download byte cap')
                    if out:
                        out.write(block)
                    else:
                        data.extend(block)
        finally:
            if out:
                out.close()
        return bytes(data)

    url = f'https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true'
    metadata = json.loads(fetch(url, 1000000))
    entries = {e['rfilename']: e for e in metadata['siblings']}
    weight = entries['model.safetensors']
    if (metadata['sha'] != REVISION or metadata.get('cardData', {}).get('license') != 'apache-2.0'
            or weight['size'] != WEIGHT_BYTES or weight['lfs']['sha256'] != WEIGHT_SHA256):
        raise ValueError('official model metadata differs from pinned target')
    # Persist public provenance before any weights are retrieved.
    (directory / 'source.json').write_text(json.dumps(metadata, indent=2))
    for name in FILES:
        entry = entries[name]
        if entry['size'] > (WEIGHT_BYTES if name == 'model.safetensors' else 10000000):
            raise ValueError('unexpected file size')
        part = directory / (name + '.part')
        try:
            fetch(f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}', entry['size'], part)
            _verify_file(part, entry, name)
            part.replace(directory / name)
        finally:
            part.unlink(missing_ok=True)
    verify_files(directory)
    return dict(downloaded_bytes=used, metadata_url=url)


def _verify_file(path, entry, name):
    if (path.is_symlink() or path.stat().st_size != entry['size']
            or (name != 'model.safetensors' and entry['size'] > 10000000)):
        raise ValueError('model file size/symlink mismatch')
    if name == 'model.safetensors':
        if file_hash(path) != WEIGHT_SHA256:
            raise ValueError('weight checksum mismatch')
    else:
        data = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != BLOBS[name] or entry['blobId'] != BLOBS[name]:
            raise ValueError('source blob mismatch')


def verify_files(directory):
    directory = Path(directory)
    source = directory / 'source.json'
    if source.is_symlink() or source.stat().st_size > 1000000:
        raise ValueError('unsafe source metadata')
    metadata = json.loads(source.read_text())
    entries = {e['rfilename']: e for e in metadata['siblings']}
    if metadata['sha'] != REVISION or entries['model.safetensors']['size'] != WEIGHT_BYTES:
        raise ValueError('model identity mismatch')
    for name in FILES:
        _verify_file(directory / name, entries[name], name)


def memory():
    # macOS reports bytes, Linux KiB. This is process lifetime peak RSS, not current RSS.
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(process_peak_rss_bytes=int(rss if platform.system() == 'Darwin' else rss * 1024),
                measurement='getrusage ru_maxrss; process lifetime peak, includes loading')


def termination(tokens, eos, cap, elapsed, seconds):
    reason = 'eos' if tokens and tokens[-1] in eos else (
        'token_cap' if len(tokens) >= cap else 'walltime')
    return dict(termination=reason, deadline_exceeded=elapsed >= seconds)


class Runtime:
    """One loaded CPU model per process. close() releases the instance ownership slot."""
    def __init__(self, directory):
        global _active
        with _slot_lock:
            if _active is not None and _active() is not None:
                raise RuntimeError('only one local model may be loaded')
            _active = weakref.ref(self)
        for name, version in VERSIONS.items():
            if importlib.metadata.version(name).split('+')[0] != version:
                raise RuntimeError(f'{name} must equal {version}')
        verify_files(directory)
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        import torch
        from transformers import AutoTokenizer, Qwen2ForCausalLM
        torch.set_num_threads(2)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        torch.manual_seed(1729)
        torch.use_deterministic_algorithms(True)
        start = time.monotonic()
        self.model, loading = Qwen2ForCausalLM.from_pretrained(
            str(directory), local_files_only=True, token=False, trust_remote_code=False,
            use_safetensors=True, torch_dtype=torch.float32, attn_implementation='eager',
            output_loading_info=True)
        if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')):
            raise RuntimeError(f'incomplete pretrained load: {loading}')
        if any(p.device.type != 'cpu' or p.dtype != torch.float32 for p in self.model.parameters()):
            raise RuntimeError('CPU float32 required')
        self.model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(directory), local_files_only=True, trust_remote_code=False, token=False)
        self.identity = dict(plan(), python=platform.python_version(), architecture=platform.machine(),
                             parameter_count=sum(p.numel() for p in self.model.parameters()),
                             load_seconds=time.monotonic() - start, loading_info=loading,
                             memory=memory(), installed_packages={d.metadata['Name']: d.version
                                          for d in importlib.metadata.distributions()})
        _active = weakref.ref(self)

    def close(self):
        global _active
        self.model = None
        self.tokenizer = None
        if _active is not None and _active() is self:
            _active = None

    def generate(self, prompt, max_new_tokens=32, seconds=20):
        global _generations
        if self.model is None:
            raise RuntimeError('runtime is closed')
        if not isinstance(prompt, str) or not prompt or len(prompt) > 512:
            raise ValueError('prompt must contain 1..512 characters')
        if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 32:
            raise ValueError('max_new_tokens must be 1..32')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 30:
            raise ValueError('seconds must be finite in (0,30]')
        if _generations >= 8:
            raise RuntimeError('process generation budget exhausted')
        import torch
        from transformers import GenerationConfig, StoppingCriteria, StoppingCriteriaList
        start = time.monotonic()
        rendered = self.tokenizer.apply_chat_template(
            [{'role': 'user', 'content': prompt}], tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(rendered, return_tensors='pt')
        input_count = inputs.input_ids.shape[-1]
        if input_count > 128 or input_count + max_new_tokens > 160:
            raise ValueError('input/context token cap')
        if time.monotonic() - start >= seconds:
            return dict(output='', prompt=prompt, rendered_prompt=rendered, input_tokens=input_count,
                        generated_tokens=0, generated_token_ids=[], latency_seconds=time.monotonic()-start,
                        termination='walltime', deadline_exceeded=True, memory=memory())
        class Deadline(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return time.monotonic() - start >= seconds
        gc = GenerationConfig(do_sample=False, num_beams=1, max_new_tokens=max_new_tokens,
                              repetition_penalty=1.0, eos_token_id=[151645, 151643],
                              pad_token_id=151643, use_cache=True)
        _generations += 1  # failed native attempts still consume a generation reservation
        with torch.inference_mode():
            out = self.model.generate(**inputs, generation_config=gc,
                                     stopping_criteria=StoppingCriteriaList([Deadline()]))
        tokens = out[0, input_count:].tolist()
        output = self.tokenizer.decode(tokens, skip_special_tokens=True)
        elapsed = time.monotonic() - start
        return dict(output=output, prompt=prompt, rendered_prompt=rendered,
                    input_tokens=input_count, generated_tokens=len(tokens), generated_token_ids=tokens,
                    latency_seconds=elapsed, generation_config=gc.to_dict(), memory=memory(),
                    **termination(tokens, gc.eos_token_id, max_new_tokens, elapsed, seconds))
