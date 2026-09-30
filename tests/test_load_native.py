from types import SimpleNamespace

import pytest

from scripts.load_native import scope, translate


def args(**kwargs):
    return SimpleNamespace(**({"ssh": "ubuntu@150.158.22.139", "url": "https://wjy-1214.cloud"} | kwargs))


def test_native_rejects_other_hosts_and_domains():
    for a in (args(ssh="someone@elsewhere"), args(url="http://wjy-1214.cloud")):
        with pytest.raises(ValueError):
            translate(a, "podman exec club-capacity-test_api_1 python -m club.load_fixture check")


def test_native_keeps_fixture_isolation_and_rejects_unknown_commands():
    cmd = translate(args(), "podman exec club-capacity-test_api_1 python -m club.load_fixture check")
    assert "/etc/club/load-test.env" in cmd and "-m club.load_fixture check" in cmd
    assert "production.env" not in cmd
    with pytest.raises(ValueError):
        translate(args(), "rm -rf /srv/club")


def test_native_python_requires_test_database_before_code():
    cmd = translate(args(), 'podman exec club-capacity-test_api_1 python -c "print(123)"')
    assert "club_test" in cmd and "club:test" in cmd and "s.club_env" in cmd
    assert cmd.index("assert ") < cmd.index("print(123)")


def test_new_host_requires_matching_endpoint_and_retains_test_guard():
    new = args(ssh="ubuntu@43.142.19.144", url="https://wjy-1214.cloud")
    assert "8GB" in scope(new)["cpu_scope"]
    cmd = translate(new, 'podman exec club-capacity-test_api_1 python -c "print(123)"')
    assert "club_test" in cmd and "club:test" in cmd
    with pytest.raises(ValueError):
        translate(args(ssh=new.ssh, url="https://unapproved.invalid"), "podman exec club-capacity-test_api_1 python -m club.load_fixture prepare")
