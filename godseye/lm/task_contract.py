"""Offline, deterministic JSON-task preview. No execution, paths, or network I/O."""
from dataclasses import dataclass
import hashlib
import json
import math
import re

MODEL_ID = 'Qwen/Qwen2.5-0.5B-Instruct'
VERSION = 'godseye-lm-task-v1'
PHRASES = (
    'improve json schema adherence',
    'return correct json matching the specified schema',
    'improve json output without markdown or preamble',
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def strict_json(raw, max_bytes=16384):
    """One JSON value, no duplicate keys, nonfinite numbers or excessive nesting."""
    if not isinstance(raw, str):
        raise ValueError('JSON must be bounded text')
    try:
        if len(raw.encode('utf-8')) > max_bytes:
            raise ValueError('JSON must be bounded text')
    except UnicodeError as exc:
        raise ValueError('invalid Unicode JSON') from exc

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('nonfinite JSON number')

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        def bounded(item, depth=0):
            if depth > 12:
                raise ValueError('JSON nesting limit')
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError('nonfinite JSON number')
            if isinstance(item, dict):
                for child in item.values():
                    bounded(child, depth + 1)
            if isinstance(item, list):
                for child in item:
                    bounded(child, depth + 1)
        bounded(value)
        return value
    except (RecursionError, OverflowError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid JSON') from exc


def validate_schema(schema, depth=0):
    """Deliberately small JSON Schema dialect, not a general JSON Schema engine."""
    if type(schema) is not dict or depth > 3:
        raise ValueError('invalid bounded schema')
    kind = schema.get('type')
    if kind == 'object':
        if set(schema) != {'type', 'properties', 'required', 'additionalProperties'}:
            raise ValueError('object schema fields')
        props = schema['properties']
        if type(props) is not dict or not 1 <= len(props) <= 8:
            raise ValueError('object property bound')
        if any(type(k) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', k) for k in props):
            raise ValueError('property name')
        if schema['additionalProperties'] is not False or schema['required'] != sorted(props):
            raise ValueError('all properties must be required, no extras')
        for child in props.values():
            validate_schema(child, depth + 1)
    elif kind == 'string':
        if set(schema) not in ({'type', 'maxLength'}, {'type', 'maxLength', 'enum'}):
            raise ValueError('string schema fields')
        if type(schema['maxLength']) is not int or not 1 <= schema['maxLength'] <= 256:
            raise ValueError('string length bound')
        if 'enum' in schema:
            choices = schema['enum']
            if (type(choices) is not list or not 1 <= len(choices) <= 8 or
                    any(type(x) is not str or len(x) > schema['maxLength'] for x in choices) or
                    len(set(choices)) != len(choices)):
                raise ValueError('enum bound')
    elif kind == 'integer':
        if (set(schema) != {'type', 'minimum', 'maximum'} or
                type(schema['minimum']) is not int or type(schema['maximum']) is not int or
                not -1000000 <= schema['minimum'] <= schema['maximum'] <= 1000000):
            raise ValueError('integer bounds')
    elif kind == 'boolean':
        if set(schema) != {'type'}:
            raise ValueError('boolean schema fields')
    else:
        raise ValueError('unsupported schema type')


def matches_schema(value, schema):
    validate_schema(schema)
    kind = schema['type']
    if kind == 'object':
        return (type(value) is dict and set(value) == set(schema['properties']) and
                all(matches_schema(value[k], s) for k, s in schema['properties'].items()))
    if kind == 'string':
        return (type(value) is str and len(value) <= schema['maxLength'] and
                ('enum' not in schema or value in schema['enum']))
    if kind == 'integer':
        return type(value) is int and schema['minimum'] <= value <= schema['maximum']
    return type(value) is bool


@dataclass(frozen=True)
class TaskSpec:
    """Canonical immutable bytes; returned dictionaries are independent copies."""
    _json: str

    def __post_init__(self):
        value = strict_json(self._json, max_bytes=65536)
        validate_spec(value)
        object.__setattr__(self, '_json', canonical(value))

    @property
    def sha256(self):
        return hashlib.sha256(self._json.encode('utf-8')).hexdigest()

    def to_dict(self):
        return json.loads(self._json)


def _spec(revision, model_id=MODEL_ID):
    from .task_suite import dataset_identity
    if model_id != MODEL_ID:
        raise ValueError('unsupported model')
    if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('explicit immutable 40-character lowercase commit revision required')
    return {
        'version': VERSION, 'goal': 'correct_bounded_json',
        'model': {'id': MODEL_ID, 'revision': revision, 'tokenizer_revision': revision},
        'dataset': dataset_identity(),
        'metrics': {'target': 'strict_schema_adherence', 'semantic': 'exact_typed_json',
                    'regression': 'exact_text', 'min_schema_gain': 0.1,
                    'max_semantic_drop': 0, 'max_regression_cases': 0,
                    'uncertainty': 'paired_hoeffding_95_descriptive_public_fixture'},
        'operations': {'kind': 'scale_column',
                       'parameter': 'model.layers.0.mlp.down_proj.weight',
                       'candidates': [{'column': 0, 'scale': 0.0}, {'column': 1, 'scale': 0.5}],
                       'max_changed_columns': 1, 'requires_verified_reload_and_rollback': True},
        'baselines': {'unchanged': {},
                      'prompt': {'scope': 'json_targets_only', 'prefix': 'Return only the requested JSON. No markdown or explanation.\n'},
                      'decoding': {'repetition_penalty': 1.1}},
        'generation': {'do_sample': False, 'seed': 1729, 'num_beams': 1,
                       'repetition_penalty': 1.0, 'max_new_tokens': 96},
        'budgets': {'max_candidates': 2, 'max_attempts': 126,
                    'max_attempts_per_variant': 28, 'max_input_tokens_per_attempt': 512,
                    'max_output_tokens_per_attempt': 96, 'max_seconds_per_attempt': 60,
                    'max_worker_seconds': 1800, 'max_concurrency': 1, 'retries': 0},
        'split_policy': {'development': 'selection_only',
                         'heldout': 'once_after_persisted_freeze',
                         'selection': 'schema_gain_then_semantics_then_variant_id_no_regressions',
                         'ties': 'unchanged', 'families': 'disjoint_entities_and_templates',
                         'heldout_reselection': False},
    }


def validate_spec(value):
    """V1 is a fixed recipe; every field participates in identity and must match."""
    try:
        expected = _spec(value['model']['revision'], value['model']['id'])
        if canonical(value) != canonical(expected):
            raise ValueError('unsupported or modified task specification')
    except (KeyError, TypeError) as exc:
        raise ValueError('invalid task specification') from exc


def preview(text, *, revision, model_id=MODEL_ID):
    """Finite phrase mapping, never a claim of arbitrary-language understanding."""
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise ValueError('request text must contain 1..2000 characters')
    normalized = ' '.join(text.casefold().split()).removesuffix('.')
    if normalized not in PHRASES:
        clarification = any(word in normalized for word in ('json', 'schema', 'format'))
        return {'outcome': 'clarification_required' if clarification else 'unsupported',
                'spec': None, 'spec_sha256': None,
                'message': 'Supported goal: return correct JSON matching the specified bounded schema. '
                           'Use: Improve JSON schema adherence. Arbitrary edits and schemas are unsupported.'}
    spec = TaskSpec(canonical(_spec(revision, model_id)))
    return {'outcome': 'ready', 'spec': spec.to_dict(), 'spec_sha256': spec.sha256,
            'message': 'Preview only; no model load, experiment, download or charge.'}
