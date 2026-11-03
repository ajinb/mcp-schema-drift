"""mcp-surface against a real degraded/healthy pair from the study and a live fake server."""

import json
import sys
from pathlib import Path

from mcp_schema_drift import check, diff, lockfile, normalize, total_loss
from mcp_schema_drift.cli import main
from mcp_schema_drift.client import fetch_tools

FIX = Path(__file__).parent / "fixtures"
SERVER = [sys.executable, str(Path(__file__).parent / "fake_server.py")]


def _tools(name):
    return json.loads((FIX / name).read_text())["tools"]


def test_study_pair_server_github_0_5_1():
    era, naive = _tools("era_tools.json"), _tools("naive_tools.json")
    assert not total_loss(era)
    assert total_loss(naive)  # R1 catches the deployment-induced loss
    report = check(naive, lockfile(era))
    assert report.exit_code() == 1
    emptied = [f for f in report.findings if f.kind == "input schema emptied"]
    assert len(emptied) == len(era)


def test_parameterless_tool_alone_is_not_total_loss():
    assert not total_loss([{"name": "ping", "inputSchema": {"type": "object"}},
                           {"name": "a", "inputSchema": {"properties": {"x": {"type": "string"}}}}])
    assert not total_loss([])


def test_subtle_drift_needs_the_baseline():
    old = [{"name": "t", "inputSchema": {"properties": {"a": {"type": "string"},
                                                        "b": {"type": "string"}},
                                         "required": ["a"]}}]
    new = [{"name": "t", "inputSchema": {"properties": {"a": {"type": "integer"},
                                                        "c": {"type": "string"}},
                                         "required": ["a", "c"]}}]
    kinds = {(f.kind, f.detail.split(":")[0]) for f in diff(normalize(old), normalize(new))}
    assert ("property removed", "b") in kinds
    assert ("property added", "c") in kinds
    assert ("property type changed", "a") in kinds
    assert check(new, lockfile(old)).exit_code() == 2


def test_description_only_change_is_a_warning():
    old = [{"name": "t", "description": "x", "inputSchema": {"properties": {
        "a": {"type": "string", "description": "one"}}}}]
    new = [{"name": "t", "description": "x", "inputSchema": {"properties": {
        "a": {"type": "string", "description": "two"}}}}]
    findings = diff(normalize(old), normalize(new))
    assert [f.severity for f in findings] == ["warning"]


def test_live_handshake_with_pagination_and_noisy_stdout():
    tools, info = fetch_tools(SERVER, timeout=20)
    assert [t["name"] for t in tools] == ["read_file", "list_dir", "ping"]
    assert info["name"] == "fake" and info["protocolVersion"] == "2025-06-18"


def test_cli_snapshot_then_check(tmp_path, capsys):
    lock = tmp_path / "surface.lock.json"
    assert main(["snapshot", "--out", str(lock), "--", *SERVER]) == 0
    assert main(["check", "--baseline", str(lock), "--", *SERVER]) == 0
    assert main(["check", "--baseline", str(lock), "--json", "--", *SERVER, "--empty"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["total_loss"] is True


def test_cli_offline_and_errors(tmp_path):
    assert main(["check", "--tools-json", str(FIX / "naive_tools.json")]) == 1
    assert main(["check", "--tools-json", str(FIX / "era_tools.json")]) == 0
    assert main(["check"]) == 3
    assert main(["check", "--timeout", "2", "--", sys.executable, "-c", "import time; time.sleep(30)"]) == 3
