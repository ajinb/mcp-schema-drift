"""E4: measure schema drift across published MCP server versions via the real protocol.

For each published npm version of each server, spawn it over stdio, complete the MCP
handshake, and capture the verbatim tools/list response. No source parsing: what we
record is exactly what an agent host would see.
"""
from __future__ import annotations
import json, os, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SANDBOX = os.path.join(ROOT, "sandbox")
os.makedirs(DATA, exist_ok=True); os.makedirs(SANDBOX, exist_ok=True)

# Dummy credentials: tools/list is an unauthenticated operation in MCP, but some
# servers exit at startup if a key is absent. Supplying syntactically-plausible
# placeholders lets them reach the point where they advertise their tool list.
DUMMY_ENV = {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_" + "0"*36,
    "GITHUB_TOKEN": "ghp_" + "0"*36,
    "GITLAB_PERSONAL_ACCESS_TOKEN": "glpat-" + "0"*20,
    "GITLAB_API_URL": "https://gitlab.com/api/v4",
    "SLACK_BOT_TOKEN": "xoxb-0000000000-0000000000-" + "0"*24,
    "SLACK_TEAM_ID": "T00000000",
    "BRAVE_API_KEY": "BSA" + "0"*29,
    "GOOGLE_MAPS_API_KEY": "AIza" + "0"*35,
    "REDIS_URL": "redis://localhost:6379",
    "MEMORY_FILE_PATH": os.path.join(SANDBOX, "memory.json"),
}

SERVERS = {
    "server-filesystem":          {"args": [SANDBOX]},
    "server-everything":          {"args": []},
    "server-memory":              {"args": []},
    "server-sequential-thinking": {"args": []},
    "server-github":              {"args": []},
    "server-gitlab":              {"args": []},
    "server-slack":               {"args": []},
    "server-postgres":            {"args": ["postgresql://localhost/postgres"]},
    "server-puppeteer":           {"args": []},
    "server-brave-search":        {"args": []},
    "server-google-maps":         {"args": []},
    "server-redis":               {"args": ["redis://localhost:6379"]},
}
PROTOCOLS = ["2025-06-18", "2024-11-05"]


def npm_versions(pkg: str):
    url = f"https://registry.npmjs.org/@modelcontextprotocol/{pkg}"
    raw = subprocess.run(["curl", "-sL", "--max-time", "60", url],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(raw)
    t = d.get("time", {})
    out = [(v, t[v][:10]) for v in d.get("versions", {}) if v in t]
    out.sort(key=lambda x: x[1])
    return out


def probe(pkg, version, args, timeout=150):
    env = dict(os.environ); env.update(DUMMY_ENV); env["NO_COLOR"] = "1"
    last_err = None
    for proto in PROTOCOLS:
        cmd = ["npx", "-y", f"@modelcontextprotocol/{pkg}@{version}"] + args
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, bufsize=1,
                             env=env, cwd=SANDBOX)
        res = {}
        try:
            def send(o):
                p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush()
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                  "protocolVersion": proto, "capabilities": {},
                  "clientInfo": {"name": "drift-probe", "version": "1.0"}}})
            deadline = time.time() + timeout
            init = None
            while time.time() < deadline:
                line = p.stdout.readline()
                if not line:
                    break
                try: m = json.loads(line)
                except Exception: continue
                if m.get("id") == 1:
                    init = m; break
            if init is None or "result" not in init:
                last_err = f"no/failed initialize (proto {proto})"
                continue
            res["protocolVersion"] = init["result"].get("protocolVersion")
            res["serverInfo"] = init["result"].get("serverInfo")
            send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            while time.time() < deadline:
                line = p.stdout.readline()
                if not line:
                    break
                try: m = json.loads(line)
                except Exception: continue
                if m.get("id") == 2:
                    if "result" in m:
                        res["tools"] = m["result"].get("tools", [])
                        res["ok"] = True
                        return res
                    last_err = f"tools/list error: {json.dumps(m.get('error'))[:200]}"
                    break
            last_err = last_err or "no tools/list response"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        finally:
            try: p.kill()
            except Exception: pass
    return {"ok": False, "error": last_err}


def job(pkg, version, date, args):
    path = os.path.join(DATA, pkg, f"{version}.json")
    if os.path.exists(path):
        return pkg, version, "cached"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = probe(pkg, version, args)
    r["package"], r["version"], r["published"] = pkg, version, date
    with open(path, "w") as f:
        json.dump(r, f, indent=1)
    return pkg, version, ("ok %d tools" % len(r["tools"])) if r.get("ok") else "FAIL: %s" % str(r.get("error"))[:60]


def main():
    only = sys.argv[1:] or list(SERVERS)
    tasks = []
    for pkg in only:
        try:
            vs = npm_versions(pkg)
        except Exception as e:
            print(f"!! {pkg}: {e}"); continue
        print(f"{pkg}: {len(vs)} versions")
        for v, d in vs:
            tasks.append((pkg, v, d, SERVERS[pkg]["args"]))
    print(f"\n{len(tasks)} version-probes queued\n", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(job, *t) for t in tasks]
        for f in as_completed(futs):
            pkg, v, status = f.result(); done += 1
            print(f"[{done}/{len(tasks)}] {pkg}@{v}: {status}", flush=True)


if __name__ == "__main__":
    main()
