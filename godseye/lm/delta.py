"""Versioned, non-executable replacement-column delta with exact preconditions."""
import contextlib
import hashlib
import json
import math
from pathlib import Path
from .spec import MODEL, REVISION, PARAMETER, digest


def tensor_hash(tensor):
    # Hash in bounded row chunks: no model-sized CPU copies.
    h = hashlib.sha256()
    h.update(str(tuple(tensor.shape)).encode())
    h.update(str(tensor.dtype).encode())
    for chunk in tensor.detach().split(64):
        h.update(chunk.contiguous().cpu().numpy().tobytes())
    return h.hexdigest()


def target(model):
    param = dict(model.named_parameters())[PARAMETER]
    if param.ndim != 2 or tuple(param.shape) != (1024, 3584) or str(param.dtype) != 'torch.float32':
        raise ValueError('fixed float32 Qwen text MLP schema required')
    return param


def make_delta(model, column, scale):
    if type(column) is not int or column not in (0, 1) or scale not in (0.0, 0.5):
        raise ValueError('candidate outside fixed bounds')
    p = target(model)
    before = p[:, column].detach().clone()
    after = before * scale
    body = dict(format='godseye-lm-column-v1', model=MODEL, revision=REVISION,
                parameter=PARAMETER, shape=list(p.shape), dtype='float32', column=column,
                scale=scale, base_tensor_sha256=tensor_hash(p),
                before=before.cpu().tolist(), after=after.cpu().tolist())
    return dict(body, content_sha256=digest(body))


def validate(artifact):
    expected = {'format', 'model', 'revision', 'parameter', 'shape', 'dtype', 'column',
                'scale', 'base_tensor_sha256', 'before', 'after', 'content_sha256'}
    if not isinstance(artifact, dict) or set(artifact) != expected:
        raise ValueError('invalid delta schema')
    body = {k: v for k, v in artifact.items() if k != 'content_sha256'}
    if digest(body) != artifact['content_sha256']:
        raise ValueError('delta digest mismatch')
    if (artifact['format'] != 'godseye-lm-column-v1' or artifact['model'] != MODEL
            or artifact['revision'] != REVISION or artifact['parameter'] != PARAMETER
            or artifact['shape'] != [1024, 3584] or artifact['dtype'] != 'float32'
            or type(artifact['column']) is not int or artifact['column'] not in (0, 1)
            or type(artifact['scale']) not in (int, float)
            or artifact['scale'] not in (0.0, 0.5)):
        raise ValueError('unsupported delta')
    for key in ('base_tensor_sha256', 'content_sha256'):
        value = artifact[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('invalid sha256')
    for key in ('before', 'after'):
        vals = artifact[key]
        if not isinstance(vals, list) or len(vals) != 1024 or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in vals):
            raise ValueError('invalid column values')
    return artifact


def load_delta(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 100000:
        raise ValueError('unsafe delta file')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate field')
            result[k] = v
        return result
    return validate(json.loads(path.read_text(), object_pairs_hook=pairs))


@contextlib.contextmanager
def applied(model, artifact):
    import torch
    a = validate(artifact)
    p = target(model)
    if tensor_hash(p) != a['base_tensor_sha256']:
        raise ValueError('base tensor precondition failed')
    col = a['column']
    before = torch.tensor(a['before'], dtype=p.dtype, device=p.device)
    after = torch.tensor(a['after'], dtype=p.dtype, device=p.device)
    if not torch.equal(p[:, col], before) or not torch.equal(after, before * a['scale']):
        raise ValueError('column precondition failed')
    with torch.no_grad():
        p[:, col].copy_(after)
    try:
        yield tensor_hash(p)
    finally:
        with torch.no_grad():
            p[:, col].copy_(before)
        if tensor_hash(p) != a['base_tensor_sha256']:
            raise RuntimeError('rollback failed')
