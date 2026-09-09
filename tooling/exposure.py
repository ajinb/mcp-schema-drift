"""Table XII: exposure across the official MCP server family.

For each official server, fetch per-version download counts for the trailing week from the npm
registry and sum the counts landing on releases the controlled comparison marks as degraded.
Ground truth for "degraded" is read from resolution_full.json, so this script cannot disagree
with Table I: a release counts as affected exactly when its present-day tool surface differs
from its publish-time surface.

    python3 exposure.py [--data resolution_full.json] [--out exposure_family.json]

Registry downloads overcount human installs (CI, mirrors, automation); the paper reports them
as an upper bound on installs and draws no conclusion from the absolute level.
"""
from __future__ import annotations
import argparse, json, os, subprocess, collections

SERVERS = ["server-filesystem", "server-everything", "server-memory",
           "server-sequential-thinking", "server-github", "server-gitlab", "server-slack",
           "server-postgres", "server-puppeteer", "server-brave-search",
           "server-google-maps", "server-redis"]


def get(url):
    raw = subprocess.run(["curl", "-sL", "--max-time", "60", url],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def degraded_versions(path):
    """Two classes of degraded release, per the controlled comparison.

    loss: every advertised tool's schema is emptied under present-day resolution.
    any : the present-day surface differs from the publish-time surface at all, which
          additionally covers the required-set change of the sequential-thinking server.
    """
    loss = collections.defaultdict(set); any_ = collections.defaultdict(set)
    if not os.path.exists(path):
        return loss, any_
    for r in json.load(open(path)).values():
        n, e = r.get("naive", {}), r.get("era", {})
        if not (isinstance(n.get("n"), int) and isinstance(e.get("n"), int)) or r["identical"]:
            continue
        any_[r["package"]].add(r["version"])
        if n["empty_schemas"] == n["n"]:
            loss[r["package"]].add(r["version"])
    return loss, any_


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="resolution_full.json")
    ap.add_argument("--out", default="exposure_family.json")
    a = ap.parse_args()
    loss, any_ = degraded_versions(a.data)
    rows, tot, tl, ta = {}, 0, 0, 0
    print(f"{'server':<28}{'weekly dl':>12}{'total-loss':>12}{'share':>8}{'any-change':>12}{'share':>8}")
    for pkg in SERVERS:
        d = get(f"https://api.npmjs.org/versions/@modelcontextprotocol%2F{pkg}/last-week").get("downloads", {})
        t = sum(d.values())
        xl = sum(v for k, v in d.items() if k in loss.get(pkg, set()))
        xa = sum(v for k, v in d.items() if k in any_.get(pkg, set()))
        tot += t; tl += xl; ta += xa
        rows[pkg] = {"total": t, "loss": xl, "any": xa,
                     "loss_versions": sorted(loss.get(pkg, set())),
                     "any_versions": sorted(any_.get(pkg, set()))}
        sl = f"{100*xl/t:.2f}%" if t else "--"; sa = f"{100*xa/t:.2f}%" if t else "--"
        print(f"{pkg:<28}{t:>12,}{xl:>12,}{sl:>8}{xa:>12,}{sa:>8}")
    print(f"{'FAMILY TOTAL':<28}{tot:>12,}{tl:>12,}{(100*tl/tot if tot else 0):>7.2f}%{ta:>12,}{(100*ta/tot if tot else 0):>7.2f}%")
    json.dump(rows, open(a.out, "w"), indent=1)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
