"""Severity experiment: does an emptied inputSchema degrade real tool use?

Controlled A/B against a REAL MCP server. Identical model, tasks, and server; the only
variable is whether the tool is advertised with its true schema or with the emptied schema
that present-day dependency resolution actually serves.

  full    -- inputSchema exactly as the healthy server advertises it
  emptied -- {"$schema": "http://json-schema.org/draft-07/schema#"}, byte-identical to what
             `@modelcontextprotocol/server-filesystem@2025.8.21` serves today

Every tool call the model emits is executed against the live server, so success is measured
by what actually happened, not by judging the model's text.

Requires ANTHROPIC_API_KEY (or `ant auth login`). Run:
    pip install anthropic
    python3 severity.py --models claude-haiku-4-5,claude-sonnet-5 --seeds 3
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, uuid

# What the broken server actually serves, verbatim:
RAW_EMPTY = {"$schema": "http://json-schema.org/draft-07/schema#"}
# The Anthropic Messages API rejects RAW_EMPTY (400: input_schema.type Field required),
# so a host that forwards MCP schemas untouched fails loudly at request time. Hosts that
# normalise the schema before forwarding do not. These are the two normalisations a host
# can plausibly produce, and they are what the model actually gets to reason from.
CONDITIONS = {
    "full":         None,                                             # true schema
    "emptied_norm": {"type": "object", "properties": {}},              # closed object
    "emptied_open": {"type": "object", "properties": {},
                     "additionalProperties": True},                    # open object
}
SERVER_PKG = "@modelcontextprotocol/server-filesystem@2026.8.31"   # healthy release


# ---------------------------------------------------------------- MCP session
class MCPSession:
    """Minimal stdio MCP client: initialize, tools/list, tools/call."""
    def __init__(self, root):
        self.p = subprocess.Popen(
            ["npx", "-y", SERVER_PKG, root],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        self._id = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "severity", "version": "1"}})
        self._notify("notifications/initialized")

    def _rpc(self, method, params, timeout=120):
        self._id += 1; mid = self._id
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                       "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        end = time.time() + timeout
        while time.time() < end:
            line = self.p.stdout.readline()
            if not line: break
            try: m = json.loads(line)
            except Exception: continue
            if m.get("id") == mid: return m
        return {"error": {"message": "timeout"}}

    def _notify(self, method, params=None):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                       "params": params or {}}) + "\n")
        self.p.stdin.flush()

    def tools(self):
        return self._rpc("tools/list", {}).get("result", {}).get("tools", [])

    def call(self, name, args):
        r = self._rpc("tools/call", {"name": name, "arguments": args})
        if "error" in r:
            return False, json.dumps(r["error"])[:300]
        res = r.get("result", {})
        if res.get("isError"):
            return False, json.dumps(res.get("content"))[:300]
        return True, json.dumps(res.get("content"))[:2000]

    def close(self):
        try: self.p.kill()
        except Exception: pass


# ---------------------------------------------------------------- tasks
def make_tasks(root):
    """Each task: a natural instruction plus a checker over the transcript/filesystem."""
    return [
        {"id": "read",
         "prompt": "What is the contents of the file notes.txt?",
         "check": lambda tr, root: any(ok and "alpha-7" in out for _, _, ok, out in tr)},
        {"id": "read_nested",
         "prompt": "Read docs/spec.md and tell me the version string it contains.",
         "check": lambda tr, root: any(ok and "v3.14" in out for _, _, ok, out in tr)},
        {"id": "list",
         "prompt": "List everything in the docs directory.",
         "check": lambda tr, root: any(ok and "spec.md" in out for _, _, ok, out in tr)},
        {"id": "search",
         "prompt": "Find every file whose name matches the pattern *.md.",
         "check": lambda tr, root: any(ok and "spec.md" in out for _, _, ok, out in tr)},
        {"id": "info",
         "prompt": "How large is notes.txt, in bytes?",
         "check": lambda tr, root: any(ok and ("size" in out.lower()) for _, _, ok, out in tr)},
        {"id": "write",
         "prompt": "Create a file called out.txt containing exactly the word DONE.",
         "check": lambda tr, root: os.path.exists(os.path.join(root, "out.txt"))
                  and "DONE" in open(os.path.join(root, "out.txt")).read()},
        {"id": "mkdir",
         "prompt": "Create a directory called build.",
         "check": lambda tr, root: os.path.isdir(os.path.join(root, "build"))},
        {"id": "move",
         "prompt": "Rename notes.txt to renamed.txt.",
         "check": lambda tr, root: os.path.exists(os.path.join(root, "renamed.txt"))},
        {"id": "multi",
         "prompt": "Read notes.txt and docs/spec.md, then write a file summary.txt "
                   "containing the word BOTH.",
         "check": lambda tr, root: os.path.exists(os.path.join(root, "summary.txt"))
                  and "BOTH" in open(os.path.join(root, "summary.txt")).read()},
        {"id": "tree",
         "prompt": "Show me the full directory tree from the root.",
         "check": lambda tr, root: any(ok and "docs" in out for _, _, ok, out in tr)},
    ]


def fresh_sandbox(base):
    d = os.path.join(base, "sb-" + uuid.uuid4().hex[:8])
    os.makedirs(os.path.join(d, "docs"))
    open(os.path.join(d, "notes.txt"), "w").write("project code alpha-7\n")
    open(os.path.join(d, "docs", "spec.md"), "w").write("# Spec\nversion v3.14\n")
    return d


# ---------------------------------------------------------------- one trial
def run_trial(client, model, condition, task, base, max_turns=6):
    root = fresh_sandbox(base)
    sess = MCPSession(root)
    try:
        real = {t["name"]: t for t in sess.tools()}
        tools = []
        for t in real.values():
            override = CONDITIONS[condition]
            schema = t.get("inputSchema") if override is None else dict(override)
            tools.append({"name": t["name"], "description": t.get("description", ""),
                          "input_schema": schema})
        messages = [{"role": "user", "content":
                     f"You have filesystem tools rooted at {root}. {task['prompt']}"}]
        transcript, calls, bad = [], 0, 0
        for _ in range(max_turns):
            r = client.messages.create(model=model, max_tokens=2048,
                                       tools=tools, messages=messages)
            blocks = r.content
            uses = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
            messages.append({"role": "assistant", "content": blocks})
            if not uses:
                break
            results = []
            for u in uses:
                calls += 1
                ok, out = sess.call(u.name, u.input or {})
                if not ok: bad += 1
                transcript.append((u.name, u.input, ok, out))
                results.append({"type": "tool_result", "tool_use_id": u.id,
                                "content": out, "is_error": not ok})
            messages.append({"role": "user", "content": results})
            if r.stop_reason != "tool_use":
                break
        ok = bool(task["check"](transcript, root))
        return {"model": model, "condition": condition, "task": task["id"],
                "success": ok, "calls": calls, "failed_calls": bad,
                "first_call_args": transcript[0][1] if transcript else None}
    finally:
        sess.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="claude-haiku-4-5")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default="severity_results.json")
    a = ap.parse_args()
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    client = anthropic.Anthropic()
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sevwork")
    os.makedirs(base, exist_ok=True)
    rows = json.load(open(a.out)) if os.path.exists(a.out) else []
    seen = {(r["model"], r["condition"], r["task"], r.get("seed")) for r in rows}
    for model in a.models.split(","):
        for seed in range(a.seeds):
            for task in make_tasks(base):
                for cond in CONDITIONS:
                    if (model, cond, task["id"], seed) in seen: continue
                    try:
                        r = run_trial(client, model, cond, task, base)
                    except Exception as e:
                        r = {"model": model, "condition": cond, "task": task["id"],
                             "success": False, "error": f"{type(e).__name__}: {e}"}
                    r["seed"] = seed; rows.append(r)
                    json.dump(rows, open(a.out, "w"), indent=1)
                    print(f"{model} {cond:<8} {task['id']:<12} seed{seed} "
                          f"-> {'OK ' if r.get('success') else 'FAIL'} "
                          f"calls={r.get('calls')} bad={r.get('failed_calls')}", flush=True)
    # summary
    print("\n" + "="*76)
    for model in sorted({r["model"] for r in rows}):
        for cond in CONDITIONS:
            sub = [r for r in rows if r["model"] == model and r["condition"] == cond]
            if not sub: continue
            s = sum(1 for r in sub if r.get("success"))
            bc = sum(r.get("failed_calls") or 0 for r in sub)
            tc = sum(r.get("calls") or 0 for r in sub)
            print(f"{model:<24}{cond:<10}success {s}/{len(sub)} ({100*s/len(sub):5.1f}%)"
                  f"   rejected calls {bc}/{tc}")


if __name__ == "__main__":
    main()
