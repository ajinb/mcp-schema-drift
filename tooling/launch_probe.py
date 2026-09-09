"""Which popular third-party MCP servers will start and answer tools/list with no configuration?"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from probe import probe
from harness import DUMMY_ENV
os.environ.update(DUMMY_ENV); os.environ["NO_COLOR"]="1"
# plausible-looking placeholders for common third-party keys, so servers that only check presence get past startup
os.environ.update({"CONTEXT7_API_KEY":"ctx7sk-"+"0"*32,"NOTION_API_KEY":"ntn_"+"0"*40,"NOTION_TOKEN":"ntn_"+"0"*40,
  "SUPABASE_ACCESS_TOKEN":"sbp_"+"0"*40,"SENTRY_AUTH_TOKEN":"sntrys_"+"0"*40,"TAVILY_API_KEY":"tvly-"+"0"*32,
  "STRIPE_SECRET_KEY":"sk_test_"+"0"*24,"APIFY_TOKEN":"apify_api_"+"0"*36,"SLACK_MCP_XOXP_TOKEN":"xoxp-"+"0"*40,
  "HUBSPOT_ACCESS_TOKEN":"pat-na1-"+"0"*36,"CLICKUP_API_KEY":"pk_"+"0"*40,"SHORTCUT_API_TOKEN":"0"*36,
  "DATADOG_API_KEY":"0"*32,"DATADOG_APP_KEY":"0"*40,"GOOGLE_APPLICATION_CREDENTIALS":"/dev/null",
  "BACKLOG_DOMAIN":"example.backlog.com","BACKLOG_API_KEY":"0"*32,"DATABASE_URL":"postgresql://localhost/postgres",
  "HOSTINGER_API_TOKEN":"0"*40,"CURRENTS_API_KEY":"0"*32,"AIKIDO_API_KEY":"0"*32})
cands=json.load(open("candidates.json"))[:22]
res=[]
for dl,name,nv,first in cands:
    if name.endswith("-arm64") or name.endswith("-x64") or "darwin" in name or "linux" in name or "win32" in name: continue
    t0=time.time()
    r=probe(["npx","-y",name],timeout=120)
    tools=r.get("tools")
    ok=isinstance(tools,list) and len(tools)>0
    n=len(tools) if ok else 0
    empty=sum(1 for t in tools if not ((t.get("inputSchema") or {}).get("properties"))) if ok else None
    print(f"{'OK ' if ok else 'no '} {name:<40} tools={n:<3} empty={empty}  ({time.time()-t0:4.0f}s)  {'' if ok else str(r.get('error'))[:60]}",flush=True)
    res.append({"name":name,"weekly":dl,"versions":nv,"first":first,"ok":ok,"tools":n,"empty":empty})
json.dump(res,open("launchable.json","w"),indent=1)
print("\nlaunchable with no config:",[r["name"] for r in res if r["ok"]])
