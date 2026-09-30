"""Verify retained public-run reports offline; no network or database operations."""
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def p(values, fraction):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * fraction))], 4) if values else None


with tarfile.open(ROOT / 'raw-evidence.tar.gz') as archive:
    members = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
manifest = read('raw-evidence-manifest.json')
assert set(manifest) == set(members)
for name, expected in manifest.items():
    assert sha(members[name]) == expected['sha256'], name
    assert len(members[name]) == expected['bytes'], name
for name in ['cold-1', 'ready-1']:
    report = read(name + '.json')
    assert members[name + '.json'] == (ROOT / (name + '.json')).read_bytes()
    assert report['completed'] and not report['errors']
    assert report['parameters']['users'] == 1500
    assert report['parameters']['url'] == 'https://wjy-1214.cloud'
    assert report['parameters']['ssh'] == 'ubuntu@43.142.19.144'
    assert not report['production_capacity_verified']
    rows = collections.defaultdict(list)
    completed = confirmed = 0
    for part in report['parts']:
        raw = members[part['file']]
        assert sha(raw) == part['sha256']
        run = json.loads(raw)['runs'][0]
        completed += run['completed_students']
        confirmed += run['confirmed_enrollments']
        for stage, values in run['raw_stages'].items():
            rows[stage].extend(values)
    run = report['runs'][0]
    assert run['completed_students'] == completed
    assert run['confirmed_enrollments'] == confirmed == run['db']['enrollments']
    assert run['db']['inconsistencies'] == []
    for stage, values in rows.items():
        stat = run['stages'][stage]
        assert stat['count'] == len(values)
        assert stat['statuses'] == dict(collections.Counter(f'{r[0]}:{r[1]}' for r in values))
        assert stat['p95_s'] == p([r[2] for r in values], .95)
        assert stat['p99_s'] == p([r[2] for r in values], .99)
with gzip.open(ROOT / 'process-health.jsonl.gz', 'rt') as f:
    monitor = [json.loads(line) for line in f]


def usage(r, k):
    return int(dict(line.split() for line in r['services'][k]['resources']['cpu.stat'].splitlines())['usage_usec'])


peak = max(sum(usage(b, k) - usage(a, k) for k in a['services']) / (b['at'] - a['at']) / 1e6
           for a, b in zip(monitor, monitor[1:]))
assert math.isclose(peak, read('resource-summary.json')['service_cpu_cores_peak_5s'], rel_tol=1e-12)
assert read('closed.json')['maintenance_enabled'] and read('closed.json')['activity_state'] == 'draft'
if (ROOT / 'SHA256SUMS').exists():
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert sha((ROOT / name).read_bytes()) == expected, name
print(f'PASS: {len(members)} members, two public 1500-student runs, raw rows and resource peak')
