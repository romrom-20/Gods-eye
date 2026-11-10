"""Offline experiment contract v1. No persistence, credentials, transport or launch.

SCHEMAS is a JSON Schema-compatible structural contract. validate_message also
checks cross-field invariants; validate_spec additionally binds operator policy.
See docs/experiment-contract.md for service transactions and evidence provenance.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from types import MappingProxyType

from .provider_discovery import MODEL_PATTERN

VERSION = 1
MAX_BYTES = 65536
STATUSES = ('draft', 'ready', 'queued', 'running', 'cancelling', 'completed',
            'failed', 'cancelled', 'interrupted')
TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')
VERDICTS = ('not_evaluated', 'improved', 'no_improvement', 'inconclusive')
TRANSITIONS = {
    'draft': ('ready', 'cancelled'), 'ready': ('queued', 'cancelled'),
    'queued': ('running', 'cancelling', 'failed', 'interrupted'),
    'running': ('cancelling', 'completed', 'failed', 'interrupted'),
    'cancelling': ('cancelled', 'failed', 'interrupted'),
    **{s: () for s in TERMINAL},
}
# Mirrors existing adapter defaults; never import the standalone adapter into a service.
DEFAULT_CEILINGS = MappingProxyType(dict(
    max_requests=80, max_input_tokens=200000, max_total_output_tokens=20000,
    max_seconds=900, max_rounds=80, max_calls=160, max_output_tokens=2000))
MESSAGES = {
    'invalid_json': 'Expected bounded, unambiguous UTF-8 JSON.',
    'invalid_schema': 'Message does not match experiment contract v1.',
    'unsupported_version': 'Unsupported experiment contract version.',
    'policy_violation': 'Specification exceeds or differs from trusted policy.',
    'clarification_required': 'Use an explicit supported Breakout score-improvement request.',
    'unsupported_goal': 'Only the existing Breakout score-improvement goal is supported.',
    'spec_conflict': 'The reviewed specification has changed.',
    'state_conflict': 'Operation is unavailable in the current state.',
    'idempotency_conflict': 'Idempotency key is already bound to another submission.',
    'not_found': 'Experiment is unavailable in this scope.',
    'result_not_ready': 'The experiment has no terminal result yet.',
    'not_authorized': 'Operation is not authorized.',
    'unavailable': 'Experiment service is unavailable.',
}


class ContractError(ValueError):
    """Fixed safe message; never include input values or unknown property names."""
    def __init__(self, code, field='$'):
        self.code = code
        self.field = field if type(field) is str and field in _SAFE_PATHS else '$'
        super().__init__(MESSAGES[code])

    def issue(self):
        return dict(code=self.code, field=self.field, message=MESSAGES[self.code])

    def response(self):
        return dict(schema_version=VERSION, error=self.issue())


def _object(**properties):
    return dict(type='object', properties=properties, required=list(properties),
                additionalProperties=False)


def _enum(*values):
    return {'enum': list(values)}


def _integer(low=0, high=None):
    result = dict(type='integer', minimum=low)
    if high is not None:
        result['maximum'] = high
    return result


def _text(low=1, high=500, pattern=None):
    result = dict(type='string', minLength=low, maxLength=high)
    if pattern:
        result['pattern'] = pattern
    return result


def _array(items, low, high):
    return dict(type='array', items=items, minItems=low, maxItems=high)


def _nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


_ID = _text(1, 64, r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_HASH = _text(64, 64, r'^[0-9a-f]{64}$')
_NUMBER = {'type': 'number'}
_NONNEGATIVE = dict(type='number', minimum=0)
_PROVIDER = _object(name=_enum('openai', 'openrouter', 'huggingface'),
                    model=_text(1, 128, '^' + MODEL_PATTERN + '$'),
                    routing=_enum('price', 'latency', 'throughput'))
_LIMITS = _object(**{k: _integer(1) for k in DEFAULT_CEILINGS})
_EVALUATION = _object(
    suite_id=_ID, revision=_ID, episodes=_integer(2, 8), max_steps=_integer(1, 1000),
    probes_per_case=_integer(2, 100), forwards_per_case=_integer(1, 1000000),
    development=_enum('selection_only'), held_out=_enum('once_after_all_freezes'))
_SPEC = _object(
    schema_version=_enum(VERSION), target=_enum('breakout'), goal=_enum('improve_score'),
    baseline=_object(id=_ID, sha256=_HASH), evaluation=_EVALUATION,
    success=_enum('positive_paired_mean_2se_and_no_control_regression'),
    editing=_enum('numeric_tensor_assignments_v1'), provider=_PROVIDER, limits=_LIMITS)
_ISSUE = _object(code=_enum(*MESSAGES), field=_text(1, 200), message=_text(1, 500))
_USAGE = _object(requests=_integer(), input_tokens=_integer(), output_tokens=_integer(),
                 tool_calls=_integer(), elapsed_seconds=_NONNEGATIVE,
                 usage_complete={'type': 'boolean'}, request_in_flight={'type': 'boolean'})
_EVIDENCE = _object(
    baseline_id=_ID, candidate_manifest_id=_ID, delta_artifact_id=_ID, report_id=_ID,
    paired_samples=_integer(2), mean_delta=_NUMBER, paired_se=_NONNEGATIVE,
    min_control_delta=_NUMBER, limitations=_array(_text(), 1, 10))
_REASONS = _nullable(_enum('budget_exhausted', 'provider_error', 'evaluation_error',
                          'agent_incomplete', 'runtime_failure', 'user_cancelled', 'process_lost'))
_QUERY = _object(schema_version=_enum(VERSION), experiment_id=_ID)
_STATUS = _object(schema_version=_enum(VERSION), experiment_id=_ID, spec_hash=_HASH,
                  status=_enum(*STATUSES), verdict=_enum(*VERDICTS), reason=_REASONS,
                  usage=_USAGE)
SCHEMAS = {
    'spec': _SPEC,
    'plan_request': _object(schema_version=_enum(VERSION), text=_text(1, 2000),
                            provider=_PROVIDER, limits=_LIMITS),
    'plan_response': _object(
        schema_version=_enum(VERSION), outcome=_enum('ready', 'clarification_required', 'rejected'),
        draft_id=_nullable(_ID), spec=_nullable(_SPEC), spec_hash=_nullable(_HASH),
        issues=_array(_ISSUE, 0, 10)),
    'start_request': _object(schema_version=_enum(VERSION), draft_id=_ID, spec_hash=_HASH,
                             idempotency_key=_ID, confirmed={'const': True}),
    'start_response': _object(schema_version=_enum(VERSION), experiment_id=_ID,
                              spec_hash=_HASH, status=_enum(*STATUSES[2:])),
    'status_request': _QUERY, 'cancel_request': _QUERY, 'results_request': _QUERY,
    'status_response': _STATUS, 'cancel_response': _STATUS,
    'results_response': _object(**_STATUS['properties'], evidence=_nullable(_EVIDENCE)),
    'error_response': _object(schema_version=_enum(VERSION), error=_ISSUE),
}


def _schema_paths(schema, path='$'):
    paths = {path}
    for key, child in schema.get('properties', {}).items():
        paths.update(_schema_paths(child, path + '.' + key))
    for child in schema.get('anyOf', []):
        paths.update(_schema_paths(child, path))
    if 'items' in schema:
        paths.update(_schema_paths(schema['items'], path + '[]'))
    return paths


_SAFE_PATHS = set().union(*(_schema_paths(schema) for schema in SCHEMAS.values()))


def _json_shape(value, depth=0):
    if depth > 16:
        raise ContractError('invalid_json')
    if type(value) in (dict, list):
        if type(value) is dict and any(type(k) is not str for k in value):
            raise ContractError('invalid_json')
        for item in (value.values() if type(value) is dict else value):
            _json_shape(item, depth + 1)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ContractError('invalid_json')
    elif type(value) is float and not math.isfinite(value):
        raise ContractError('invalid_json')


def canonical_json(value):
    _json_shape(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)
    except (ValueError, OverflowError, RecursionError):
        raise ContractError('invalid_json') from None


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def loads_message(raw):
    """Strict raw JSON ingress; use before validate_message to reject duplicate keys."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def constant(_):
        raise ValueError()

    try:
        if type(raw) is str:
            raw = raw.encode('utf-8')
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
            raise ValueError()
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
        _json_shape(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ContractError('invalid_json') from None


def _check(value, schema, path='$'):
    if 'anyOf' in schema:
        for alternative in schema['anyOf']:
            try:
                _check(value, alternative, path)
                return
            except ContractError:
                pass
        raise ContractError('invalid_schema', path)
    if 'const' in schema:
        if type(value) is not type(schema['const']) or value != schema['const']:
            raise ContractError('invalid_schema', path)
    if 'enum' in schema:
        if not any(type(value) is type(item) and value == item for item in schema['enum']):
            raise ContractError('invalid_schema', path)
    kind = schema.get('type')
    kinds = {'object': (dict,), 'array': (list,), 'string': (str,), 'integer': (int,),
             'number': (int, float), 'boolean': (bool,), 'null': (type(None),)}
    if kind and type(value) not in kinds[kind]:
        raise ContractError('invalid_schema', path)
    if kind == 'object':
        if set(value) != set(schema['required']):
            raise ContractError('invalid_schema', path)
        for key, child in schema['properties'].items():
            _check(value[key], child, path + '.' + key)
    elif kind == 'array':
        if not schema['minItems'] <= len(value) <= schema['maxItems']:
            raise ContractError('invalid_schema', path)
        for item in value:
            _check(item, schema['items'], path + '[]')
    elif kind == 'string':
        if (not schema['minLength'] <= len(value) <= schema['maxLength']
                or ('pattern' in schema and not re.fullmatch(schema['pattern'], value))):
            raise ContractError('invalid_schema', path)
    elif kind in ('number', 'integer'):
        if (('minimum' in schema and value < schema['minimum'])
                or ('maximum' in schema and value > schema['maximum'])):
            raise ContractError('invalid_schema', path)


def _provider(value):
    model = value['model']
    if ('//' in model or any(part in ('.', '..') for part in model.split('/'))
            or re.match(r'^[A-Za-z]:/', model)):
        raise ContractError('invalid_schema', '$.provider.model')
    if value['name'] != 'openrouter' and value['routing'] != 'price':
        raise ContractError('invalid_schema', '$.provider.routing')


def evidence_verdict(evidence):
    """Interpret a complete, trusted summary; cannot certify provenance/completeness."""
    _json_shape(evidence)
    _check(evidence, _EVIDENCE)
    if evidence['mean_delta'] <= 0 or evidence['min_control_delta'] < 0:
        return 'no_improvement'
    if evidence['mean_delta'] - 2 * evidence['paired_se'] > 0:
        return 'improved'
    return 'inconclusive'


def validate_message(kind, value):
    """Validate exact shape and semantic invariants; returns an independent copy."""
    if kind not in SCHEMAS:
        raise ValueError('Unknown contract message kind')
    _json_shape(value)
    if len(canonical_json(value).encode('utf-8')) > MAX_BYTES:
        raise ContractError('invalid_json')
    if type(value) is dict and 'schema_version' in value:
        if type(value['schema_version']) is not int or value['schema_version'] != VERSION:
            raise ContractError('unsupported_version', '$.schema_version')
    _check(value, SCHEMAS[kind])
    if kind in ('spec', 'plan_request'):
        _provider(value['provider'])
    if kind == 'spec':
        e = value['evaluation']
        if e['forwards_per_case'] < e['episodes'] * e['max_steps'] * e['probes_per_case']:
            raise ContractError('policy_violation', '$.evaluation.forwards_per_case')
    if kind == 'plan_response':
        ready = value['outcome'] == 'ready'
        if ready:
            if (value['draft_id'] is None or value['spec'] is None or value['issues']
                    or value['spec_hash'] != _hash(value['spec'])):
                raise ContractError('invalid_schema')
            validate_message('spec', value['spec'])
        elif (any(value[k] is not None for k in ('draft_id', 'spec', 'spec_hash'))
              or not value['issues']):
            raise ContractError('invalid_schema')
        else:
            code = ('unsupported_goal' if value['outcome'] == 'rejected'
                    else 'clarification_required')
            if any(issue['code'] != code for issue in value['issues']):
                raise ContractError('invalid_schema', '$.issues')
    if kind.endswith('_response') and 'verdict' in value:
        status, verdict, reason = value['status'], value['verdict'], value['reason']
        expected = {'cancelled': ('user_cancelled',), 'interrupted': ('process_lost',),
                    'failed': ('budget_exhausted', 'provider_error', 'evaluation_error',
                               'agent_incomplete', 'runtime_failure')}.get(status, (None,))
        if reason not in expected:
            raise ContractError('invalid_schema', '$.reason')
        if (status == 'completed') != (verdict != 'not_evaluated'):
            raise ContractError('invalid_schema', '$.verdict')
        if kind == 'results_response':
            if status not in TERMINAL:
                raise ContractError('result_not_ready')
            evidence = value['evidence']
            if (status == 'completed') != (evidence is not None):
                raise ContractError('invalid_schema', '$.evidence')
            if evidence is not None and verdict != evidence_verdict(evidence):
                raise ContractError('invalid_schema', '$.verdict')
    if kind == 'error_response' or kind == 'plan_response':
        issues = [value['error']] if kind == 'error_response' else value['issues']
        for issue in issues:
            if (issue['message'] != MESSAGES[issue['code']]
                    or issue['field'] not in _SAFE_PATHS):
                raise ContractError('invalid_schema', '$')
    return json.loads(canonical_json(value))


@dataclass(frozen=True)
class PlanningPolicy:
    """Trusted registry binding; never construct from a client/model request."""
    baseline_id: str
    baseline_sha256: str
    suite_id: str
    revision: str
    episodes: int = 2
    max_steps: int = 200
    probes_per_case: int = 2
    forwards_per_case: int = 800
    ceilings: object = field(default_factory=lambda: dict(DEFAULT_CEILINGS))

    def __post_init__(self):
        _check(self.baseline(), _SPEC['properties']['baseline'])
        _check(self.evaluation(), _EVALUATION)
        _check(self.ceilings, _LIMITS)
        if any(self.ceilings[k] > DEFAULT_CEILINGS[k] for k in DEFAULT_CEILINGS):
            raise ContractError('policy_violation', '$.limits')
        if self.forwards_per_case < self.episodes * self.max_steps * self.probes_per_case:
            raise ContractError('policy_violation', '$.evaluation.forwards_per_case')
        object.__setattr__(self, 'ceilings', MappingProxyType(dict(self.ceilings)))

    def baseline(self):
        return dict(id=self.baseline_id, sha256=self.baseline_sha256)

    def evaluation(self):
        return dict(suite_id=self.suite_id, revision=self.revision, episodes=self.episodes,
                    max_steps=self.max_steps, probes_per_case=self.probes_per_case,
                    forwards_per_case=self.forwards_per_case, development='selection_only',
                    held_out='once_after_all_freezes')


@dataclass(frozen=True)
class ExperimentSpec:
    """Immutable structural spec. Use validate_spec for trusted policy validation."""
    _canonical: str

    def __post_init__(self):
        value = validate_message('spec', loads_message(self._canonical))
        object.__setattr__(self, '_canonical', canonical_json(value))

    @property
    def sha256(self):
        return hashlib.sha256(self._canonical.encode('utf-8')).hexdigest()

    def to_dict(self):
        return json.loads(self._canonical)


def validate_spec(value, policy):
    value = validate_message('spec', value)
    if value['baseline'] != policy.baseline():
        raise ContractError('policy_violation', '$.baseline')
    if value['evaluation'] != policy.evaluation():
        raise ContractError('policy_violation', '$.evaluation')
    for name, ceiling in policy.ceilings.items():
        if value['limits'][name] > ceiling:
            raise ContractError('policy_violation', '$.limits.' + name)
    return ExperimentSpec(canonical_json(value))


def plan(request, policy, *, draft_id):
    """Build a response only. Caller must persist ready drafts before publishing."""
    request = validate_message('plan_request', request)
    text = ' '.join(request['text'].casefold().split())
    if text.endswith('.'):
        text = text[:-1]
    phrases = ('improve breakout score', 'improve the breakout score',
               'improve breakout score without control regressions')
    if text not in phrases:
        clarify = 'breakout' in text
        code = 'clarification_required' if clarify else 'unsupported_goal'
        return validate_message('plan_response', dict(
            schema_version=VERSION, outcome='clarification_required' if clarify else 'rejected',
            draft_id=None, spec=None, spec_hash=None,
            issues=[ContractError(code, '$.text').issue()]))
    spec = validate_spec(dict(
        schema_version=VERSION, target='breakout', goal='improve_score', baseline=policy.baseline(),
        evaluation=policy.evaluation(), success='positive_paired_mean_2se_and_no_control_regression',
        editing='numeric_tensor_assignments_v1', provider=request['provider'],
        limits=request['limits']), policy)
    return validate_message('plan_response', dict(
        schema_version=VERSION, outcome='ready', draft_id=draft_id,
        spec=spec.to_dict(), spec_hash=spec.sha256, issues=[]))


def confirm_start(request, stored_spec, policy, *, draft_id, status):
    """Pure pre-admission check. Service must handle atomic/idempotent admission."""
    request = validate_message('start_request', request)
    spec = validate_spec(stored_spec, policy)
    if request['draft_id'] != draft_id or request['spec_hash'] != spec.sha256:
        raise ContractError('spec_conflict')
    if status != 'ready':
        raise ContractError('state_conflict')
    return spec


def transition(current, following):
    """Check a transition; persistence/concurrency are the service's responsibility."""
    if (type(current) is not str or type(following) is not str
            or following not in TRANSITIONS.get(current, ())):
        raise ContractError('state_conflict')
    return following
