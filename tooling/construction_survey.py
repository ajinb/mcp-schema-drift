"""Which schema-generation construction does each server use, and what does its tree resolve today?
Installs the latest release of each server and greps the package's own code (not its deps)."""
import json, os, re, subprocess, shutil, sys
from concurrent.futures import ThreadPoolExecutor
ROOT=os.path.dirname(os.path.abspath(__file__)); W=os.path.join(ROOT,"conswork"); os.makedirs(W,exist_ok=True)
OFFICIAL=["@modelcontextprotocol/server-"+s for s in "filesystem everything memory sequential-thinking github gitlab slack postgres puppeteer brave-search google-maps redis".split()]
THIRD=["chrome-devtools-mcp","@upstash/context7-mcp","@notionhq/notion-mcp-server","hostinger-api-mcp","@supabase/mcp-server-supabase","nx-mcp","@sap-ux/fiori-mcp-server","@ui5/mcp-server","@cap-js/mcp-server","@softeria/ms-365-mcp-server","@currents/mcp","@winor30/mcp-server-datadog","@yawlabs/postgres-mcp"]
PATS={"zodToJsonSchema (direct converter)":r"zodToJsonSchema\(|zod-to-json-schema","registerTool (SDK ≥1.19 path)":r"\.registerTool\(","server.tool() (SDK path)":r"\.tool\(\s*['\"]","z.toJSONSchema (zod4 native)":r"toJSONSchema\(","literal JSON Schema ('type':'object')":r"type:\s*['\"]object['\"]|\"type\":\s*\"object\"","ListToolsRequestSchema handler":r"ListToolsRequestSchema"}
def ver(d,lib):
    p=os.path.join(d,"node_modules",lib,"package.json"); return json.load(open(p)).get("version") if os.path.exists(p) else None
def one(pkg):
    d=os.path.join(W,pkg.replace("/","__")); shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
    json.dump({"name":"c","private":True,"dependencies":{pkg:"latest"}},open(os.path.join(d,"package.json"),"w"))
    r=subprocess.run(["npm","i","--silent","--no-audit","--no-fund","--ignore-scripts"],cwd=d,capture_output=True,text=True,timeout=600)
    if r.returncode!=0: return {"pkg":pkg,"error":"install failed"}
    code=os.path.join(d,"node_modules",*pkg.split("/"))
    counts={k:0 for k in PATS}
    for dp,dn,fn in os.walk(code):
        if "node_modules" in dp.split(os.sep)[len(code.split(os.sep)):]: continue
        for f in fn:
            if f.endswith((".js",".mjs",".cjs")):
                try: s=open(os.path.join(dp,f),errors="ignore").read()
                except Exception: continue
                for k,p in PATS.items(): counts[k]+=len(re.findall(p,s))
    out={"pkg":pkg,"zod":ver(d,"zod"),"z2js":ver(d,"zod-to-json-schema"),"sdk":ver(d,"@modelcontextprotocol/sdk"),"counts":counts}
    # direct dependency declarations
    pj=json.load(open(os.path.join(code,"package.json"))); dep=pj.get("dependencies",{})
    out["declares"]={k:dep[k] for k in ("zod","zod-to-json-schema","@modelcontextprotocol/sdk") if k in dep}
    shutil.rmtree(d,ignore_errors=True); return out
with ThreadPoolExecutor(max_workers=4) as ex: rows=list(ex.map(one,OFFICIAL+THIRD))
json.dump(rows,open("construction_survey.json","w"),indent=1)
short={"zodToJsonSchema (direct converter)":"z2js","registerTool (SDK ≥1.19 path)":"regTool","server.tool() (SDK path)":"s.tool","z.toJSONSchema (zod4 native)":"native","literal JSON Schema ('type':'object')":"literal","ListToolsRequestSchema handler":"ListTools"}
print(f"{'package':<36}{'zod':>8}{'z2js':>8}{'sdk':>8}  {'z2js':>5}{'regTool':>8}{'s.tool':>7}{'native':>7}{'literal':>8}{'ListT':>6}   declares")
for r in rows:
    if "error" in r: print(f"{r['pkg']:<36} {r['error']}"); continue
    c=r["counts"]; print(f"{r['pkg']:<36}{str(r['zod']):>8}{str(r['z2js']):>8}{str(r['sdk']):>8}  "+"".join(f"{c[k]:>{w}}" for k,w in zip(PATS,(5,8,7,7,8,6)))+f"   {r['declares']}")
