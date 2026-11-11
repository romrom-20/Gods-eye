"""Independent bounded numeric Breakout artifact reader; no service/worker imports."""
import hashlib
import json
import math
import re

import numpy as np

from .core import NAMES, digest

MAX_BYTES = 32 * 1024 * 1024
MAX_CASES = 32
FORMAT = 'godseye-checkpoint-v1'
INSTRUCTIONS = dict(
    reload='Validate with reload_artifact and the retained content hash; save selected with core.save_weights.',
    rollback='Load the exported original; verify original_sha256; preserve the stored original.')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def content_hash(value):
    return hashlib.sha256(canonical({k: v for k, v in value.items()
                                     if k != 'content_sha256'})).hexdigest()


def exact(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError('Invalid checkpoint artifact')


def hex_id(value, length=64):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{%d}' % length, value):
        raise ValueError('Invalid checkpoint artifact')
    return value


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value) or abs(value) > 3.4028234663852886e38:
        raise ValueError('Invalid checkpoint artifact')
    converted = np.float32(value)
    if float(converted) != value:
        raise ValueError('Invalid checkpoint artifact')
    return converted


def bits(value):
    return np.asarray(value, dtype='<f4').tobytes()


def reload_artifact(raw, *, expected_sha256):
    """Return independent (original, selected) pairs, without executing or writing."""
    hex_id(expected_sha256)
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('Invalid checkpoint artifact')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Invalid checkpoint artifact')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        exact(value, 'schema_version format experiment_id spec_hash artifact_id baseline_id checkpoints instructions content_sha256')
        if (type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['format'] != FORMAT or value['instructions'] != INSTRUCTIONS):
            raise ValueError()
        hex_id(value['experiment_id'], 32)
        hex_id(value['artifact_id'], 32)
        hex_id(value['spec_hash'])
        if type(value['baseline_id']) is not str or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', value['baseline_id']):
            raise ValueError()
        if value['content_sha256'] != expected_sha256 or content_hash(value) != expected_sha256:
            raise ValueError()
        rows = value['checkpoints']
        if type(rows) is not list or not 1 <= len(rows) <= MAX_CASES:
            raise ValueError()
        result = []
        for slot, row in enumerate(rows):
            exact(row, 'slot outcome original_sha256 selected_sha256 original delta')
            if type(row['slot']) is not int or row['slot'] != slot:
                raise ValueError()
            hex_id(row['original_sha256'])
            hex_id(row['selected_sha256'])
            exact(row['original'], ' '.join(NAMES))
            original = {}
            for name, (_, shape) in NAMES.items():
                values = row['original'][name]
                if type(values) is not list or len(values) != math.prod(shape):
                    raise ValueError()
                original[name] = np.array([number(v) for v in values], dtype=np.float32).reshape(shape)
            if digest(original) != row['original_sha256']:
                raise ValueError()
            selected = {n: a.copy() for n, a in original.items()}
            delta = row['delta']
            if type(delta) is not list or len(delta) > sum(a.size for a in original.values()):
                raise ValueError()
            previous = (-1, -1)
            for edit in delta:
                exact(edit, 'tensor index before after')
                name, index = edit['tensor'], edit['index']
                if name not in NAMES or type(index) is not int or not 0 <= index < selected[name].size:
                    raise ValueError()
                position = (list(NAMES).index(name), index)
                if position <= previous:
                    raise ValueError()
                previous = position
                before, after = number(edit['before']), number(edit['after'])
                if bits(selected[name].flat[index]) != bits(before) or bits(before) == bits(after):
                    raise ValueError()
                selected[name].flat[index] = after
            if digest(selected) != row['selected_sha256']:
                raise ValueError()
            if row['outcome'] != ('changed' if delta else 'unchanged'):
                raise ValueError()
            result.append((original, selected))
        return result
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        raise ValueError('Invalid checkpoint artifact') from None
