"""Recompute cold-login results and verify direct-route/restoration evidence offline."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
raw = gzip.decompress((ROOT / 'login.json.gz').read_bytes())
assert hashlib.sha256(raw).hexdigest() == '4a80ca845239859385a15b4afe7f947390be46eb5f7bac408640aee03de9f683'
report = json.loads(raw)
rows = [r for part in report['parts'] for r in part['rows']]
assert len(rows) == 1500 and {r['index'] for r in rows} == set(range(1500))
assert dict(Counter(r['outcome'] for r in rows)) == report['summary']['outcomes'] == {'OK': 1500}
assert all(r['status'] == 200 for r in rows)
values = sorted(r['total_s'] for r in rows)
assert report['summary']['total_p95_s'] == round(values[int(len(values) * .95)], 6)
assert report['summary']['total_p99_s'] == round(values[int(len(values) * .99)], 6)
assert report['summary']['total_p95_s'] <= 5
assert max(r['start_epoch'] for r in rows) - min(r['start_epoch'] for r in rows) < 1
control = json.loads((ROOT / 'proxy-control.json').read_text())
assert control['test_exit'] == 0 and control['restored_same_version']
assert control['before']['state'] == control['restored']['state']
assert control['before']['network']['proxy'] == control['restored']['network']['proxy']
assert control['before']['network']['dns'] == control['restored']['network']['dns']
direct = control['disabled']['network']
assert 'interface: en1' in direct['route'] and 'utun' not in direct['route']
assert direct['resolved'] == ['43.142.19.144'] and direct['dns'] != '127.0.0.1'
assert not control['disabled']['state']['enabled']
assert all(f'{key} : 1' not in direct['proxy'] for key in ['HTTPEnable','HTTPSEnable','SOCKSEnable'])
closed = json.loads((ROOT / 'closed.json').read_text())
assert closed['maintenance_enabled'] and closed['activity_state'] == 'draft'
assert closed['enrollments'] == 1489 and not closed['inconsistencies']
for path in ROOT.iterdir():
    if path.suffix in ('.json', '.gz'):
        content = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
        assert not re.search(rb'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}', content), path
if (ROOT / 'SHA256SUMS').exists():
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
print('PASS: 1500 successful cold logins, p95<=5s, direct route, proxy restored, maintenance restored')
