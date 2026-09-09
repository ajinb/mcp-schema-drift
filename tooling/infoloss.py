"""How much of the tool contract survives in the description when the schema is emptied?

When dependency resolution empties `inputSchema`, one channel remains: the tool's
natural-language `description`. This asks, deterministically and with no model calls,
how much of what the caller must supply is still recoverable from that channel --
i.e. how much the model is forced to guess.
"""
import json, re, glob

def variants(p):
    s = {p, p.lower()}
    s.add(re.sub(r'(?<!^)(?=[A-Z])', '_', p).lower())        # camelCase -> snake_case
    s.add(p.replace('_', ' ').lower())
    s.add(p.replace('_', '').lower())
    return {x for x in s if x}

def mentioned(param, desc):
    d = desc.lower()
    return any(re.search(r'\b' + re.escape(v) + r'\b', d) for v in variants(param))

# healthy record = latest release of each server, probed under normal resolution
rows = []
for pkg in sorted({p.split('/')[1] for p in glob.glob("data/*/*.json")}):
    best = None
    for f in glob.glob(f"data/{pkg}/*.json"):
        d = json.load(open(f))
        if not d.get("ok"): continue
        ts = d["tools"]
        if ts and all(not ((t.get("inputSchema") or {}).get("properties")) for t in ts):
            continue                                   # degenerate, skip
        if best is None or d["published"] > best["published"]: best = d
    if not best: continue
    for t in best["tools"]:
        s = t.get("inputSchema") or {}
        props = list((s.get("properties") or {}).keys())
        req = list(s.get("required") or [])
        if not props: continue
        desc = (t.get("description") or "")
        rows.append({
            "pkg": pkg, "tool": t["name"], "desc_len": len(desc),
            "props": props, "required": req,
            "req_named": [p for p in req if mentioned(p, desc)],
            "req_unnamed": [p for p in req if not mentioned(p, desc)],
            "all_named": [p for p in props if mentioned(p, desc)],
        })

tot_req = sum(len(r["required"]) for r in rows)
named   = sum(len(r["req_named"]) for r in rows)
tot_all = sum(len(r["props"]) for r in rows)
named_all = sum(len(r["all_named"]) for r in rows)
tools_all_named = sum(1 for r in rows if r["required"] and not r["req_unnamed"])
tools_with_req  = sum(1 for r in rows if r["required"])
no_desc = sum(1 for r in rows if r["desc_len"] == 0)

print("="*94)
print("INFORMATION SURVIVING IN THE DESCRIPTION WHEN THE SCHEMA IS EMPTIED")
print("="*94)
print(f"tools analysed (latest healthy release per server) : {len(rows)}")
print(f"tools with at least one required parameter         : {tools_with_req}")
print(f"tools carrying no description at all               : {no_desc}")
print()
print(f"REQUIRED parameters                                : {tot_req}")
print(f"  named somewhere in the description               : {named}  ({100*named/tot_req:.1f}%)")
print(f"  NOT recoverable from the description             : {tot_req-named}  ({100*(tot_req-named)/tot_req:.1f}%)")
print()
print(f"ALL parameters (required + optional)               : {tot_all}")
print(f"  named in the description                         : {named_all}  ({100*named_all/tot_all:.1f}%)")
print(f"  NOT recoverable                                  : {tot_all-named_all}  ({100*(tot_all-named_all)/tot_all:.1f}%)")
print()
print(f"tools where EVERY required parameter is still named: {tools_all_named}/{tools_with_req}"
      f"  ({100*tools_all_named/tools_with_req:.1f}%)")
print()
print("Tools whose required parameters vanish entirely with the schema:")
n=0
for r in sorted(rows, key=lambda r: -len(r["req_unnamed"])):
    if r["req_unnamed"]:
        n+=1
        if n<=18:
            print(f"  {r['pkg']:<26} {r['tool']:<26} missing={r['req_unnamed']}  (desc {r['desc_len']}c)")
print(f"  ... {n} such tools in total")
json.dump(rows, open("infoloss_results.json","w"), indent=1)
