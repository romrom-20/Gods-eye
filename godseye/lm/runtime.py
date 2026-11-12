"""Real native Transformers path. Import and download occur only after execution opt-in."""
import hashlib
import importlib.metadata
import os
import platform
import time
from .spec import MODEL, REVISION, VERSIONS

SHARD = 'model.safetensors-00001-of-00001.safetensors'
SHARD_SHA256 = '04b1c301231dd422b8860db31311ab2721511346a32cb1e079c4c4e5f1fe4696'


class Runtime:
    def __init__(self, config):
        # Never use implicit locally saved HF tokens or download executable Hub kernels.
        os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
        os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
        for package in ('torch', 'transformers', 'safetensors', 'numpy'):
            if importlib.metadata.version(package).split('+')[0] != VERSIONS[package]:
                raise RuntimeError(f'{package} version must equal {VERSIONS[package]}')
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer, Qwen3_5TextConfig, Qwen3_5ForCausalLM
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA required; laptop execution has not been measured')
        started = time.monotonic()
        path = hf_hub_download(MODEL, SHARD, revision=REVISION, token=False)
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024*1024), b''):
                h.update(chunk)
        if h.hexdigest() != SHARD_SHA256:
            raise ValueError('public safetensors shard hash mismatch')
        text_config = Qwen3_5TextConfig.from_pretrained(
            MODEL, revision=REVISION, token=False, trust_remote_code=False)
        self.model, loading = Qwen3_5ForCausalLM.from_pretrained(
            MODEL, revision=REVISION, config=text_config, token=False,
            trust_remote_code=False, use_safetensors=True, dtype=torch.float32,
            attn_implementation='eager', device_map='cuda', output_loading_info=True,
            key_mapping={r'^model\.language_model\.': 'model.'})
        if loading.get('missing_keys') or loading.get('mismatched_keys') or loading.get('error_msgs'):
            raise RuntimeError(f'incomplete text weight load: {loading}')
        unexpected = loading.get('unexpected_keys', [])
        if any(not (key.startswith('mtp.') or key.startswith('model.visual.'))
               for key in unexpected):
            raise RuntimeError(f'unexpected text weights: {unexpected}')
        self.model.eval()
        load_peak_allocated = torch.cuda.max_memory_allocated()
        load_peak_reserved = torch.cuda.max_memory_reserved()
        torch.cuda.reset_peak_memory_stats()
        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL, revision=REVISION, token=False, trust_remote_code=False)
        torch.manual_seed(config['seed'])
        torch.cuda.manual_seed_all(config['seed'])
        torch.use_deterministic_algorithms(True)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        self.config = config
        self.identity = dict(python=platform.python_version(), packages={d.metadata['Name']: d.version
                             for d in importlib.metadata.distributions()}, gpu=torch.cuda.get_device_name(),
                             cuda=torch.version.cuda, gpu_capability=torch.cuda.get_device_capability(),
                             load_peak_cuda_allocated_bytes=load_peak_allocated,
                             load_peak_cuda_reserved_bytes=load_peak_reserved, model=MODEL, revision=REVISION,
                             shard_sha256=SHARD_SHA256, loading_info=loading,
                             parameter_count=sum(p.numel() for p in self.model.parameters()),
                             load_seconds=time.monotonic()-started)

    def generate(self, prompt, decoding=False, seconds=10):
        import torch
        from transformers import GenerationConfig, StoppingCriteria, StoppingCriteriaList
        config = self.config
        if len(prompt) > config['max_prompt_chars']:
            raise ValueError('prompt character cap')
        rendered = self.tokenizer.apply_chat_template(
            [{'role': 'user', 'content': prompt}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False)
        inputs = self.tokenizer(rendered, return_tensors='pt').to('cuda')
        if inputs.input_ids.shape[-1] > config['max_prompt_tokens']:
            raise ValueError('prompt token cap')
        start = time.monotonic()
        class Deadline(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return time.monotonic()-start >= seconds
        gc = GenerationConfig(do_sample=False, num_beams=1,
                              max_new_tokens=config['max_new_tokens'],
                              repetition_penalty=1.15 if decoding else 1.0,
                              eos_token_id=self.model.config.eos_token_id,
                              pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                              use_cache=True)
        with torch.inference_mode():
            out = self.model.generate(**inputs, generation_config=gc,
                                     stopping_criteria=StoppingCriteriaList([Deadline()]))
        torch.cuda.synchronize()
        tokens = out[0, inputs.input_ids.shape[-1]:].tolist()
        eos = gc.eos_token_id if isinstance(gc.eos_token_id, list) else [gc.eos_token_id]
        reason = 'eos' if tokens and tokens[-1] in eos else (
            'token_cap' if len(tokens) >= config['max_new_tokens'] else 'walltime')
        return dict(output=self.tokenizer.decode(tokens, skip_special_tokens=True),
                    rendered_prompt=rendered,
                    generated_tokens=len(tokens), generated_token_ids=tokens, input_tokens=inputs.input_ids.shape[-1],
                    latency_seconds=time.monotonic()-start, termination=reason,
                    generation_config=gc.to_dict(),
                    peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                    peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved())
