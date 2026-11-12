"""CC0-1.0 authored public fixtures and data-only evaluation, stdlib only.

No model execution. Public heldout labels are an engineering split, not secrets.
"""
import copy
import math
import re

from .task_contract import canonical, digest, matches_schema, strict_json, TaskSpec

DATASET_ID = 'godseye-authored-json'
DATASET_VERSION = '1.0.0'
ARMS = ('unchanged', 'prompt', 'decoding', 'weight')
VARIANTS = ('unchanged', 'prompt', 'decoding', 'weight-0', 'weight-1')
COMPLETE = 'complete'
STATUSES = ('complete', 'failed', 'budget_limited', 'cancelled', 'incomplete')


def obj(**properties):
    return {'type': 'object', 'properties': properties, 'required': sorted(properties),
            'additionalProperties': False}


def string(*choices):
    result = {'type': 'string', 'maxLength': 80}
    if choices:
        result['enum'] = list(choices)
    return result


def integer(low=0, high=1000):
    return {'type': 'integer', 'minimum': low, 'maximum': high}


def cases(split):
    """Return fresh data: 10 JSON targets + 4 simple text controls per split.

    Six extraction and four classification cases vary fields, value types,
    nesting, negation, quoting, distractors, and explicit decision rules.
    """
    if split not in ('dev', 'heldout'):
        raise ValueError('unknown split')
    if split == 'dev':
        authored = [
            ('badge', 'Extract the badge owner and badge number: owner Mira; badge 17.',
             obj(owner=string(), badge=integer()), {'owner': 'Mira', 'badge': 17}),
            ('parcel', 'Parcel for Quill weighs 8 kg. Ignore tracking code 59. Return recipient and kg.',
             obj(recipient=string(), kg=integer()), {'recipient': 'Quill', 'kg': 8}),
            ('booking', 'Booking: venue Lantern Hall, seats 24, confirmed yes. Return venue, seats, confirmed.',
             obj(venue=string(), seats=integer(), confirmed={'type': 'boolean'}),
             {'venue': 'Lantern Hall', 'seats': 24, 'confirmed': True}),
            ('inventory', 'Stock record: item Brass Kite; available 0; NOT reserved. Return item, count, reserved.',
             obj(item=string(), count=integer(), reserved={'type': 'boolean'}),
             {'item': 'Brass Kite', 'count': 0, 'reserved': False}),
            ('quoted_title', 'Title is exactly A "Small" Map; author Edda. Return title and author.',
             obj(title=string(), author=string()), {'title': 'A "Small" Map', 'author': 'Edda'}),
            ('nested_contact', 'Create a contact object for Noor with city Juniper and postcode 480. '
             'Use person and address with city and postcode.',
             obj(person=string(), address=obj(city=string(), postcode=integer())),
             {'person': 'Noor', 'address': {'city': 'Juniper', 'postcode': 480}}),
            ('support_route', 'Route ticket "I was charged twice" to billing; password issues to account; '
             'everything else to other. Return route.', obj(route=string('billing', 'account', 'other')),
             {'route': 'billing'}),
            ('access_rule', 'Access rule: allow only if age >= 18 and ticket is valid. '
             'Ravi is 18, ticket invalid. Return allow.', obj(allow={'type': 'boolean'}), {'allow': False}),
            ('temperature_band', 'Band rule: below 10 cold, 10 through 25 mild, above 25 hot. '
             'Sensor Hazel reads 25. Return band.', obj(band=string('cold', 'mild', 'hot')), {'band': 'mild'}),
            ('priority_rule', 'Priority rule: urgent when outage=yes, normal otherwise. '
             'Incident Finch: outage=no, note="urgent meeting". Return priority.',
             obj(priority=string('urgent', 'normal')), {'priority': 'normal'}),
        ]
        controls = [('arithmetic', 'What is 7 + 5? Reply only with the integer.', '12'),
                    ('copy', 'Copy exactly this token and nothing else: VELVET', 'VELVET'),
                    ('opposite', 'What is the opposite of north? Reply with one lowercase word.', 'south'),
                    ('count', 'How many letters are in frog? Reply only with the integer.', '4')]
    else:
        authored = [
            ('museum_label', 'Museum label lists creator Solenne and year 1932. '
             'Catalog 712 is unrelated. Return creator and year.',
             obj(creator=string(), year=integer(0, 2100)), {'creator': 'Solenne', 'year': 1932}),
            ('recipe', 'Recipe card: dish Cinder Soup / portions 3 / vegan false. Return dish, portions, vegan.',
             obj(dish=string(), portions=integer(), vegan={'type': 'boolean'}),
             {'dish': 'Cinder Soup', 'portions': 3, 'vegan': False}),
            ('weather_log', 'Weather log at Obsidian Ridge: -6 degrees, snow yes. Return site, degrees, snow.',
             obj(site=string(), degrees=integer(-100, 100), snow={'type': 'boolean'}),
             {'site': 'Obsidian Ridge', 'degrees': -6, 'snow': True}),
            ('invoice_line', 'Invoice line product: Azure Bowl. Quantity: 2. Unit cost: 9. '
             'Return product and total (quantity times unit cost).',
             obj(product=string(), total=integer()), {'product': 'Azure Bowl', 'total': 18}),
            ('escaped_path', 'A sign contains the literal text Left \\ Right. Labeler is Ivo. '
             'Return text and labeler.', obj(text=string(), labeler=string()),
             {'text': 'Left \\ Right', 'labeler': 'Ivo'}),
            ('nested_delivery', 'Delivery log: courier Tamsin, destination town Saffron, zone 6. '
             'Return courier plus destination object with town and zone.',
             obj(courier=string(), destination=obj(town=string(), zone=integer())),
             {'courier': 'Tamsin', 'destination': {'town': 'Saffron', 'zone': 6}}),
            ('library_shelf', 'Shelf policy: maps go to geography, poetry to literature, others to general. '
             'Object Kestrel Atlas is a map. Return shelf.',
             obj(shelf=string('geography', 'literature', 'general')), {'shelf': 'geography'}),
            ('eligibility_rule', 'Eligible when score >= 60 OR exemption=yes. '
             'Candidate Oriel has score 59, exemption yes. Return eligible.',
             obj(eligible={'type': 'boolean'}), {'eligible': True}),
            ('shipping_class', 'Shipping classes: mass < 5 light, 5 to 20 standard, > 20 heavy. '
             'Crate Nacre has mass 5. Return shipping.',
             obj(shipping=string('light', 'standard', 'heavy')), {'shipping': 'standard'}),
            ('alarm_rule', 'Alarm only when smoke AND heat detected. '
             'Station Zephyr: smoke true, heat false, test message="alarm". Return alarm.',
             obj(alarm={'type': 'boolean'}), {'alarm': False}),
        ]
        controls = [('subtraction', 'Compute 19 - 8. Reply only with the integer.', '11'),
                    ('literal', 'Return the following word unchanged: MARBLE', 'MARBLE'),
                    ('antonym', 'Give the lowercase antonym of empty. One word only.', 'full'),
                    ('length', 'Count the letters in lantern. Reply only with the integer.', '7')]
    rows = []
    for index, (family, instruction, schema, answer) in enumerate(authored):
        rows.append({'id': f'{split}-{family}', 'split': split, 'family': family,
                     'task': 'extraction' if index < 6 else 'classification',
                     'schema': schema, 'answer': answer,
                     'prompt': instruction + '\nReturn only correct JSON matching this schema, '
                     'without markdown or preamble: ' + canonical(schema)})
    for family, prompt, answer in controls:
        rows.append({'id': f'{split}-{family}', 'split': split, 'family': family,
                     'task': 'regression', 'schema': None, 'answer': answer, 'prompt': prompt})
    return rows


