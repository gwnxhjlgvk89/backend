"""Offline evidence checks; no network, credentials, extraction or DB writes."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from scripts.load_connection_phases import summarize  # noqa: E402


def read(name):
    return json.loads((ROOT / name).read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


manifest = read('raw-evidence-manifest.json')
with tarfile.open(ROOT / 'raw-evidence.tar.gz') as archive:
    members = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
assert set(manifest) == set(members)
for name, expected in manifest.items():
    assert digest(members[name]) == expected['sha256'], name
    assert len(members[name]) == expected['bytes'], name
parts = 0
for name in ('cold-1', 'cold-2', 'cold-3', 'ready-600', 'hot', 'last-seat'):
    report = read(name + '.json')
    for part in report['parts']:
        assert digest(members['reports/' + part['file']]) == part['sha256']
        parts += 1
    assert report['runs'][0]['data_consistency_pass']
assert parts == 18
for phase, expected in read('phases-summary.json').items():
    rows = [r for shard in range(3)
            for r in json.loads(members[f'reports/phases/{phase}-{shard}.json'])['rows']]
    assert summarize(rows) == expected, phase
rows = [r for shard in range(3)
        for r in json.loads(members[f'capacity-loopback/loopback_health-{shard}.json'])['rows']]
assert summarize(rows) == read('loopback-summary.json')['loopback_health']
with gzip.open(ROOT / 'handshake-rows.jsonl.gz', 'rt') as stream:
    packets = [json.loads(line) for line in stream]
metadata = read('handshake-metadata.json')
assert len(packets) == metadata['row_count']
expected_handshakes = read('handshake-comparison.json')


def first(rows, kind):
    result = {}
    for row in rows:
        if row['kind'] == kind:
            key = row['connection']
            result[key] = min(result.get(key, row['at']), row['at'])
    return result


def stats(values):
    values = sorted(values)
    return {'count': len(values),
            'p50_s': values[len(values) // 2] if values else None,
            'p95_s': values[min(len(values) - 1, int(len(values) * .95))] if values else None,
            'over_200ms': sum(v > .2 for v in values)}


for phase, (start, end) in metadata['phase_windows'].items():
    window = [p for p in packets if start - 1 <= p['at'] <= end + 1]
    client = [p for p in window if p['side'] == 'client']
    server = [p for p in window if p['side'] == 'server']
    cf, sf = first(client, 'syn'), first(server, 'syn')
    ca, sa = first(client, 'synack'), first(server, 'synack')
    cs, ss, cas, sas = set(cf), set(sf), set(ca), set(sa)
    result = {
        'first_syn_client_to_server': stats([sf[k] - cf[k] for k in cs & ss]),
        'first_synack_server_to_client': stats([ca[k] - sa[k] for k in cs & sas & cas]),
        'client_unique_syn': len(cs), 'server_received_client_syn': len(cs & ss),
        'client_syn_missing_at_server': len(cs - ss),
        'server_replied_to_client_syn': len(cs & sas),
        'client_received_server_synack': len(cs & cas),
        'server_synack_missing_at_client': len((cs & sas) - cas),
        'client_packets': dict(collections.Counter(p['kind'] for p in client)),
        'server_packets': dict(collections.Counter(p['kind'] for p in server)),
    }
    assert result == expected_handshakes[phase], phase
monitor = [json.loads(line) for line in (ROOT / 'process-health.jsonl').read_text().splitlines()]


def usage(service):
    return int(dict(line.split() for line in service['resources']['cpu.stat'].splitlines())['usage_usec'])


service_peak = max(
    sum(usage(b['services'][k]) - usage(a['services'][k]) for k in a['services'])
    / (b['at'] - a['at']) / 1e6
    for a, b in zip(monitor, monitor[1:])
)
assert service_peak == read('resource-summary.json')['services_cpu_cores_sample_max']
assert read('restored.json')['formal_database_full_fingerprints_unchanged']
assert read('summary.json')['capacity_pass'] is False
checksums = ROOT / 'SHA256SUMS'
if checksums.exists():
    for line in checksums.read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert digest((ROOT / name).read_bytes()) == expected, name
print(f'PASS: {len(members)} archive members, {parts} journey shards, 5 phase summaries, '
      f'{len(packets)} normalized packets, CPU peak, restoration and file checksums')
