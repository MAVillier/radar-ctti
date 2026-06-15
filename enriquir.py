#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enriquir.py — Omple el radar amb CRITERIS de puntuació i LICITADORS (qui s'ha
presentat, qui ha guanyat) llegint els documents del portal de contractació,
i ho injecta dins index.html (entre els marcadors /* ENRICH:start */ ... /* ENRICH:end */).

Només biblioteca estàndard de Python 3. Sense dependències.
Ús:   python3 enriquir.py
"""
import urllib.request, urllib.parse, json, time, re, os, sys

BASE = "https://analisi.transparenciacatalunya.cat/resource/ybgg-dgi6.json"
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
CAP = int(os.environ.get("CAP", "200"))          # màxim d'expedients a enriquir
PAL = ["#185FA5","#534AB7","#0F6E56","#854F0B","#A32D2D","#5F5E5A"]

GROUPS = {"301","302","322","324","325","503","513","516","642"} \
       | {"48"+str(i) for i in range(1,10)} \
       | {"72"+str(i) for i in range(1,10)} \
       | {"73"+str(i) for i in range(1,5)}

def get(url, tries=3, timeout=35):
    last=None
    for i in range(tries):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":"radar/1.0","Accept":"application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8","replace")
        except Exception as e:
            last=e; time.sleep(1.5+i)
    raise last

def soda(select, where, order=None, limit=1500):
    p={"$select":select,"$where":where,"$limit":str(limit)}
    if order: p["$order"]=order
    return json.loads(get(BASE+"?"+urllib.parse.urlencode(p)))

def txt(v):
    if isinstance(v,dict): return v.get("ca") or v.get("es") or v.get("en") or ""
    return v or ""
def url_of(v):
    return v.get("url") if isinstance(v,dict) else v
def cpv_match(full):
    return any(c.strip()[:3] in GROUPS for c in (full or "").split("||") if c.strip())
def norm(s):
    return re.sub(r"[^A-Z0-9]","", (s or "").upper())

def extract_criteris(doc):
    for lot in (doc.get("publicacio",{}).get("dadesPublicacioLot",[]) or []):
        items=[]
        for it in (lot.get("criterisAdjudicacio") or []):
            try: p=float(it.get("ponderacio"))
            except: p=None
            if not p or p<=0: continue
            items.append((txt(it.get("criteri")) or ("Criteri "+str(it.get("index",""))), p))
        if not items: continue
        s=sum(p for _,p in items)
        if s<=1.5:                      # ve en fracció (0.39) -> a punts
            items=[(l,p*100) for l,p in items]; s*=100
        if 1<=len(items)<=7 and 90<=s<=110:
            return [{"l":l,"p":round(p),"c":PAL[i%len(PAL)]} for i,(l,p) in enumerate(items)]
    return None

def extract_licitadors(doc, winner):
    wn=norm(winner)
    for lot in (doc.get("publicacio",{}).get("dadesPublicacioLot",[]) or []):
        emp=lot.get("identitatEmpresa") or []
        if not emp: continue
        out=[]
        for e in emp:
            nom=txt(e.get("empresa")); nif=e.get("identificadorEmpresa")
            g = bool(wn) and (norm(nom)[:12]!="" and norm(nom)[:12] in wn or wn[:12] in norm(nom))
            out.append({"nom":nom,"nif":nif,"g":bool(g)})
        if winner and not any(o["g"] for o in out):       # 2n intent, més tou
            for o in out:
                if norm(o["nom"])[:8] and norm(o["nom"])[:8] in wn:
                    o["g"]=True; break
        return out
    return None

def gather():
    """Recull expedients d'interès amb els seus enllaços a documents."""
    F="codi_expedient,codi_cpv,racionalitzacio_contractacio,denominacio_adjudicatari,url_json_licitacio,url_json_avaluacio,fase_publicacio"
    since=time.strftime("%Y-%m-%dT00:00:00", time.gmtime(time.time()-30*86400))
    GEN="nom_ambit like '%Generalitat de Catalunya%'"
    blocks=[]
    # prioritat: especifics SDA, en avaluacio, adjudicades CTTI, obertes
    blocks.append(soda(F, GEN+" AND fase_publicacio='Anunci de licitació' AND racionalitzacio_contractacio like '%Específic%'", "termini_presentacio_ofertes DESC", 200))
    blocks.append(soda(F, GEN+" AND fase_publicacio='Expedient en avaluació'", "termini_presentacio_ofertes DESC", 300))
    blocks.append(soda(F, "codi_organ='11110' AND fase_publicacio='Adjudicació'", "data_publicacio_adjudicacio DESC", 200))
    blocks.append(soda(F, GEN+" AND fase_publicacio='Anunci de licitació' AND termini_presentacio_ofertes > '"+since+"'", "termini_presentacio_ofertes ASC", 1500))
    seen={}
    for blk in blocks:
        for r in blk:
            k=r.get("codi_expedient")
            if not k or k in seen: continue
            if not (cpv_match(r.get("codi_cpv")) or "Específic" in (r.get("racionalitzacio_contractacio") or "")): continue
            seen[k]=r
            if len(seen)>=CAP: break
        if len(seen)>=CAP: break
    return list(seen.values())

def main():
    print("Recollint expedients d'interès…")
    rows=gather()
    print(f"  {len(rows)} expedients a processar (CAP={CAP})")
    ENRICH={}; nc=nb=0
    for i,r in enumerate(rows,1):
        exp=r["codi_expedient"]; ent={}
        lic=url_of(r.get("url_json_licitacio")); ava=url_of(r.get("url_json_avaluacio"))
        if lic:
            try:
                c=extract_criteris(json.loads(get(lic)))
                if c: ent["criteris"]=c; nc+=1
            except Exception: pass
        if ava:
            try:
                b=extract_licitadors(json.loads(get(ava)), r.get("denominacio_adjudicatari"))
                if b: ent["licitadors"]=b; nb+=1
            except Exception: pass
        if ent: ENRICH[exp]=ent
        if i%10==0: print(f"  …{i}/{len(rows)}  criteris={nc} licitadors={nb}")
        time.sleep(0.25)
    print(f"FET: {len(ENRICH)} expedients enriquits (amb criteris={nc}, amb licitadors={nb})")

    html=open(INDEX, encoding="utf-8").read()
    repl="/* ENRICH:start (no editar a ma; ho regenera enriquir.py) */\nconst ENRICH = "+json.dumps(ENRICH, ensure_ascii=False)+";\n/* ENRICH:end */"
    html2=re.sub(r"/\* ENRICH:start.*?/\* ENRICH:end \*/", lambda m: repl, html, count=1, flags=re.S)
    if html2==html:
        print("AVÍS: no s'han trobat els marcadors ENRICH a index.html"); sys.exit(1)
    open(INDEX,"w",encoding="utf-8").write(html2)
    print("index.html actualitzat:", len(html2), "bytes")

if __name__=="__main__":
    main()
