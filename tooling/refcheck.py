import os, re, sys, json, subprocess, xml.etree.ElementTree as ET, time, unicodedata
import sys
T2=sys.argv[1] if len(sys.argv)>1 else "."
s=open(os.path.join(T2,"main.tex")).read()
bib=s[s.index("\\begin{thebibliography}"):]
items=re.findall(r"\\bibitem\{(\w+)\}(.*?)(?=\\bibitem\{|\\end\{thebibliography\})", bib, re.S)
ns={'a':'http://www.w3.org/2005/Atom'}
def norm(x):
    x=unicodedata.normalize("NFKD",x)
    x=re.sub(r"[^\w\s]"," ",x.lower()); return re.sub(r"\s+"," ",x).strip()
def lastname(n): return norm(n.split()[-1]) if n.split() else ""
ids=[]
for k,body in items:
    m=re.search(r"arXiv:(\d{4}\.\d{4,5})",body)
    ids.append((k,body,m.group(1) if m else None))
live={}
batch=[i for _,_,i in ids if i]
for chunk in [batch[:20],batch[20:]]:
    raw=subprocess.run(["curl","-sL","--max-time","90","-A","ph/1.0",
        "https://export.arxiv.org/api/query?id_list=%s&max_results=40"%",".join(chunk)],capture_output=True,text=True).stdout
    for e in ET.fromstring(raw).findall('a:entry',ns):
        i=e.find('a:id',ns).text.split('/abs/')[-1].split('v')[0]
        live[i]={"title":re.sub(r"\s+"," ",e.find('a:title',ns).text.strip()),
                 "authors":[a.find('a:name',ns).text for a in e.findall('a:author',ns)],
                 "year":e.find('a:published',ns).text[:4]}
    time.sleep(3)
print(f"{'key':<16}{'id':<13} verdict")
print("-"*100)
bad=0
for k,body,i in ids:
    if not i:
        print(f"{k:<16}{'--':<13} NON-ARXIV (manual check): {re.sub(chr(10),' ',body).strip()[:80]}"); continue
    if i not in live:
        print(f"{k:<16}{i:<13} *** DID NOT RESOLVE ***"); bad+=1; continue
    L=live[i]
    # title
    mt=re.search(r"``(.+?),''", body, re.S)
    ptitle=re.sub(r"\s+"," ",mt.group(1)) if mt else ""
    ptitle=ptitle.replace("$\\tau$","τ").replace("\\emph{","").replace("}","")
    tok=norm(ptitle); lok=norm(L["title"])
    title_ok = tok==lok or tok in lok or lok in tok
    # authors: paper lists initials + surname before the title
    head=body[:body.index("``")] if "``" in body else body
    head=re.sub(r"\\emph\{[^}]*\}","",head)
    psur=[lastname(x) for x in re.split(r",| and ", head) if len(x.strip())>2 and not x.strip().startswith("\\")]
    psur=[p for p in psur if p and p not in ("et","al","al.")]
    etal = "et al" in head or "\\emph{et al" in body[:body.index("``")] if "``" in body else False
    lsur=[lastname(a) for a in L["authors"]]
    if etal:
        auth_ok = all(p in lsur for p in psur)
        acount = f"{len(psur)}+etal vs {len(lsur)}"
    else:
        auth_ok = [p for p in psur]==lsur
        acount = f"{len(psur)} vs {len(lsur)}"
    # year
    my=re.search(r"(\d{4})\.\s*$", body.strip()) or re.search(r",\s*(\d{4})\.", body)
    pyear=my.group(1) if my else "?"
    year_ok = pyear==L["year"]
    flags=[]
    if not title_ok: flags.append("TITLE")
    if not auth_ok: flags.append("AUTHORS")
    if not year_ok: flags.append(f"YEAR({pyear} vs {L['year']})")
    if flags:
        bad+=1
        print(f"{k:<16}{i:<13} *** {' '.join(flags)} ***   [{acount}]")
        if not title_ok: print(f"{'':16}  paper: {ptitle[:88]}\n{'':16}  live : {L['title'][:88]}")
        if not auth_ok: print(f"{'':16}  paper: {psur}\n{'':16}  live : {lsur}")
    else:
        print(f"{k:<16}{i:<13} ok  [{acount}]")
print("-"*100); print("entries flagged:",bad,"of",len(ids))
