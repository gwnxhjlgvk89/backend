"""The recovery diagnostic must refuse the wrong fixture before network writes."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts import recover_load_students as recovery


def source():
    return {
        "completed": True,
        "errors": [],
        "parameters": {
            "url": "https://192.168.100.130:18082",
            "mode": "login",
            "scenario": "uniform",
            "users": 1500,
            "rounds": 1,
        },
        "runs": [{"db": {"enrollments": 1499}}],
    }


@pytest.mark.parametrize("change", ["production", "incomplete", "hot_club"])
def test_wrong_source_refused_before_ssh(tmp_path, monkeypatch, change):
    data = source()
    if change == "production":
        data["parameters"]["url"] = "https://production.invalid"
    if change == "incomplete":
        data["completed"] = False
    if change == "hot_club":
        data["parameters"]["scenario"] = "hot_club"
    path = tmp_path / "source.json"
    path.write_text(json.dumps(data))

    async def forbidden(*args, **kwargs):
        pytest.fail("Network must not be touched for invalid source evidence")

    monkeypatch.setattr(recovery, "fixture", forbidden)
    monkeypatch.setattr(recovery, "ssh", forbidden)
    with pytest.raises(SystemExit, match="completed original TEST"):
        asyncio.run(
            recovery.main(SimpleNamespace(journey_report=str(path), report=str(tmp_path / "out.json")))
        )


def test_changed_fixture_refused_before_account_lookup(tmp_path, monkeypatch):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source()))

    async def changed(*args, **kwargs):
        return {"inconsistencies": [], "enrollments": 0}

    async def forbidden(*args, **kwargs):
        pytest.fail("Must not continue into a reset or different fixture")

    monkeypatch.setattr(recovery, "fixture", changed)
    monkeypatch.setattr(recovery, "ssh", forbidden)
    with pytest.raises(SystemExit, match="Fixture changed"):
        asyncio.run(
            recovery.main(SimpleNamespace(journey_report=str(path), report=str(tmp_path / "out.json")))
        )
