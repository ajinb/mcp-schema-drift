"""Controlled naive-vs-era comparison on popular THIRD-PARTY MCP servers (launchable with no
config). Servers with more than 15 releases are sampled to 12 evenly spaced by publish order,
always including the first and the latest."""
from __future__ import annotations
import json, os, subprocess, sys, shutil, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import probe
from harness import DUMMY_ENV
os.environ.update(DUMMY_ENV); os.environ["NO_COLOR"]="1"
os.environ.update({"CONTEXT7_API_KEY":"ctx7sk-"+"0"*32,"NOTION_API_KEY":"ntn_"+"0"*40,"NOTION_TOKEN":"ntn_"+"0"*40,
  "SUPABASE_ACCESS_TOKEN":"sbp_"+"0"*40,"DATADOG_API_KEY":"0"*32,"DATADOG_APP_KEY":"0"*40,"HOSTINGER_API_TOKEN":"0"*40,
  "CURRENTS_API_KEY":"0"*32,"DATABASE_URL":"postgresql://localhost/postgres"})
ROOT=os.path.dirname(os.path.abspath(__file__)); WORK=os.path.join(ROOT,"reswork3"); OUT=os.path.join(ROOT,"resolution_thirdparty.json")
LOCK=threading.Lock()
def get(url): return json.loads(subprocess.run(["curl","-sL","--max-time","60",url],capture_output=True,text=True).stdout)
def meta(pkg): return get(f"https://registry.npmjs.org/{pkg.replace('/','%2F')}")
def versions(m):
    t=m.get("time",{}); v=[(x,t[x][:10]) for x in m.get("versions",{}) if x in t and not any(s in x for s in ("alpha","beta","rc","canary","next","dev"))]
    v.sort(key=lambda x:x[1]); return v
def sample(v,k=12):
    if len(v)<=15: return v
    idx=sorted({0,len(v)-1}|{round(i*(len(v)-1)/(k-1)) for i in range(k)}); return [v[i] for i in idx]
def binname(m):
    b=m.get("versions",{}).get(m.get("dist-tags",{}).get("latest",""),{}).get("bin")
    if isinstance(b,dict): return list(b.keys())[0]
    return m.get("name","").split("/")[-1]
def build(pkg,ver,date,mode):
    d=os.path.join(WORK,(pkg+"@"+ver+"@"+mode).replace("/","__")); shutil.rmtree(d,ignore_errors=True); os.makedirs(d,exist_ok=True)
    json.dump({"name":"probe-env","private":True,"type":"module","dependencies":{pkg:ver}},open(os.path.join(d,"package.json"),"w"))
    cmd=["npm","i","--silent","--no-audit","--no-fund","--ignore-scripts"]
    if mode=="era": cmd.append("--before="+(dt.date.fromisoformat(date)+dt.timedelta(days=2)).isoformat())
    r=subprocess.run(cmd,cwd=d,capture_output=True,text=True,timeout=900)
    return d if r.returncode==0 else None
def libver(d,lib):
    p=os.path.join(d,"node_modules",lib,"package.json") if d else None
    return json.load(open(p)).get("version") if p and os.path.exists(p) else None
def surface(d,binn):
    if d is None: return {"install":"failed"}
    b=os.path.join(d,"node_modules",".bin",binn)
    if not os.path.exists(b):
        cands=os.listdir(os.path.join(d,"node_modules",".bin")) if os.path.isdir(os.path.join(d,"node_modules",".bin")) else []
        if len(cands)==1: b=os.path.join(d,"node_modules",".bin",cands[0])
        else: return {"install":"no binary","bins":cands[:5]}
    r=probe([b],cwd=d,timeout=90); tools=r.get("tools")
    if not isinstance(tools,list): return {"error":str(r.get("error"))[:120]}
    summ={t["name"]:{"props":sorted(((t.get("inputSchema") or {}).get("properties") or {}).keys()),"required":sorted((t.get("inputSchema") or {}).get("required") or []),"empty":not ((t.get("inputSchema") or {}).get("properties"))} for t in tools}
    return {"n":len(tools),"tools":summ,"empty_schemas":sum(1 for v in summ.values() if v["empty"]),"raw_tools":tools}
def job(pkg,ver,date,binn):
    row={"package":pkg,"version":ver,"published":date}
    for mode in ("naive","era"):
        d=build(pkg,ver,date,mode); row[mode]=surface(d,binn)
        row[mode+"_zod"]=libver(d,"zod"); row[mode+"_z2js"]=libver(d,"zod-to-json-schema"); row[mode+"_sdk"]=libver(d,"@modelcontextprotocol/sdk")
        shutil.rmtree(d,ignore_errors=True)
    row["identical"]=(row["naive"].get("tools")==row["era"].get("tools")); return row
def main():
    pkgs=sys.argv[1:]
    res=json.load(open(OUT)) if os.path.exists(OUT) else {}
    tasks=[]
    for pkg in pkgs:
        m=meta(pkg); bn=binname(m); vs=sample(versions(m))
        print(f"{pkg}: {len(versions(m))} releases, sampling {len(vs)}, bin={bn}",flush=True)
        for ver,date in vs:
            if f"{pkg}@{ver}" not in res: tasks.append((pkg,ver,date,bn))
    print(f"{len(tasks)} version-pairs queued",flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs={ex.submit(job,*t):t for t in tasks}
        for f in as_completed(futs):
            pkg,ver,_,_=futs[f]
            try: row=f.result()
            except Exception as e: row={"package":pkg,"version":ver,"error":str(e)[:200]}
            with LOCK: res[f"{pkg}@{ver}"]=row; json.dump(res,open(OUT,"w"),indent=1)
            n,e=row.get("naive",{}),row.get("era",{})
            print(f"{pkg}@{ver:<12} naive={n.get('n')}t/{n.get('empty_schemas')}e zod={row.get('naive_zod')} era={e.get('n')}t/{e.get('empty_schemas')}e zod={row.get('era_zod')}  {'SAME' if row.get('identical') else '*** DIFFERS ***'}",flush=True)
if __name__=="__main__": main()
