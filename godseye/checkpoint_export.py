"""Read-only projection of completed trusted experiments into safe model artifacts."""
import io
import json
import os
import stat
import statistics
import math
from pathlib import Path
import zipfile

import numpy as np

from .checkpoint_artifact import (
    FORMAT, INSTRUCTIONS, MAX_BYTES, MAX_CASES, canonical, content_hash, hex_id,
    reload_artifact,
)
from .core import NAMES, digest
from .experiment_spec import ContractError, loads_message, validate_message
from .orchestration import audit_selections, verify_registration


def read_file(root, relative, maximum):
    root = Path(root).absolute()
    path = root
    if root.is_symlink():
        raise ValueError()
    for part in Path(relative).parts:
        if part in ('..', '.', '') or Path(part).is_absolute():
            raise ValueError()
        path = path / part
        if path.is_symlink():
            raise ValueError()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise ValueError()
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError()
    return raw


def read_json(root, relative):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    return json.loads(read_file(root, relative, MAX_BYTES), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def weights(root, role, identifier):
    hex_id(identifier, 32)
    if role not in ('agent', 'heuristic', 'unchanged'):
        raise ValueError()
    raw = read_file(root, role + '/' + identifier + '.npz', 128 * 1024)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if (len(members) != len(NAMES) or {m.filename for m in members} !=
                {key + '.npy' for key, _ in NAMES.values()}
                or sum(m.file_size for m in members) > 100 * 1024
                or any(m.flag_bits & 1 for m in members)):
            raise ValueError()
        # Validate NPY headers before numpy can allocate an attacker-declared shape.
        for name, (key, shape) in NAMES.items():
            with archive.open(key + '.npy') as stream:
                version = np.lib.format.read_magic(stream)
                if version != (1, 0):
                    raise ValueError()
                actual, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                if actual != shape or fortran or dtype != np.dtype('<f4'):
                    raise ValueError()
                if len(stream.read()) != int(np.prod(shape)) * 4:
                    raise ValueError()
    with np.load(io.BytesIO(raw), allow_pickle=False) as source:
        result = {n: source[key].copy() for n, (key, _) in NAMES.items()}
    if any(not np.isfinite(v).all() for v in result.values()):
        raise ValueError()
    return result


def export_checkpoint(service, raw):
    request = loads_message(raw)
    if (type(request) is not dict or set(request) !=
            {'schema_version', 'experiment_id', 'artifact_id'}
            or type(request['schema_version']) is not int or request['schema_version'] != 1):
        raise ContractError('invalid_schema')
    try:
        hex_id(request['experiment_id'], 32)
        hex_id(request['artifact_id'], 32)
    except ValueError:
        raise ContractError('not_found') from None
    # Authorization comes from the server's operator scope, before any content lookup.
    with service.transaction():
        service.throttle('read', service.limits.reads_per_minute)
    try:
        with service.lock:
            row = service.load(request['experiment_id'], 'run')
            if row['status'] != 'completed' or row['evidence'] is None:
                raise ContractError('result_not_ready')
            validate_message('results_response', service.response(row, 'results'))
            evidence = row['evidence']
            if request['artifact_id'] != evidence['candidate_manifest_id']:
                raise ValueError()
            registration = service.registration(row['spec']['baseline']['id'])
            directory = service.directory / row['id']
            private = registration['directory']
            # Membership before paths, including internal references and all participants.
            artifacts = {}
            for kind, field in (('manifest', 'candidate_manifest_id'),
                                ('delta', 'delta_artifact_id'), ('report', 'report_id')):
                identifier = hex_id(evidence[field], 32)
                expected = directory / (identifier + '.json')
                if row['artifacts'].get(identifier) != str(expected):
                    raise ValueError()
                artifacts[kind] = read_json(service.directory, row['id'] + '/' + identifier + '.json')
            report = artifacts['report']
            if set(report) != {'agent', 'heuristic', 'unchanged'}:
                raise ValueError()
            read_json(private, 'experiment.json')
            cached = {}
            for role, state in report.items():
                if read_json(private, role + '/private-state.json') != state:
                    raise ValueError()
                if not 1 <= len(state['cases']) <= MAX_CASES:
                    raise ValueError()
                # Bound every file the legacy integrity verifier will inspect first.
                cached[role] = {state['reference_id']: weights(private, role, state['reference_id'])}
                for case in state['cases']:
                    if not 1 <= len(case['candidates']) <= 101 or len(case['attempts']) > 100:
                        raise ValueError()
                    chosen = case['final']['candidate_id']
                    candidates = {hex_id(c['id'], 32): c for c in case['candidates']}
                    if len(candidates) != len(case['candidates']):
                        raise ValueError()
                    cursor, seen = chosen, set()
                    while cursor != case['root_id']:
                        if cursor in seen or cursor not in candidates:
                            raise ValueError()
                        seen.add(cursor)
                        cursor = hex_id(candidates[cursor]['parent'], 32)
                    if candidates[cursor]['parent'] is not None:
                        raise ValueError()
                    root_score, chosen_score = None, None
                    for probe in case['attempts']:
                        if probe['status'] != 'completed':
                            continue
                        scores = probe['result']['scores']
                        mean = probe['result']['mean_score']
                        if (len(scores) != row['spec']['evaluation']['episodes']
                                or type(mean) not in (int, float) or not np.isfinite(mean)
                                or any(type(v) not in (int, float) or not np.isfinite(v) for v in scores)
                                or mean != sum(scores) / len(scores)):
                            raise ValueError()
                        if probe['candidate_id'] == case['root_id']:
                            root_score = mean
                        elif probe['candidate_id'] == chosen and root_score is not None:
                            chosen_score = mean
                    if chosen != case['root_id'] and (
                            root_score is None or chosen_score is None or chosen_score <= root_score):
                        raise ValueError()
                    if not any(c['id'] == chosen for c in case['candidates']):
                        raise ValueError()
                    for identifier in (case['root_id'], chosen):
                        cached[role][identifier] = weights(private, role, identifier)
            # Read-only: no evaluator._read/recovery/reveal or assembler writes.
            states = verify_registration(registration, row['spec'], fresh=False)
            if states != report:
                raise ValueError()
            audit_selections(states)
            manifest, patches, checkpoints, deltas, controls = [], [], [], [], []
            for role, state in states.items():
                for case in state['cases']:
                    final = case['final']
                    if not case['finalized'] or final['status'] != 'completed':
                        raise ValueError()
                    for arm in ('reference', 'corrupted', 'selected'):
                        scores = final[arm]['scores']
                        if (len(scores) != row['spec']['evaluation']['episodes']
                                or any(type(v) not in (float, int) or not np.isfinite(v) for v in scores)):
                            raise ValueError()
                    paired = [a - b for a, b in zip(final['selected']['scores'], final['corrupted']['scores'])]
                    if final['paired_corrupted']['differences'] != paired:
                        raise ValueError()
                    root, chosen = case['root_id'], final['candidate_id']
                    original, selected = cached[role][root], cached[role][chosen]
                    manifest.append(dict(participant=role, case_id=case['id'], root_id=root,
                                         selected_id=chosen, root_sha256=digest(original),
                                         selected_sha256=digest(selected)))
                    patches.append(dict(participant=role, case_id=case['id'], root_id=root,
                                        selected_id=chosen, candidates=case['candidates'], paired_deltas=paired))
                    if role != 'agent':
                        continue
                    deltas.extend(paired)
                    if case['family'] == 'control':
                        controls.append(statistics.mean(paired))
                    delta = []
                    for name in NAMES:
                        before, after = original[name].ravel(), selected[name].ravel()
                        for index in np.flatnonzero(before.view(np.uint32) != after.view(np.uint32)):
                            delta.append(dict(tensor=name, index=int(index), before=float(before[index]),
                                              after=float(after[index])))
                    checkpoints.append(dict(slot=len(checkpoints), outcome='changed' if delta else 'unchanged',
                        original_sha256=digest(original), selected_sha256=digest(selected),
                        original={n: a.ravel().tolist() for n, a in original.items()}, delta=delta))
            # Assembler preserves participant order, independent of JSON object ordering.
            order = {role: i for i, role in enumerate(('unchanged', 'heuristic', 'agent'))}
            manifest.sort(key=lambda v: order[v['participant']])
            patches.sort(key=lambda v: order[v['participant']])
            if manifest != artifacts['manifest'] or patches != artifacts['delta']:
                raise ValueError()
            if not controls or len(deltas) < 2:
                raise ValueError()
            expected_summary = dict(baseline_id=row['spec']['baseline']['id'], paired_samples=len(deltas),
                mean_delta=statistics.mean(deltas), paired_se=statistics.stdev(deltas) / math.sqrt(len(deltas)),
                min_control_delta=min(controls))
            if any(evidence[k] != v for k, v in expected_summary.items()):
                raise ValueError()
            value = dict(schema_version=1, format=FORMAT, experiment_id=row['id'], spec_hash=row['hash'],
                         artifact_id=request['artifact_id'], baseline_id=row['spec']['baseline']['id'],
                         checkpoints=checkpoints, instructions=INSTRUCTIONS)
            value['content_sha256'] = content_hash(value)
            output = canonical(value)
            reload_artifact(output, expected_sha256=value['content_sha256'])
            return output
    except ContractError as error:
        if error.code in ('result_not_ready', 'not_found'):
            raise
        raise ContractError('not_found') from None
    except Exception:
        raise ContractError('not_found') from None
