"""Inert, versioned float32 column edits for exactly one CPU Qwen2 projection."""
import contextlib
import hashlib
import json
import math
from pathlib import Path
import struct
from .local_runtime import MODEL, REVISION, WEIGHT_SHA256

PARAMETER = 'model.layers.0.mlp.down_proj.weight'
SHAPE = [896, 4864]
FORMAT = 'godseye-local-column-v1'


def digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _f32(value):
    try:
        return struct.unpack('<f', struct.pack('<f', value))[0]
    except (OverflowError, struct.error):
        raise ValueError('float32 overflow') from None


def validate(a):
    keys = {'format', 'model', 'revision', 'weight_sha256', 'parameter', 'shape', 'dtype',
            'column', 'scale', 'before', 'after', 'base_tensor_sha256',
            'edited_tensor_sha256', 'content_sha256'}
    if not isinstance(a, dict) or set(a) != keys:
        raise ValueError('invalid delta schema')
    if (a['format'] != FORMAT or a['model'] != MODEL or a['revision'] != REVISION
            or a['weight_sha256'] != WEIGHT_SHA256 or a['parameter'] != PARAMETER
            or a['shape'] != SHAPE or a['dtype'] != 'float32'
            or type(a['column']) is not int or a['column'] not in (0, 1)
            or type(a['scale']) not in (int, float) or a['scale'] not in (0.0, 0.5)):
        raise ValueError('unsupported delta identity/operation')
    for key in ('base_tensor_sha256', 'edited_tensor_sha256', 'content_sha256'):
        if not _sha(a[key]):
            raise ValueError('invalid sha256')
    for key in ('before', 'after'):
        values = a[key]
        if (not isinstance(values, list) or len(values) != SHAPE[0]
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       or _f32(v) != v for v in values)):
            raise ValueError('invalid exact float32 column')
    if any(struct.pack('<f', _f32(v * a['scale'])) != struct.pack('<f', w)
           for v, w in zip(a['before'], a['after'])):
        raise ValueError('replacement does not match float32 scaling')
    if digest({k: v for k, v in a.items() if k != 'content_sha256'}) != a['content_sha256']:
        raise ValueError('delta content hash mismatch')
    return a


def load_delta(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 100000:
        raise ValueError('unsafe delta file')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate delta field')
            result[k] = v
        return result
    return validate(json.loads(path.read_text(), object_pairs_hook=pairs))


def save_delta(path, artifact):
    data = json.dumps(validate(artifact), sort_keys=True, indent=2, allow_nan=False)
    with open(path, 'x') as f:
        f.write(data + '\n')


def target(model):
    # Fixed traversal; no caller-supplied tensor paths or executable payloads.
    p = model.model.layers[0].mlp.down_proj.weight
    if list(p.shape) != SHAPE or str(p.dtype) != 'torch.float32' or p.device.type != 'cpu':
        raise ValueError('fixed CPU float32 projection required')
    return p


def tensor_hash(p, replacement=None, column=0):
    """Canonical little endian float32 hash; at most 64 rows copied at a time."""
    h = hashlib.sha256()
    h.update(json.dumps({'shape': list(p.shape), 'dtype': 'float32-le'}, sort_keys=True).encode())
    for offset in range(0, p.shape[0], 64):
        chunk = p[offset:offset + 64].detach()
        if replacement is not None:
            chunk = chunk.clone()
            chunk[:, column].copy_(replacement[offset:offset + 64])
        h.update(chunk.contiguous().numpy().astype('<f4', copy=False).tobytes())
    return h.hexdigest()


def make_delta(model, column=0, scale=0.0):
    if (type(column) is not int or column not in (0, 1)
            or type(scale) not in (int, float) or scale not in (0.0, 0.5)):
        raise ValueError('unsupported candidate')
    import torch
    p = target(model)
    for chunk in p.detach().split(64):
        if not torch.isfinite(chunk).all().item():
            raise ValueError('nonfinite base tensor')
    before = p[:, column].detach().clone()
    after = before * scale
    body = dict(format=FORMAT, model=MODEL, revision=REVISION, weight_sha256=WEIGHT_SHA256,
                parameter=PARAMETER, shape=SHAPE[:], dtype='float32', column=column, scale=scale,
                before=before.tolist(), after=after.tolist(), base_tensor_sha256=tensor_hash(p),
                edited_tensor_sha256=tensor_hash(p, after, column))
    return validate(dict(body, content_sha256=digest(body)))


@contextlib.contextmanager
def applied(model, artifact):
    import torch
    # Snapshot validated data so caller mutation cannot alter rollback/preconditions.
    a = validate(json.loads(json.dumps(artifact, allow_nan=False)))
    p = target(model)
    if tensor_hash(p) != a['base_tensor_sha256']:
        raise ValueError('base tensor precondition failed')
    before = torch.tensor(a['before'], dtype=torch.float32)
    after = torch.tensor(a['after'], dtype=torch.float32)
    column = a['column']
    if p[:, column].detach().contiguous().numpy().tobytes() != before.numpy().tobytes():
        raise ValueError('column precondition failed')
    try:
        with torch.no_grad():
            p[:, column].copy_(after)
        if tensor_hash(p) != a['edited_tensor_sha256']:
            raise ValueError('edited tensor hash mismatch')
        yield a['edited_tensor_sha256']
    finally:
        with torch.no_grad():
            p[:, column].copy_(before)
        if tensor_hash(p) != a['base_tensor_sha256']:
            raise RuntimeError('exact rollback failed')
