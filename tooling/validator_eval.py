"""Evaluate the startup tool-surface validators proposed in the Mitigation section.

R1  reject when EVERY advertised tool has an empty input schema (total-loss detector)
R2  reject when ANY advertised tool has an empty input schema (strict)
R3  reject when any tool has an empty schema AND its description names an argument-like
    word (path, file, name, query, id, url, content, text, channel, repo, owner, key ...)
R4  reject when the advertised surface differs from a recorded baseline (era-correct probe
    of the same release) in any tool's parameter set or required set

Ground truth: a record is DEGRADED if the controlled comparison shows its naive surface
differs from its era surface; HEALTHY otherwise. Evaluate on the controlled pairs.
"""
import json, re, time, glob
ARGWORDS=set("path file files directory dir name query id url uri content text message channel repo owner branch key value pattern entity entities relation relations observation observations thought number title body issue pull number user email token".split())
def empty(t): return not ((t.get("inputSchema") or {}).get("properties"))
def r1(tools): return bool(tools) and all(empty(t) for t in tools)
def r2(tools): return any(empty(t) for t in tools)
def r3(tools):
    for t in tools:
        if empty(t):
            words=set(re.findall(r"[a-z]+",(t.get("description") or "").lower()))
            if words & ARGWORDS: return True
    return False
def sig(tools): return {t["name"]:(tuple(sorted(((t.get("inputSchema") or {}).get("properties") or {}).keys())),tuple(sorted((t.get("inputSchema") or {}).get("required") or []))) for t in tools}
def r4(tools,baseline): return sig(tools)!=sig(baseline)

# controlled pairs with raw tools (new run) -- fall back to old run's summarised surface
res={}
for f in ["resolution_full.json","resolution_results.json"]:
    try:
        for k,v in json.load(open(f)).items(): res.setdefault(k,v)
    except FileNotFoundError: pass
rows=[]
for k,r in res.items():
    n,e=r.get("naive",{}),r.get("era",{})
    if not isinstance(n.get("n"),int) or not isinstance(e.get("n"),int): continue
    degraded=not r["identical"]
    if "raw_tools" in n and "raw_tools" in e:
        nt,et=n["raw_tools"],e["raw_tools"]
    else:
        # reconstruct minimal tool records from summaries (props/required only; no descriptions)
        nt=[{"name":a,"inputSchema":{"properties":{p:{} for p in b["props"]},"required":b["required"]},"description":""} for a,b in n["tools"].items()]
        et=[{"name":a,"inputSchema":{"properties":{p:{} for p in b["props"]},"required":b["required"]},"description":""} for a,b in e["tools"].items()]
    rows.append({"key":k,"pkg":r["package"],"degraded":degraded,"R1":r1(nt),"R2":r2(nt),"R3":r3(nt),"R4":r4(nt,et),
                 "R2_healthy_side":r2(et)})
deg=[r for r in rows if r["degraded"]]; ok=[r for r in rows if not r["degraded"]]
print(f"controlled pairs evaluated: {len(rows)}  degraded={len(deg)} healthy={len(ok)}")
print(f"{'rule':<6}{'detects degraded':>18}{'false positives on healthy':>28}")
for R in ["R1","R2","R3","R4"]:
    tp=sum(1 for r in deg if r[R]); fp=sum(1 for r in ok if r[R])
    print(f"{R:<6}{tp:>7}/{len(deg):<10}{fp:>12}/{len(ok)}")
print("\nR2 on the HEALTHY (era) surfaces -- legitimately parameterless tools trip it:",sum(1 for r in rows if r['R2_healthy_side']),"of",len(rows))
print("\nmissed by R1 (the subtle required-set case):",[r['key'] for r in deg if not r['R1']])
# overhead
import statistics
samp=[r for r in res.values() if isinstance(r.get('naive',{}).get('n'),int)][:50]
t0=time.perf_counter()
for _ in range(200):
    for r in samp:
        n=r['naive']; tools=n.get('raw_tools') or [{"name":a,"inputSchema":{"properties":{p:{} for p in b['props']},"required":b['required']},"description":""} for a,b in n['tools'].items()]
        r1(tools); r2(tools); r3(tools)
dt=(time.perf_counter()-t0)/(200*len(samp))*1e6
print(f"\nvalidator cost per surface (R1+R2+R3): {dt:.1f} microseconds")
json.dump(rows,open("validator_eval.json","w"),indent=1)
