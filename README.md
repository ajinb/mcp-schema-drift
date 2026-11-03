# mcp-schema-drift

Protocol-level probing of published Model Context Protocol server releases under controlled
dependency resolution.

Companion artifact for *Pinning the Version Is Not Pinning the Tools: Deployment-Induced Schema
Loss in MCP Servers*.

## The finding, in two lines

An MCP agent learns what arguments a tool takes from the JSON Schema the server advertises in
`tools/list`. That schema is not fixed by the server version you pin. It is generated at
startup by a converter library that the package manager chooses for you:

```
zod 3.25.76 + zod-to-json-schema 3.25.2 -> {"type":"object","properties":{"path":{...}},"required":["path"],...}
zod 4.5.4   + zod-to-json-schema 3.25.2 -> {"$schema":"http://json-schema.org/draft-07/schema#"}
```

The converter does not fail. It returns an empty object, the server starts, the handshake
succeeds, and the agent is told the tools exist and nothing about what any of them takes.

Reproduce it yourself:

```bash
cd tooling/minrepro && npm i zod@4.5.4 zod-to-json-schema@3.25.2 && node repro.mjs
```

## What is measured

Every release of the twelve official MCP servers is installed twice, under present-day
dependency resolution and under the tree that existed on its publish day, and probed over the
live protocol. Of 116 release-pairs where both installs produced a working server, **18 differ**;
in 17 of them every tool's input schema is emptied.

| study | script | output |
|---|---|---|
| Controlled comparison, official family | `tooling/resolution_study2.py` | `data/resolution_full.json` |
| Controlled comparison, third-party sample | `tooling/resolution_thirdparty.py` | `data/resolution_thirdparty.json` |
| Schema-generation construction survey | `tooling/construction_survey.py` | `data/construction_survey.json` |
| Longitudinal drift between releases | `tooling/drift_era.py` | `data/drift_era.json`, `data/drift_naive.json` |
| What survives in the description | `tooling/infoloss.py` | `data/infoloss_results.json` |
| Severity A/B, filesystem server | `tooling/severity.py` | `data/severity_final.json` |
| Severity A/B, memory server | `tooling/severity_memory.py` | `data/severity_memory_final.json` |
| Startup validator evaluation | `tooling/validator_eval.py` | `data/validator_eval.json` |
| Exposure from registry downloads | `tooling/exposure.py` | `data/exposure_family.json` |
| Third-party server discovery | `tooling/launch_probe.py` | `data/candidates.json`, `data/launchable.json` |
| Reference verification (paper-side) | `tooling/refcheck.py` | — |

`tooling/probe.py` and `tooling/harness.py` are the shared MCP client and fault-injection
scaffolding the studies build on.

## Running it

Requires Python 3.11+, Node 20+, and network access to the npm registry. Only the two severity
scripts call a model; everything else is free and deterministic given the registry state.

```bash
python3 tooling/resolution_study2.py                  # ~2h, 129 release-pairs, 258 installs
python3 tooling/construction_survey.py                # ~10min
python3 tooling/drift_era.py era                      # instant, reads resolution_full.json
python3 tooling/validator_eval.py                     # instant
python3 tooling/exposure.py --data data/resolution_full.json

pip install anthropic && export ANTHROPIC_API_KEY=...
python3 tooling/severity.py --models claude-haiku-4-5,claude-sonnet-5 --seeds 3
python3 tooling/severity_memory.py --models claude-haiku-4-5,claude-sonnet-5 --seeds 3
```

**Run every install against an isolated npm cache.** Parallel installs sharing a cache produce
spurious `EACCES` failures that look like unreconstructible releases. Three releases in an early
run were nearly reported as such; they reconstruct cleanly against a fresh cache.

## Guard your own deployment: `mcp-surface`

The study's mitigation, packaged. `mcp-surface` speaks MCP over stdio (handshake, paginated
`tools/list`), then applies the two checks the paper evaluated:

- **Total-loss check (R1)** — reject a surface in which **every** tool has an empty input schema.
  It catches every total-loss case in the study with no false positives, at about two
  microseconds per surface, and needs no baseline. ("Any tool empty" is deliberately not offered:
  57 of 116 healthy surfaces contain a legitimately parameterless tool.)
- **Lockfile diff (R4)** — record the surface once, then fail on breaking drift: a tool or
  property removed, a schema emptied, a type changed, an argument newly required. Description-only
  changes are warnings.

```bash
pip install "git+https://github.com/ajinb/mcp-schema-drift@v1.1.0"   # stdlib only, no dependencies

# Record what your pinned server advertises today
mcp-surface snapshot --out mcp-surface.lock.json -- npx -y @modelcontextprotocol/server-github@0.5.1

# In CI or at agent startup: exit 1 on total loss, 2 on breaking drift, 0 when the surface holds
mcp-surface check --baseline mcp-surface.lock.json -- npx -y @modelcontextprotocol/server-github@0.5.1

# Offline, against a captured tools/list result
mcp-surface check --tools-json tools_list.json --json
```

As a GitHub Action:

```yaml
- uses: ajinb/mcp-schema-drift@v1.1.0
  with:
    command: npx -y @modelcontextprotocol/server-github@0.5.1
    baseline: mcp-surface.lock.json
```

Commit the lockfile next to the server pin. A dependency update that silently empties schemas
now fails the build instead of reaching an agent.

## Data notes

`data/` holds the raw record behind every number in the paper. `data/first-pass/` is the earlier
single-pass survey that first revealed the empty schemas and is the corpus the description
analysis uses; it is superseded by the controlled records for every other purpose.

Sandbox filesystem paths in the severity records are replaced with `<SANDBOX>`. Nothing else in
the records is altered. Credential-shaped strings in the tooling are all-zero placeholders: the
`tools/list` operation is unauthenticated, and the placeholders exist only so servers that check
for a variable's presence will start.

Measurements were taken 2026-09-08 and 2026-09-09 on macOS with Node 22.15.1. "Present-day
resolution" is a property of when you run this, not a constant. Running it later will give
different numbers, which is the point.

## Licence

Code Apache-2.0. Data CC BY 4.0.