def dataset_identity():
    return {'id': DATASET_ID, 'version': DATASET_VERSION, 'license': 'CC0-1.0',
            'sha256': digest({s: cases(s) for s in ('dev', 'heldout')}),
            'counts': {'dev_target': 10, 'dev_regression': 4,
                       'heldout_target': 10, 'heldout_regression': 4}}


def score_output(case, output):
    """Formatting and semantics are separate. Invalid JSON cannot be correct."""
    if not isinstance(output, str):
        raise ValueError('output must be text')
    if case['task'] == 'regression':
        return {'schema_ok': None, 'correct': output.strip() == case['answer'], 'error': None}
    try:
        parsed = strict_json(output)
    except ValueError:
        return {'schema_ok': False, 'correct': False, 'error': 'invalid_json'}
    schema_ok = matches_schema(parsed, case['schema'])
    return {'schema_ok': schema_ok,
            'correct': schema_ok and canonical(parsed) == canonical(case['answer']),
            'error': None if schema_ok else 'schema_mismatch'}


def validate_record(record, spec):
    """Exact trusted-adapter envelope. Unknown fields/statuses fail closed."""
    fields = {'attempt_id', 'spec_sha256', 'case_id', 'split', 'variant', 'status',
              'output', 'input_tokens', 'output_tokens', 'elapsed_seconds'}
    if type(record) is not dict or set(record) != fields:
        raise ValueError('record fields')
    if not isinstance(record['attempt_id'], str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', record['attempt_id']):
        raise ValueError('attempt ID')
    if record['spec_sha256'] != spec.sha256 or record['variant'] not in VARIANTS:
        raise ValueError('record identity')
    if record['split'] not in ('dev', 'heldout') or record['status'] not in STATUSES:
        raise ValueError('record split/status')
    if type(record['case_id']) is not str or record['case_id'] not in {c['id'] for c in cases(record['split'])}:
        raise ValueError('unknown case')
    if not isinstance(record['output'], str) or len(record['output'].encode('utf-8')) > 16384:
        raise ValueError('output bound')
    for field in ('input_tokens', 'output_tokens'):
        value = record[field]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('invalid token usage')
    seconds = record['elapsed_seconds']
    if seconds is not None and (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0):
        raise ValueError('invalid elapsed time')
    if record['status'] == COMPLETE and any(record[f] is None for f in
                                           ('input_tokens', 'output_tokens', 'elapsed_seconds')):
        raise ValueError('complete records require measured usage')
    return copy.deepcopy(record)


def _records(spec, records):
    if not isinstance(spec, TaskSpec):
        raise ValueError('validated TaskSpec required')
    if type(records) is not list:
        raise ValueError('ordered record list required')
    return [validate_record(r, spec) for r in records]


def _accounting(spec, records):
    limits = spec.to_dict()['budgets']
    issues = []
    if len(records) > limits['max_attempts']:
        issues.append('attempt_budget')
    if len({r['attempt_id'] for r in records}) != len(records):
        issues.append('duplicate_attempt_id')
    if any(sum(r['variant'] == v for r in records) > limits['max_attempts_per_variant'] for v in VARIANTS):
        issues.append('variant_budget')
    if any(r['input_tokens'] is None or r['output_tokens'] is None or r['elapsed_seconds'] is None for r in records):
        issues.append('unknown_usage')
    if any((r['input_tokens'] or 0) > limits['max_input_tokens_per_attempt'] or
           (r['output_tokens'] or 0) > limits['max_output_tokens_per_attempt'] or
           (r['elapsed_seconds'] or 0) > limits['max_seconds_per_attempt'] for r in records):
        issues.append('attempt_resource_budget')
    if sum(r['elapsed_seconds'] or 0 for r in records) > limits['max_worker_seconds']:
        issues.append('worker_budget')
    return issues


def _wilson(successes, n):
    if not n:
        return None
    z = 1.959963984540054
    rate = successes / n
    divisor = 1 + z * z / n
    center = (rate + z * z / (2 * n)) / divisor
    radius = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / divisor
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _arm(records, split, variant):
    expected = cases(split)
    selected = [r for r in records if r['split'] == split and r['variant'] == variant]
    groups = {c['id']: [r for r in selected if r['case_id'] == c['id']] for c in expected}
    complete = all(len(group) == 1 and group[0]['status'] == COMPLETE for group in groups.values())
    scored = []
    for case in expected:
        for record in groups[case['id']]:
            score = score_output(case, record['output'])
            scored.append(dict(record, task=case['task'], **score))
    targets = [r for r in scored if r['task'] != 'regression']
    regression = [r for r in scored if r['task'] == 'regression']
    schema_n = sum(r['schema_ok'] for r in targets)
    correct_n = sum(r['correct'] for r in targets)
    # Attempt counts are visible even on incomplete arms; rates require all cases exactly once.
    return {'variant': variant, 'complete': complete, 'expected': len(expected),
            'attempts': len(selected), 'target_n': len(targets), 'regression_n': len(regression),
            'schema_successes': schema_n, 'semantic_successes': correct_n,
            'regression_successes': sum(r['correct'] for r in regression),
            'schema_rate': schema_n / len(targets) if complete else None,
            'semantic_rate': correct_n / len(targets) if complete else None,
            'schema_interval': _wilson(schema_n, len(targets)) if complete else None,
            'semantic_interval': _wilson(correct_n, len(targets)) if complete else None,
            'regression_interval': _wilson(sum(r['correct'] for r in regression), len(regression))
                                   if complete else None,
            'records': scored}


def freeze_selection(spec, development_records):
    """Recompute all dev evidence; never accepts heldout data or supplied scores.

    Caller must persist this freeze BEFORE requesting any heldout generation.
    This pure function cannot attest to wall-clock ordering or artifact durability.
    """
    records = _records(spec, development_records)
    if any(r['split'] != 'dev' for r in records):
        raise ValueError('heldout data forbidden during selection')
    issues = _accounting(spec, records)
    summaries = {v: _arm(records, 'dev', v) for v in VARIANTS}
    base = summaries['unchanged']
    eligible = []
    if not issues and all(a['complete'] for a in summaries.values()):
        for variant in ('weight-0', 'weight-1'):
            arm = summaries[variant]
            if (arm['schema_rate'] > base['schema_rate'] and
                    _regressions(base, arm, 'target') == 0 and
                    _regressions(base, arm, 'regression') == 0):
                eligible.append(variant)
    selected = min(eligible, key=lambda v: (-summaries[v]['schema_rate'],
                                          -summaries[v]['semantic_rate'], v)) if eligible else 'unchanged'
    value = {'version': 'godseye-lm-freeze-v1', 'spec_sha256': spec.sha256,
             'dev_records_sha256': digest(records), 'selected_weight': selected,
             'heldout_variants': ['unchanged', 'prompt', 'decoding'] +
                                 ([selected] if selected != 'unchanged' else []),
             'selection_eligible': not issues and all(a['complete'] for a in summaries.values()),
             'accounting_issues': issues}
    return dict(value, sha256=digest(value))


def _regressions(base, arm, task):
    original = {r['case_id']: r for r in base['records']}
    return sum(original[r['case_id']]['correct'] and not r['correct'] for r in arm['records']
               if (r['task'] == 'regression') == (task == 'regression'))


def _comparison(base, arm, spec):
    complete = base['complete'] and arm['complete']
    target_n = base['target_n']
    if not complete:
        return {'verdict': 'not_evaluated', 'paired_target_n': 0,
                'schema_difference': None, 'difference_interval': None,
                'semantic_regressions': None, 'regression_failures': None}
    difference = arm['schema_rate'] - base['schema_rate']
    # Hoeffding for paired differences in [-1,1]. Wide by design on this tiny suite.
    radius = math.sqrt(2 * math.log(40) / target_n)
    interval = [max(-1.0, difference - radius), min(1.0, difference + radius)]
    semantic_regressions = _regressions(base, arm, 'target')
    control_regressions = _regressions(base, arm, 'regression')
    limits = spec.to_dict()['metrics']
    if semantic_regressions or control_regressions or difference <= 0:
        verdict = 'no_improvement'
    elif interval[0] <= limits['min_schema_gain']:
        verdict = 'inconclusive'
    else:
        verdict = 'improved_on_public_fixture'
    return {'verdict': verdict, 'paired_target_n': target_n,
            'schema_difference': difference, 'difference_interval': interval,
            'semantic_regressions': semantic_regressions, 'regression_failures': control_regressions}


def evaluate(spec, freeze, records):
    """Validate frozen selection and return every supplied attempt, never run a model."""
    records = _records(spec, records)
    dev = [r for r in records if r['split'] == 'dev']
    if freeze != freeze_selection(spec, dev):
        raise ValueError('freeze mismatch: selection or development evidence changed')
    seen_heldout = False
    for record in records:
        if record['split'] == 'heldout':
            seen_heldout = True
        elif seen_heldout:
            raise ValueError('development after heldout is forbidden')
    heldout_variants = freeze['heldout_variants']
    issues = _accounting(spec, records)
    if any(r['split'] == 'heldout' and r['variant'] not in heldout_variants for r in records):
        issues.append('unfrozen_heldout_variant')
    dev_arms = {v: _arm(records, 'dev', v) for v in VARIANTS}
    heldout = {v: _arm(records, 'heldout', v) for v in heldout_variants}
    complete = (freeze['selection_eligible'] and not issues and
                all(a['complete'] for a in heldout.values()))
    comparisons = {v: _comparison(heldout['unchanged'], heldout[v], spec)
                   for v in heldout_variants if v != 'unchanged'}
    if not complete:
        for comparison in comparisons.values():
            comparison['verdict'] = 'not_evaluated'
    selected = freeze['selected_weight']
    verdict = (comparisons[selected]['verdict'] if selected != 'unchanged' else 'no_improvement') \
        if complete else 'not_evaluated'
    return {'spec_sha256': spec.sha256, 'dataset': dataset_identity(),
            'status': 'complete' if complete else 'incomplete', 'verdict': verdict,
            'accounting_issues': issues, 'attempt_count': len(records),
            'records': copy.deepcopy(records), 'development': dev_arms,
            'heldout': heldout, 'comparisons': comparisons,
            'limitations': 'Public authored CC0 fixture; no private test, contamination guarantee, '
                           'generalization proof, speedup or cost claim. Intervals are descriptive '
                           'bounds under independent-case assumptions, not calibrated population evidence.'}
