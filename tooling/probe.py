"""Speak real MCP JSON-RPC to a published server version and capture tools/list."""
import json, subprocess, sys, time, os

def probe(cmd, cwd=None, timeout=180, proto="2025-06-18"):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, bufsize=1, cwd=cwd)
    def send(o):
        p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush()
    out = {}
    try:
        send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
              "protocolVersion":proto,
              "capabilities":{},
              "clientInfo":{"name":"drift-probe","version":"1.0"}}})
        deadline = time.time() + timeout
        init = None
        while time.time() < deadline:
            line = p.stdout.readline()
            if not line: break
            try: m = json.loads(line)
            except Exception: continue
            if m.get("id") == 1:
                init = m; break
        if init is None:
            return {"error":"no initialize response", "stderr": p.stderr.read()[-500:]}
        out["initialize"] = init.get("result", init.get("error"))
        send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
        send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
        while time.time() < deadline:
            line = p.stdout.readline()
            if not line: break
            try: m = json.loads(line)
            except Exception: continue
            if m.get("id") == 2:
                out["tools"] = m.get("result", {}).get("tools", m.get("error"))
                break
    finally:
        try: p.kill()
        except Exception: pass
    return out

if __name__ == "__main__":
    ver = sys.argv[1]
    sandbox = os.path.abspath("sandbox")
    r = probe(["npx","-y",f"@modelcontextprotocol/server-filesystem@{ver}", sandbox])
    if "tools" in r and isinstance(r["tools"], list):
        print(f"OK {ver}: {len(r['tools'])} tools")
        for t in r["tools"]:
            props = list((t.get("inputSchema") or {}).get("properties", {}).keys())
            print(f"   {t['name']}: {props}")
    else:
        print(f"FAIL {ver}: {json.dumps(r)[:400]}")
