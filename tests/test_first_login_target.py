from types import SimpleNamespace

import pytest

from scripts.run_first_login_case import driver_command


def args(**overrides):
    return SimpleNamespace(**({
        'url': 'https://wjy-1214.cloud', 'ssh': 'ubuntu@43.142.19.144',
        'control': '/tmp/test-control', 'ca_cert': None, 'report': 'reports/test.json',
    } | overrides))


def test_native_first_login_does_not_reconfigure_capacity(monkeypatch):
    monkeypatch.setenv('CLUB_NATIVE_CAPACITY', '1')
    command = driver_command(args())
    assert command[1].endswith('load_distributed_journey.py')
    assert '--first-password-change' in command
    assert not {'--cpus', '--mbps', '--ca-cert'} & set(command)
    with pytest.raises(ValueError):
        driver_command(args(ssh='ubuntu@unapproved.invalid'))


def test_container_still_requires_explicit_test_ca(monkeypatch):
    monkeypatch.delenv('CLUB_NATIVE_CAPACITY', raising=False)
    with pytest.raises(ValueError):
        driver_command(args())
    command = driver_command(args(ca_cert='/tmp/test-ca.pem'))
    assert command[1].endswith('run_journey_case.py')
    assert command[command.index('--ca-cert') + 1] == '/tmp/test-ca.pem'
