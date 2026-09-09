"""Severity A/B on HARD schemas: the knowledge-graph memory server.

Its tools take nested arrays of objects with unguessable key names -- entities[].entityType,
entities[].observations, relations[].relationType, observations[].entityName,
observations[].contents -- and section 4.6 found this family loses every required parameter
on most tools. Same design as severity.py: identical model, tasks, server; only the advertised
schema differs. Ground truth is read from the server's own graph after each trial.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, uuid
SERVER="@modelcontextprotocol/server-memory@2026.8.31"
CONDITIONS={"full":None,"emptied_norm":{"type":"object","properties":{}},
            "emptied_open":{"type":"object","properties":{},"additionalProperties":True}}

class MCP:
    def __init__(self, memfile):
        env=dict(os.environ); env["MEMORY_FILE_PATH"]=memfile
        self.p=subprocess.Popen(["npx","-y",SERVER],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,text=True,bufsize=1,env=env)
        self._id=0
        self.rpc("initialize",{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"sev","version":"1"}})
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})+"\n"); self.p.stdin.flush()
    def rpc(self,m,params,timeout=120):
        self._id+=1; mid=self._id
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","id":mid,"method":m,"params":params})+"\n"); self.p.stdin.flush()
        end=time.time()+timeout
        while time.time()<end:
            line=self.p.stdout.readline()
            if not line: break
            try: msg=json.loads(line)
            except Exception: continue
            if msg.get("id")==mid: return msg
        return {"error":{"message":"timeout"}}
    def tools(self): return self.rpc("tools/list",{}).get("result",{}).get("tools",[])
    def call(self,name,args):
        r=self.rpc("tools/call",{"name":name,"arguments":args})
        if "error" in r: return False,json.dumps(r["error"])[:400]
        res=r.get("result",{})
        if res.get("isError"): return False,json.dumps(res.get("content"))[:400]
        return True,json.dumps(res.get("content"))[:3000]
    def graph(self):
        ok,out=self.call("read_graph",{})
        try:
            c=json.loads(out); txt=c[0]["text"] if isinstance(c,list) else "{}"
            return json.loads(txt)
        except Exception: return {"entities":[],"relations":[]}
    def close(self):
        try: self.p.kill()
        except Exception: pass

def seed(s,entities=(),relations=()):
    if entities: s.call("create_entities",{"entities":[{"name":n,"entityType":t,"observations":list(o)} for n,t,o in entities]})
    if relations: s.call("create_relations",{"relations":[{"from":a,"to":b,"relationType":r} for a,b,r in relations]})

def ents(g): return {e["name"]:e for e in g.get("entities",[])}
def rels(g): return {(r["from"],r["to"],r["relationType"]) for r in g.get("relations",[])}
def anyout(tr,needle): return any(ok and needle in out for _,_,ok,out in tr)

TASKS=[
 {"id":"create_one","seed":{},"prompt":"Create an entity named Alice of type Person with the observation 'works at Acme'.",
  "check":lambda tr,g: "Alice" in ents(g) and ents(g)["Alice"].get("entityType")=="Person"},
 {"id":"create_two","seed":{},"prompt":"Create two entities: Bob, a Person, and Acme, a Company.",
  "check":lambda tr,g: {"Bob","Acme"}<=set(ents(g))},
 {"id":"relation","seed":{"entities":[("Alice","Person",["engineer"]),("Acme","Company",[])]},
  "prompt":"Record that Alice works at Acme, as a relation of type works_at.",
  "check":lambda tr,g: any(a=="Alice" and b=="Acme" for a,b,_ in rels(g))},
 {"id":"add_obs","seed":{"entities":[("Alice","Person",["engineer"])]},
  "prompt":"Add the observation 'likes tea' to the entity Alice.",
  "check":lambda tr,g: "likes tea" in ents(g).get("Alice",{}).get("observations",[])},
 {"id":"search","seed":{"entities":[("Alice","Person",["likes tea"]),("Bob","Person",["likes coffee"])]},
  "prompt":"Which entities in the graph mention tea?",
  "check":lambda tr,g: anyout(tr,"Alice")},
 {"id":"open","seed":{"entities":[("Acme","Company",["founded 1999","based in Denver"])]},
  "prompt":"Show me everything known about the entity Acme.",
  "check":lambda tr,g: anyout(tr,"Denver")},
 {"id":"delete_ent","seed":{"entities":[("Bob","Person",["temp"]),("Alice","Person",["keep"])]},
  "prompt":"Delete the entity named Bob from the graph.",
  "check":lambda tr,g: "Bob" not in ents(g) and "Alice" in ents(g)},
 {"id":"read_all","seed":{"entities":[("Alice","Person",[]),("Acme","Company",[])]},
  "prompt":"List every entity currently in the graph.",
  "check":lambda tr,g: anyout(tr,"Alice") and anyout(tr,"Acme")},
 {"id":"chain","seed":{"entities":[("Alice","Person",[])]},
  "prompt":"Create an entity Carol of type Person, then record a relation that Carol knows Alice (type knows).",
  "check":lambda tr,g: "Carol" in ents(g) and ("Carol","Alice","knows") in rels(g)},
 {"id":"delete_obs","seed":{"entities":[("Alice","Person",["works at Acme","likes tea"])]},
  "prompt":"Remove the observation 'works at Acme' from Alice, keeping her other observations.",
  "check":lambda tr,g: "works at Acme" not in ents(g).get("Alice",{}).get("observations",[]) and "likes tea" in ents(g).get("Alice",{}).get("observations",[])},
]

def trial(client,model,cond,task,base,max_turns=6):
    memfile=os.path.join(base,f"mem-{uuid.uuid4().hex[:8]}.jsonl")
    s=MCP(memfile)
    try:
        seed(s,**task["seed"])
        real=s.tools(); tools=[]
        for t in real:
            ov=CONDITIONS[cond]
            tools.append({"name":t["name"],"description":t.get("description",""),
                          "input_schema":t.get("inputSchema") if ov is None else dict(ov)})
        msgs=[{"role":"user","content":"You have knowledge-graph memory tools. "+task["prompt"]}]
        tr=[];calls=bad=0
        for _ in range(max_turns):
            r=client.messages.create(model=model,max_tokens=2048,tools=tools,messages=msgs)
            uses=[b for b in r.content if getattr(b,"type","")=="tool_use"]
            msgs.append({"role":"assistant","content":r.content})
            if not uses: break
            results=[]
            for u in uses:
                calls+=1; ok,out=s.call(u.name,u.input or {})
                if not ok: bad+=1
                tr.append((u.name,u.input,ok,out))
                results.append({"type":"tool_result","tool_use_id":u.id,"content":out,"is_error":not ok})
            msgs.append({"role":"user","content":results})
            if r.stop_reason!="tool_use": break
        g=s.graph()
        return {"model":model,"condition":cond,"task":task["id"],"success":bool(task["check"](tr,g)),
                "calls":calls,"failed_calls":bad,"first_call":(tr[0][0],tr[0][1]) if tr else None}
    finally:
        s.close()
        try: os.remove(memfile)
        except Exception: pass

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--models",default="claude-haiku-4-5,claude-sonnet-5")
    ap.add_argument("--seeds",type=int,default=3); ap.add_argument("--out",default="severity_memory.json"); a=ap.parse_args()
    import anthropic; client=anthropic.Anthropic()
    base=os.path.join(os.path.dirname(os.path.abspath(__file__)),"memwork"); os.makedirs(base,exist_ok=True)
    rows=json.load(open(a.out)) if os.path.exists(a.out) else []
    seen={(r["model"],r["condition"],r["task"],r.get("seed")) for r in rows}
    for model in a.models.split(","):
        for seed_i in range(a.seeds):
            for task in TASKS:
                for cond in CONDITIONS:
                    if (model,cond,task["id"],seed_i) in seen: continue
                    try: r=trial(client,model,cond,task,base)
                    except Exception as e: r={"model":model,"condition":cond,"task":task["id"],"success":False,"error":f"{type(e).__name__}: {str(e)[:200]}"}
                    r["seed"]=seed_i; rows.append(r); json.dump(rows,open(a.out,"w"),indent=1)
                    print(f"{model} {cond:<13}{task['id']:<11}s{seed_i} -> {'OK ' if r.get('success') else 'FAIL'} calls={r.get('calls')} bad={r.get('failed_calls')}",flush=True)
    print("\n"+"="*70)
    for m in sorted({r["model"] for r in rows}):
        for c in CONDITIONS:
            sub=[r for r in rows if r["model"]==m and r["condition"]==c]
            if not sub: continue
            s=sum(1 for r in sub if r.get("success")); tc=sum(r.get("calls") or 0 for r in sub); bc=sum(r.get("failed_calls") or 0 for r in sub)
            print(f"{m:<22}{c:<14}success {s}/{len(sub)} ({100*s/len(sub):5.1f}%)  calls/task {tc/len(sub):.2f}  rejected {bc}/{tc}")
if __name__=="__main__": main()
