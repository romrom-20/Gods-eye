"""Additive activity contract schemas; experiment_spec.SCHEMAS v1 is unchanged."""
from .activity import ARMS, KINDS, MAX_SEQUENCE, OPERATIONS


def obj(fields):
    return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)


def integer(low, high):
    return dict(type='integer', minimum=low, maximum=high)


ID = dict(type='string', minLength=1, maxLength=64, pattern='^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
HASH = dict(type='string', minLength=64, maxLength=64, pattern='^[0-9a-f]{64}$')
SEQUENCE = integer(0, MAX_SEQUENCE)
EVENT = obj(dict(sequence=integer(1, MAX_SEQUENCE), kind=dict(enum=sorted(KINDS)),
                 operation=dict(enum=sorted(OPERATIONS)), arm=dict(enum=sorted(ARMS)),
                 count=dict(anyOf=[integer(0, 256), dict(type='null')])))
SCOPE = dict(schema_version=dict(enum=[1]), experiment_id=ID, spec_hash=HASH)
SCHEMAS = dict(
    activity_request=obj(dict(SCOPE, after=SEQUENCE, limit=integer(1, 100))),
    activity_response=obj(dict(SCOPE, available=dict(type='boolean'),
        status=dict(enum=['queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled', 'interrupted']),
        phase=obj(dict(name=dict(enum=['unknown', 'checking_original', 'trying_edit', 'testing']),
            event_sequence=dict(anyOf=[integer(1, MAX_SEQUENCE), dict(type='null')]))),
        events=dict(type='array', items=EVENT, maxItems=100), next_cursor=SEQUENCE,
        high_water=SEQUENCE, gap=dict(type='boolean'), has_more=dict(type='boolean'))))
