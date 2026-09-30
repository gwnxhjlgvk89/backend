"""Offline checks only: hashes, raw observations, handshake matching and resource math."""
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


def digest(data):
    return hashlib.sha256(data).hexdigest()


def percentile(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * q))], 4) if values else None


with tarfile.open(ROOT / 'raw-evidence.tar.gz') as archive:
    members = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
manifest = read('raw-evidence-manifest.json')
assert set(manifest) == set(members)
for name, info in manifest.items():
    assert digest(members[name]) == info['sha256'], name
    assert len(members[name]) == info['bytes'], name
verified = 0
for row in read('summary.json')['results']:
    key = row['group'] + '/reports/' + row['case'] + '.json'
    report = json.loads(members[key])
    assert report['production_capacity_verified'] is False
    run = report['runs'][0]
    assert row['completed_students'] == run['completed_students']
    assert row['database'] == run['db']
    assert row['gates'] == run['scope_gates']
    records = collections.defaultdict(list)
    confirmed = 0
    for part in report['parts']:
        raw = members[row['group'] + '/reports/' + part['file']]
        assert digest(raw) == part['sha256']
        child = json.loads(raw)['runs'][0]
        confirmed += child['confirmed_enrollments']
        for stage, values in child['raw_stages'].items():
            records[stage].extend(values)
    assert confirmed == run['confirmed_enrollments']
    for stage, values in records.items():
        stat = run['stages'][stage]
        assert stat['count'] == len(values), (key, stage)
        assert stat['statuses'] == dict(collections.Counter(f'{v[0]}:{v[1]}' for v in values))
        assert stat['p95_s'] == percentile([v[2] for v in values], .95)
        assert stat['p99_s'] == percentile([v[2] for v in values], .99)
    verified += 1
with gzip.open(ROOT / 'handshake-rows.jsonl.gz', 'rt') as f:
    packets = [json.loads(line) for line in f]
metadata = read('handshake-metadata.json')
assert len(packets) == metadata['rows']
sets = {(side, kind): {r['connection'] for r in packets if r['side'] == side and r['kind'] == kind}
        for side in ['client', 'server'] for kind in ['syn', 'synack']}
c, s = sets['client', 'syn'], sets['server', 'syn']
h = read('handshake-diagnostic.json')
assert len(c) == h['client_unique_syn']
assert len(c & s) == h['client_syn_seen_on_server']
assert len(c - s) == h['client_syn_not_seen_on_server']
assert len(c & sets['server', 'synack'] & sets['client', 'synack']) == h['server_synack_seen_on_client']
assert all('0 packets dropped by kernel' in lines for lines in metadata['footers'].values())
for side in ['client', 'server']:
    assert dict(collections.Counter(p['kind'] for p in packets if p['side'] == side)) == h['counts'][side]
if (ROOT / 'resource-summary.json').exists():
    with gzip.open(ROOT / 'process-health.jsonl.gz', 'rt') as f:
        monitor = [json.loads(line) for line in f]
    def usage(sample, key):
        return int(dict(line.split() for line in sample['services'][key]['resources']['cpu.stat'].splitlines())['usage_usec'])
    peak = max(sum(usage(b, k) - usage(a, k) for k in a['services']) / (b['at'] - a['at']) / 1e6
               for a, b in zip(monitor, monitor[1:]))
    assert math.isclose(peak, read('resource-summary.json')['service_cpu_cores_peak_5s'], rel_tol=1e-12)
for name, data in members.items():
    if name.endswith('-first-login-fixture.json'):
        fixture = json.loads(data)
        assert fixture['test_only'] and fixture['prepared'] and fixture['restored']
    if '/reports/tcp-' in name and name.endswith('.json'):
        probe = json.loads(data)
        assert probe['diagnostic_only']
        assert len(probe['rows']) == probe['connections'] == 3000
        assert sum(r[1] == 'connected' for r in probe['rows']) == probe['connected']
assert read('summary.json')['public_capacity_pass'] is False
if (ROOT / 'SHA256SUMS').exists():
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert digest((ROOT / name).read_bytes()) == expected, name
print(f'PASS: {len(members)} archive members, {verified} journey reports, {len(packets)} normalized packets')
