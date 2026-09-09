"""Longitudinal tool-surface drift across consecutive releases, on ERA-CORRECT records.

Compatibility rule (caller's view). A -> B is BREAKING if a caller written against A can
issue a call B rejects or misreads: tool removed; required parameter added; parameter
removed; parameter type narrowed; optional became required; enum narrowed.
COMPATIBLE: tool added; optional parameter added; required became optional; type widened.
SEMANTIC: description changed with no schema change (invisible to schema checking, visible
to an LLM caller whose tool-selection logic is the description).
Records where every schema is empty are excluded as degenerate.
"""
import json, datetime, collections, sys
mode=sys.argv[1] if len(sys.argv)>1 else "era"
d=json.load(open("resolution_full.json"))
def schema_of(t):
    s=t.get("inputSchema") or {}; props=s.get("properties") or {}; req=set(s.get("required") or []); out={}
    for n,sp in props.items():
        sp=sp if isinstance(sp,dict) else {}; ty=sp.get("type")
        if ty is None and "anyOf" in sp: ty=sorted(str(a.get("type")) for a in sp["anyOf"] if isinstance(a,dict))
        out[n]={"type":ty if isinstance(ty,(str,list)) else json.dumps(ty,sort_keys=True),"req":n in req,"enum":tuple(sorted(map(str,sp["enum"]))) if isinstance(sp.get("enum"),list) else None}
    return out
def tset(x): return set(x) if isinstance(x,list) else ({x} if x else set())
def diff(a,b):
    ta={t["name"]:t for t in a}; tb={t["name"]:t for t in b}; brk=[];cmp_=[];sem=[]
    for n in ta:
        if n not in tb: brk.append(("tool removed",n,""))
    for n in tb:
        if n not in ta: cmp_.append(("tool added",n,""))
    for n in sorted(set(ta)&set(tb)):
        sa,sb=schema_of(ta[n]),schema_of(tb[n])
        for p in sa:
            if p not in sb: brk.append(("param removed",n,p))
        for p in sb:
            if p not in sa: (brk if sb[p]["req"] else cmp_).append((("required param added" if sb[p]["req"] else "optional param added"),n,p))
        for p in set(sa)&set(sb):
            if sa[p]["type"]!=sb[p]["type"]:
                wa,wb=tset(sa[p]["type"]),tset(sb[p]["type"])
                (cmp_ if wa and wb and wa<=wb else brk).append((("type widened" if wa and wb and wa<=wb else "type narrowed/changed"),n,f"{p}: {sa[p]['type']} -> {sb[p]['type']}"))
            if not sa[p]["req"] and sb[p]["req"]: brk.append(("optional became required",n,p))
            elif sa[p]["req"] and not sb[p]["req"]: cmp_.append(("required became optional",n,p))
            ea,eb=sa[p]["enum"],sb[p]["enum"]
            if ea and eb and set(ea)-set(eb): brk.append(("enum narrowed",n,f"{p}: -{sorted(set(ea)-set(eb))}"))
        if (ta[n].get("description") or "").strip()!=(tb[n].get("description") or "").strip():
            sem.append(("description changed",n,f"{len(ta[n].get('description') or '')}->{len(tb[n].get('description') or '')}c"))
    return brk,cmp_,sem
def degenerate(tools): return bool(tools) and all(not ((t.get("inputSchema") or {}).get("properties")) for t in tools)
per=collections.defaultdict(list)
for r in d.values():
    side=r.get(mode,{})
    if isinstance(side.get("n"),int) and "raw_tools" in side and not degenerate(side["raw_tools"]):
        per[r["package"]].append((r["published"],r["version"],side["raw_tools"]))
tot=tb=ts=tsem_only=0; allbrk=[]; allsem=[]; rows=[]
for p,recs in sorted(per.items()):
    recs.sort()
    if len(recs)<2: continue
    span=(datetime.date.fromisoformat(recs[-1][0])-datetime.date.fromisoformat(recs[0][0])).days/30.44
    nb=ns=nso=0
    for (da,va,ta),(db,vb,tb_) in zip(recs,recs[1:]):
        brk,cmp_,sem=diff(ta,tb_); tot+=1
        if brk: nb+=1
        if sem: ns+=1
        if sem and not brk: nso+=1
        for c in brk: allbrk.append((p,va,vb,db)+c)
        for c in sem: allsem.append((p,va,vb,db)+c)
    tb+=nb; ts+=ns; tsem_only+=nso
    rows.append((p,len(recs),len(recs)-1,span,len(recs[0][2]),len(recs[-1][2]),nb,ns,nso))
print(f"=== LONGITUDINAL DRIFT on {mode.upper()}-resolved records ===")
print(f"{'server':<28}{'rel':>4}{'trans':>6}{'months':>7}{'tools':>10}{'brk':>5}{'sem':>5}{'sem-only':>9}")
for p,n,tr,sp,t0,t1,nb,ns,nso in rows: print(f"{p:<28}{n:>4}{tr:>6}{sp:>7.1f}{f'{t0}->{t1}':>10}{nb:>5}{ns:>5}{nso:>9}")
print(f"{'TOTAL':<28}{sum(r[1] for r in rows):>4}{tot:>6}")
print(f"\ntransitions with >=1 BREAKING change      : {tb}/{tot} ({100*tb/tot:.1f}%)")
print(f"transitions with >=1 description change   : {ts}/{tot} ({100*ts/tot:.1f}%)")
print(f"description-only (schema-compatible) drift: {tsem_only}/{tot} ({100*tsem_only/tot:.1f}%)")
kinds=collections.Counter(c[4] for c in allbrk)
print("\nbreaking changes by kind:",dict(kinds))
print("\nall breaking instances:")
for c in allbrk: print(f"  {c[0]:<26}{c[1]:>11} -> {c[2]:<11} {c[4]:<26} {c[5]} {c[6]}")
print(f"\ndescription changes: {len(allsem)}; largest:")
for c in sorted(allsem,key=lambda c:-abs(int(c[6].split('->')[1][:-1])-int(c[6].split('->')[0])))[:8]: print(f"  {c[0]:<26}{c[1]:>11} -> {c[2]:<11} {c[5]:<28} {c[6]}")
json.dump({"rows":rows,"breaking":allbrk,"semantic":allsem,"totals":{"transitions":tot,"breaking":tb,"semantic":ts,"semantic_only":tsem_only}},open(f"drift_{mode}.json","w"),indent=1)
