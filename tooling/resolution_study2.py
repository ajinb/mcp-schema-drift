"""Controlled naive-vs-era comparison over the whole official family, storing the verbatim
tools/list under both resolutions so schema AND description drift can be studied on clean data.
Parallel over (package, version) with a small pool; npm installs are I/O bound."""
from __future__ import annotations
import json, os, subprocess, sys, shutil, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import probe
from harness import SERVERS, DUMMY_ENV
os.environ.update(DUMMY_ENV); os.environ["NO_COLOR"]="1"
ROOT=os.path.dirname(os.path.abspath(__file__)); WORK=os.path.join(ROOT,"reswork2"); OUT=os.path.join(ROOT,"resolution_full.json")
BIN={p:"mcp-"+p for p in SERVERS}   # every official server's bin is mcp-<name>
LOCK=threading.Lock()

def npm_versions(pkg):
    raw=subprocess.run(["curl","-sL","--max-time","60",f"https://registry.npmjs.org/@modelcontextprotocol/{pkg}"],capture_output=True,text=True).stdout
    d=json.loads(raw); t=d.get("time",{}); v=[(x,t[x][:10]) for x in d.get("versions",{}) if x in t]; v.sort(key=lambda x:x[1]); return v

def build(pkg,ver,date,mode):
    d=os.path.join(WORK,f"{pkg}@{ver}@{mode}"); shutil.rmtree(d,ignore_errors=True)
    os.makedirs(os.path.join(d,"sandbox"),exist_ok=True)
    json.dump({"name":"probe-env","private":True,"type":"module","dependencies":{f"@modelcontextprotocol/{pkg}":ver}},open(os.path.join(d,"package.json"),"w"))
    cmd=["npm","i","--silent","--no-audit","--no-fund","--ignore-scripts"]
    if mode=="era": cmd.append("--before="+(dt.date.fromisoformat(date)+dt.timedelta(days=2)).isoformat())
    r=subprocess.run(cmd,cwd=d,capture_output=True,text=True,timeout=900)
    return d if r.returncode==0 else None

def zod_of(d):
    p=os.path.join(d,"node_modules","zod","package.json") if d else None
    return json.load(open(p)).get("version") if p and os.path.exists(p) else None

def surface(d,pkg):
    if d is None: return {"install":"failed"}
    b=os.path.join(d,"node_modules",".bin",BIN[pkg])
    if not os.path.exists(b): return {"install":"no binary"}
    args=[os.path.join(d,"sandbox")] if pkg=="server-filesystem" else list(SERVERS[pkg]["args"])
    r=probe([b]+args,cwd=d,timeout=90); tools=r.get("tools")
    if not isinstance(tools,list): return {"error":str(r.get("error"))[:120]}
    summ={}
    for t in tools:
        s=t.get("inputSchema") or {}; props=list((s.get("properties") or {}).keys())
        summ[t["name"]]={"props":sorted(props),"required":sorted(s.get("required") or []),"empty":len(props)==0}
    return {"n":len(tools),"tools":summ,"empty_schemas":sum(1 for v in summ.values() if v["empty"]),
            "raw_tools":tools,"protocolVersion":r.get("protocolVersion"),"serverInfo":r.get("serverInfo")}

def job(pkg,ver,date):
    row={"package":pkg,"version":ver,"published":date}
    for mode in ("naive","era"):
        d=build(pkg,ver,date,mode); row[mode]=surface(d,pkg); row[mode+"_zod"]=zod_of(d); shutil.rmtree(d,ignore_errors=True)
    n,e=row["naive"],row["era"]; row["identical"]=(n.get("tools")==e.get("tools"))
    return row

def main():
    pkgs=sys.argv[1:] or list(SERVERS)
    res=json.load(open(OUT)) if os.path.exists(OUT) else {}
    tasks=[]
    for pkg in pkgs:
        try: vs=npm_versions(pkg)
        except Exception as ex: print("!!",pkg,ex,flush=True); continue
        for ver,date in vs:
            if f"{pkg}@{ver}" not in res: tasks.append((pkg,ver,date))
    print(f"{len(tasks)} version-pairs queued",flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs={ex.submit(job,*t):t for t in tasks}
        for f in as_completed(futs):
            pkg,ver,_=futs[f]
            try: row=f.result()
            except Exception as e: row={"package":pkg,"version":ver,"error":str(e)[:200]}
            with LOCK:
                res[f"{pkg}@{ver}"]=row; json.dump(res,open(OUT,"w"),indent=1)
            n,e=row.get("naive",{}),row.get("era",{})
            print(f"{pkg}@{ver:<12} naive={n.get('n')}t/{n.get('empty_schemas')}e zod={row.get('naive_zod')}  era={e.get('n')}t/{e.get('empty_schemas')}e zod={row.get('era_zod')}  {'SAME' if row.get('identical') else '*** DIFFERS ***'}",flush=True)

if __name__=="__main__": main()
