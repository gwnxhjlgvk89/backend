"""Verify the retained stopped-run snapshot; full request rows remain on the generator."""
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(name):
    return json.loads((ROOT / name).read_text())

r = read('current-results.json')
assert r['status'] == 'stopped_by_user' and len(r['completed_cases']) == len(r['details']) == 12
assert all(c['exit_code'] == 0 and c['data_consistent'] for c in r['completed_cases'])
for c, d in zip(r['completed_cases'], r['details']):
    assert c['case'] == d['case']
    assert c['enrollment_p95'] == d['enrollment']['p95_s']
    if c['case'].startswith('hot-'):
        assert c['enrollments'] == 100
    if c['case'].startswith('last-'):
        assert c['enrollments'] == 1
control = read('proxy-control.json')
assert control['restored_same_version'] and not control.get('restore_error')
assert control['before']['network']['proxy'] == control['restored']['network']['proxy']
assert control['before']['network']['dns'] == control['restored']['network']['dns']
closed = read('closed.json')
assert closed['maintenance_enabled'] and closed['activity_state'] == 'draft' and not closed['inconsistencies']
rows = [json.loads(x) for x in gzip.open(ROOT / 'process-health.jsonl.gz', 'rt')]
def cpu(r, k):
    return int(dict(x.split() for x in r['services'][k]['resources']['cpu.stat'].splitlines())['usage_usec'])
peak = max(sum(cpu(b, k) - cpu(a, k) for k in a['services']) / (b['at'] - a['at']) / 1e6 for a, b in zip(rows, rows[1:]))
assert math.isclose(peak, read('resource-summary.json')['service_cpu_cores_peak_5s'], rel_tol=1e-12)
for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
    expected, name = line.split('  ', 1)
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
print('PASS: stopped snapshot consistency, resources, proxy and maintenance restoration; not capacity acceptance')
