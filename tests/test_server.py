from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from glasshouse.server import app

client = fastapi_testclient.TestClient(app)


def test_healthz():
    assert client.get("/healthz").json()["status"] == "ok"


def test_tools_endpoint_exposes_effects():
    tools = {t["name"]: t for t in client.get("/tools").json()}
    assert tools["delete_file"]["effect"] == "destructive"
    assert tools["delete_file"]["reversible"] is True
    assert tools["list_files"]["effect"] == "read"


def test_run_streams_sse_events():
    body = client.post("/runs", json={"prompt": "tidy up", "auto_approve": True}).text
    assert "event: run_started" in body
    assert "event: approval_requested" in body
    assert "event: run_finished" in body


def test_dry_run_emits_a_plan_and_no_tool_start_for_mutations():
    body = client.post("/runs", json={"prompt": "tidy up", "dry_run": True}).text
    assert "event: dry_run_planned" in body
    assert "would delete" in body
    assert "event: approval_requested" not in body
