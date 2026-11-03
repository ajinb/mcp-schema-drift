"""Tool-surface normalization, the total-loss check, and baseline diffing.

A *surface* is what an MCP server advertises in ``tools/list``: each tool's
name and input schema. The study behind this repository found that the same
pinned server release can advertise different surfaces depending on how its
dependencies resolved — most often every schema emptied to ``{"$schema": ...}``.

Two checks, as evaluated in the paper (``tooling/validator_eval.py``):

* **R1, total loss** — every advertised tool has an empty input schema. Catches
  every total-loss case in the study with no false positives, in microseconds,
  and needs no baseline.
* **R4, baseline diff** — compare against a recorded lockfile. Needed for the
  subtler cases (a required argument appearing, a property disappearing).

R2 ("any tool empty") is deliberately not offered: legitimately parameterless
tools trip it on about half of healthy surfaces.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

LOCKFILE_VERSION = 1


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def is_empty_schema(tool: dict[str, Any]) -> bool:
    return not ((tool.get("inputSchema") or {}).get("properties"))


def total_loss(tools: list[dict[str, Any]]) -> bool:
    """R1: a non-empty surface in which every tool's input schema is empty."""
    return bool(tools) and all(is_empty_schema(t) for t in tools)


def _prop_type(schema: dict[str, Any]) -> str:
    t = schema.get("type")
    if isinstance(t, list):
        return "|".join(sorted(map(str, t)))
    if t:
        return str(t)
    for key in ("anyOf", "oneOf", "allOf", "$ref", "enum", "const"):
        if key in schema:
            return key
    return "any"


def normalize(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce a tools/list result to a stable, diffable lockfile body."""
    out: dict[str, Any] = {}
    for tool in sorted(tools, key=lambda t: t.get("name", "")):
        schema = tool.get("inputSchema") or {}
        props = schema.get("properties") or {}
        out[tool["name"]] = {
            "properties": {name: _prop_type(p or {}) for name, p in sorted(props.items())},
            "required": sorted(schema.get("required") or []),
            "schema_sha256": hashlib.sha256(_canonical(schema).encode()).hexdigest(),
        }
    return out


def lockfile(tools: list[dict[str, Any]], *, server: dict[str, Any] | None = None) -> dict:
    return {
        "lockfile_version": LOCKFILE_VERSION,
        "server": server or {},
        "tools": normalize(tools),
    }


@dataclass(frozen=True)
class Finding:
    severity: str  # "breaking" | "warning" | "info"
    tool: str
    kind: str
    detail: str = ""

    def __str__(self) -> str:
        return f"[{self.severity}] {self.tool}: {self.kind}{' — ' + self.detail if self.detail else ''}"


@dataclass
class Report:
    total_loss: bool
    findings: list[Finding] = field(default_factory=list)

    @property
    def breaking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "breaking"]

    def exit_code(self) -> int:
        if self.total_loss:
            return 1
        return 2 if self.breaking else 0


def diff(baseline: dict[str, Any], current: dict[str, Any]) -> list[Finding]:
    """Compare two normalized surfaces (``lockfile()["tools"]``). Breaking = an agent's
    existing calls may now fail or silently lose meaning."""
    findings: list[Finding] = []
    for name in sorted(baseline.keys() - current.keys()):
        findings.append(Finding("breaking", name, "tool removed"))
    for name in sorted(current.keys() - baseline.keys()):
        findings.append(Finding("info", name, "tool added"))
    for name in sorted(baseline.keys() & current.keys()):
        old, new = baseline[name], current[name]
        if old["schema_sha256"] == new["schema_sha256"]:
            continue
        if old["properties"] and not new["properties"]:
            findings.append(Finding("breaking", name, "input schema emptied",
                                    f"had {len(old['properties'])} properties"))
            continue
        for prop in sorted(old["properties"].keys() - new["properties"].keys()):
            findings.append(Finding("breaking", name, "property removed", prop))
        for prop in sorted(new["properties"].keys() - old["properties"].keys()):
            sev = "breaking" if prop in new["required"] else "info"
            findings.append(Finding(sev, name, "property added", prop))
        for prop in sorted(old["properties"].keys() & new["properties"].keys()):
            if old["properties"][prop] != new["properties"][prop]:
                findings.append(Finding("breaking", name, "property type changed",
                                        f"{prop}: {old['properties'][prop]} -> "
                                        f"{new['properties'][prop]}"))
        newly_required = set(new["required"]) - set(old["required"]) - (
            new["properties"].keys() - old["properties"].keys()
        )
        for prop in sorted(newly_required):
            findings.append(Finding("breaking", name, "argument became required", prop))
        for prop in sorted(set(old["required"]) - set(new["required"])):
            if prop in new["properties"]:
                findings.append(Finding("warning", name, "argument no longer required", prop))
        if not any(f.tool == name for f in findings):
            findings.append(Finding("warning", name, "schema changed",
                                    "descriptions, constraints or nested structure"))
    return findings


def check(tools: list[dict[str, Any]], baseline: dict[str, Any] | None = None) -> Report:
    report = Report(total_loss=total_loss(tools))
    if report.total_loss:
        report.findings.append(Finding("breaking", "*", "total schema loss",
                                       f"all {len(tools)} tools advertise an empty input schema"))
    if baseline is not None:
        report.findings.extend(diff(baseline["tools"], normalize(tools)))
    return report
