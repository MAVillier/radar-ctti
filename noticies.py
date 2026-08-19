#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
noticies.py — Recull notícies (Google News ca/es, BOE, DOGC) sobre licitacions
TIC de l'administració catalana, les creua amb el radar, i genera:
  - noticies.json  (titulars + resum + font + enllaç + etiquetes)
  - alertes.json   (futures licitacions anunciades + contractes a punt de vèncer)
Només biblioteca estàndard. Ús: python3 noticies.py
"""
import urllib.request, urllib.parse, json, time, re, os, html, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SODA = "https://analisi.transparenciacatalunya.cat/resource/ybgg-dgi6.json"
DOGC = "https://analisi.transparenciacatalunya.cat/resource/n6hn-rmy7.json"
BOE  = "https://www.boe.es/datosabiertos/api/boe/sumario/{}"
UA   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) radar-tic/1.0"
NOW  = datetime.now(timezone.utc)

GROUPS = {"301","302","322","324","325","503","513","516","642"} \
       | {"48"+str(i) for i in range(1,10)} \
       | {"72"+str(i) for i in range(1,10)} \
       | {"73"+str(i) for i in range(1,5)}

def get(url, timeout=45, tries=3, hdrs=None):
    last=None
    for i in range(tries):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA,"Accept":"*/*", **(hdrs or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8","replace")
        except Exception as e:
            last=e; time.sleep(2+2*i)
    raise last

def soda(base, select, where, order=None, limit=1000):
    p={"$select":select,"$where":where,"$limit":str(limit)}
    if order:p["$order"]=order
    return json.loads(get(base+"?"+urllib.parse.urlencode(p)))

def txt(v):
    if isinstance(v,dict): return v.get("ca") or v.get("es") or v.get("en") or ""
    return v or ""
def url_of(v): return v.get("url") if isinstance(v,dict) else v
def cpv_match(full): return any(c.strip()[:3] in GROUPS for c in (full or "").split("||") if c.strip())
def clean(s):
    s=html.unescape(re.sub(r"<[^>]+>"," ", s or ""))
    return re.sub(r"\s+"," ", s).strip()

# ------------------------------------------------------------------ NOTÍCIES
GN = "https://news.google.com/rss/search?q={q}&hl={hl}&gl=ES&ceid={ceid}"
QUERIES = [
    ("CTTI", "ca", "ES:ca"),
    ("licitació Generalitat", "ca", "ES:ca"),
    ('"contractació pública"', "ca", "ES:ca"),
    ("Generalitat digitalització OR ciberseguretat OR tecnologia", "ca", "ES:ca"),
    ("licitació informàtica Barcelona OR Girona OR Lleida OR Tarragona", "ca", "ES:ca"),
    ('"ley de contratos del sector público"', "es-419", "ES:es-419"),
    ('"contratación pública" Cataluña OR Generalitat', "es-419", "ES:es-419"),
    ("Ajuntament de Barcelona tecnologia OR informàtica OR digital", "ca", "ES:ca"),
    ("concurs públic tecnologia Catalunya", "ca", "ES:ca"),
]
KW_KEEP = re.compile(r"licitaci|contract|contrat|adjudicaci|tic\b|tecnolog|digital|ciberseg|inform\u00e0tic|informátic|cloud|dades|datos|intel\u00b7lig|inteligencia|programari|software|telecomunicac|ctti|generalitat|diputaci|ajuntament|sector p", re.I)
CAT_HINT = re.compile(r"catalu|catalan|generalitat|barcelona|girona|lleida|tarragona|\bctti\b|\bdogc\b|badalona|sabadell|terrassa|matar\u00f3|reus|hospitalet|amb\b|\bbit\b|institut municipal", re.I)
EXCL_PV = re.compile(r"gva\.es|comunitat valenciana|generalitat valenciana|112cv|castell[oó]|alacant|val[eè]ncia", re.I)
CAT_STRONG = re.compile(r"catalu|\bctti\b|barcelona|girona|lleida|tarragona|badalona|sabadell|terrassa|matar[oó]|hospitalet", re.I)
NORM_HINT = re.compile(r"ley de contratos|lcsp|desindexaci|revisi[oó]n de precios|junta consultiva|tribunal.*contrat|contrataci[oó]n p[úu]blica.*(reforma|modificaci|directiva|umbral|llindar)|directiva.*contrataci", re.I)

def parse_rss(xml):
    out=[]
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        t=re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        l=re.search(r"<link>(.*?)</link>", it, re.S)
        d=re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        s=re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
        de=re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", it, re.S)
        title=clean(t.group(1)) if t else ""
        if not title: continue
        # Google posa " - Font" al final del títol
        src=clean(s.group(1)) if s else ""
        if src and title.endswith(" - "+src): title=title[:-(len(src)+3)]
        try:
            dt=datetime.strptime(clean(d.group(1))[:25].strip(), "%a, %d %b %Y %H:%M:%S")
            dt=dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt=NOW
        out.append({"t":title, "link":clean(l.group(1)) if l else "", "src":src or "Google News",
                    "date":dt.isoformat(), "sum":clean(de.group(1))[:240] if de else ""})
    return out

def collect_news():
    items=[]
    for q,hl,ceid in QUERIES:
        try:
            u=GN.format(q=urllib.parse.quote(q), hl=hl, ceid=urllib.parse.quote(ceid,safe=":"))
            xml=get(u, timeout=30)
            items+=parse_rss(xml)
        except Exception as e:
            print("  [gnews] salto", q[:30], str(e)[:60])
        time.sleep(0.6)
    # BOE (avui i 2 dies enrere): NOMÉS secció I (disposicions generals) — canvis normatius
    for dd in (NOW, NOW-timedelta(days=1), NOW-timedelta(days=2)):
        try:
            j=json.loads(get(BOE.format(dd.strftime("%Y%m%d")), timeout=30, hdrs={"Accept":"application/json"}))
            def items_sec1(o):
                if isinstance(o,dict):
                    if str(o.get("codigo"))=="1" and ("departamento" in o or "item" in o):
                        def leafs(x):
                            if isinstance(x,dict):
                                if "titulo" in x and ("url_html" in x or "identificador" in x): yield x
                                for v in x.values(): yield from leafs(v)
                            elif isinstance(x,list):
                                for v in x: yield from leafs(v)
                        yield from leafs(o)
                    else:
                        for v in o.values(): yield from items_sec1(v)
                elif isinstance(o,list):
                    for v in o: yield from items_sec1(v)
            for it in items_sec1(j):
                ti=clean(str(it.get("titulo")))
                if re.search(r"contrat|desindexaci|licitaci|sector p[úu]blico", ti, re.I):
                    u=it.get("url_html") or ("https://www.boe.es/diario_boe/txt.php?id="+str(it.get("identificador")))
                    items.append({"t":ti[:220],"link":u,"src":"BOE · Disposicions","date":dd.strftime("%Y-%m-%dT08:00:00+00:00"),"sum":"Disposició general publicada al BOE (pot afectar la contractació pública)."})
        except Exception as e:
            print("  [boe] salto", dd.strftime("%Y%m%d"), str(e)[:60])
    # DOGC: normativa recent amb 'contract'
    try:
        since=(NOW-timedelta(days=21)).strftime("%Y-%m-%dT00:00:00")
        rows=soda(DOGC, "t_tol_de_la_norma,rang_de_norma,n_mero_de_control,data_de_publicaci_del_diari",
                  "data_de_publicaci_del_diari > '"+since+"' AND (upper(t_tol_de_la_norma) like '%CONTRACT%' OR upper(t_tol_de_la_norma) like '%LICITACI%')",
                  order="data_de_publicaci_del_diari DESC", limit=15)
        for r in rows:
            nc=r.get("n_mero_de_control")
            items.append({"t":clean(r.get("t_tol_de_la_norma"))[:220],
                          "link":"https://portaljuridic.gencat.cat/eli/es-ct/"+str(nc) if nc else "https://dogc.gencat.cat",
                          "src":"DOGC · "+(r.get("rang_de_norma") or "norma"),
                          "date":(r.get("data_de_publicaci_del_diari") or "")[:19]+"+00:00",
                          "sum":"Normativa publicada al DOGC."})
    except Exception as e:
        print("  [dogc] salto:", str(e)[:80])
    # filtre temàtic + dedupe + finestra 14 dies
    seen=set(); out=[]
    cutoff=NOW-timedelta(days=21)
    for it in items:
        blob=it["t"]+" "+it.get("sum","")+" "+it.get("src","")
        if not KW_KEEP.search(blob): continue
        official=it["src"].startswith(("BOE","DOGC"))
        if not official and not CAT_HINT.search(blob) and not NORM_HINT.search(blob): continue
        if not official and EXCL_PV.search(blob) and not CAT_STRONG.search(blob): continue
        try:
            d=datetime.fromisoformat(it["date"].replace("Z","+00:00"))
        except Exception:
            d=NOW
        if d<cutoff: continue
        k=re.sub(r"\W+","", it["t"].lower())[:70]
        if k in seen: continue
        seen.add(k); it["date"]=d.isoformat(); out.append(it)
    out.sort(key=lambda x:x["date"], reverse=True)
    return out[:60]

# ------------------------------------------------------ CREUAMENT AMB EL RADAR
def load_snapshot():
    try:
        h=open(os.path.join(HERE,"index.html"),encoding="utf-8").read()
        m=re.search(r"const SNAPSHOT=(\{.*?\});\n/\* SNAPSHOT:end", h, re.S)
        return json.loads(m.group(1)) if m else {}
    except Exception:
        return {}

ORG_TAGS = [
    (re.compile(r"\bCTTI\b|Telecomunicacions i Tecnologies", re.I), "CTTI"),
    (re.compile(r"Generalitat", re.I), "Generalitat"),
    (re.compile(r"Barcelona Innovaci|Institut Municipal d.Inform|IMI\b|\bBIT\b", re.I), "BIT"),
    (re.compile(r"Diputaci", re.I), "Diputacions"),
    (re.compile(r"Ajuntament", re.I), "Ajuntaments"),
    (re.compile(r"\bBOE\b|sector p[úu]blico|LCSP", re.I), "Normativa"),
    (re.compile(r"\bDOGC\b", re.I), "Normativa"),
]
def cross(news, snap):
    open_orgs={}
    for r in (snap.get("open",[])+snap.get("openLocal",[])):
        o=(r.get("organ") or "")
        for rx,tag in ORG_TAGS:
            if rx.search(o): open_orgs[tag]=open_orgs.get(tag,0)+1
    for it in news:
        tags=[]
        blob=it["t"]+" "+it.get("sum","")+" "+it.get("src","")
        for rx,tag in ORG_TAGS:
            if rx.search(blob) and tag not in tags: tags.append(tag)
        it["tags"]=tags[:3]
        it["radar"]={t:open_orgs[t] for t in tags if t in open_orgs}  # p.ex. {"CTTI": 3}
    return news

# ------------------------------------------------------------------ ALERTES
SF_MIN="codi_expedient,nom_organ,objecte_contracte,codi_cpv,fase_publicacio,enllac_publicacio,termini_presentacio_ofertes,data_publicacio_anunci,data_publicacio_previ,data_publicacio_futura,data_publicacio_consulta"
LOC=("(upper(nom_organ) like '%AJUNTAMENT%' OR upper(nom_organ) like '%DIPUTACI%' OR "
     "(upper(nom_organ) like '%INSTITUT MUNICIPAL%' AND upper(nom_organ) like '%BARCELONA%' AND (upper(nom_organ) like '%INNOVACI%' OR upper(nom_organ) like '%INFORM%')))")
GEN="nom_ambit like '%Generalitat de Catalunya%'"

def futures():
    out=[]
    for scope,slbl in ((GEN,"Generalitat"),(LOC,"Món local")):
        try:
            rows=soda(SODA, SF_MIN, scope+" AND fase_publicacio in('Anunci previ','Alerta futura','Consulta preliminar del mercat')",
                      order="data_publicacio_anunci DESC", limit=400)
        except Exception as e:
            print("  [futures] salto", slbl, str(e)[:60]); continue
        seen=set()
        for r in rows:
            if not cpv_match(r.get("codi_cpv")): continue
            k=r.get("codi_expedient")
            if not k or k in seen: continue
            seen.add(k)
            dpub=(r.get("data_publicacio_previ") or r.get("data_publicacio_futura") or r.get("data_publicacio_consulta") or r.get("data_publicacio_anunci") or "")[:10]
            # només relativament recents (últims 10 mesos) perquè no s'acumuli història
            if dpub and dpub < (NOW-timedelta(days=300)).strftime("%Y-%m-%d"): continue
            out.append({"exp":k,"organ":txt(r.get("nom_organ")),"objecte":txt(r.get("objecte_contracte"))[:200],
                        "fase":r.get("fase_publicacio"),"bloc":slbl,"dpub":dpub,"url":url_of(r.get("enllac_publicacio"))})
    out.sort(key=lambda x:x.get("dpub") or "", reverse=True)
    return out[:40]

SF_FORM="codi_expedient,nom_organ,objecte_contracte,codi_cpv,durada_contracte,data_formalitzacio_contracte,denominacio_adjudicatari,import_adjudicacio_sense,enllac_publicacio"
RE_RANG=re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*a\s*(\d{2})/(\d{2})/(\d{4})")
RE_MES=re.compile(r"(\d+)\s*mes", re.I); RE_ANY=re.compile(r"(\d+)\s*any", re.I)

def fi_contracte(durada, dform):
    m=RE_RANG.search(durada or "")
    if m:
        try: return datetime(int(m.group(6)),int(m.group(5)),int(m.group(4)),tzinfo=timezone.utc)
        except Exception: pass
    base=None
    if dform:
        try: base=datetime.fromisoformat(dform[:19]).replace(tzinfo=timezone.utc)
        except Exception: base=None
    if base:
        m=RE_MES.search(durada or "")
        if m: return base+timedelta(days=30*int(m.group(1)))
        m=RE_ANY.search(durada or "")
        if m: return base+timedelta(days=365*int(m.group(1)))
    return None

def venciments(mesos=9):
    out=[]
    lim_hi=NOW+timedelta(days=30*mesos)
    for scope,slbl in (("codi_organ='11110'","CTTI"),(GEN,"Generalitat"),(LOC,"Món local")):
        try:
            rows=soda(SODA, SF_FORM, scope+" AND fase_publicacio='Formalització' AND durada_contracte is not null",
                      order="data_publicacio_formalitzacio DESC", limit=1200)
        except Exception as e:
            print("  [venciments] salto", slbl, str(e)[:60]); continue
        seen=set()
        for r in rows:
            if not cpv_match(r.get("codi_cpv")): continue
            k=r.get("codi_expedient")
            if not k or k in seen: continue
            seen.add(k)
            fi=fi_contracte(r.get("durada_contracte"), r.get("data_formalitzacio_contracte"))
            if not fi or fi<NOW or fi>lim_hi: continue
            try: imp=float(r.get("import_adjudicacio_sense"))
            except Exception: imp=None
            out.append({"exp":k,"organ":txt(r.get("nom_organ")),"objecte":txt(r.get("objecte_contracte"))[:200],
                        "bloc":slbl,"fi":fi.strftime("%Y-%m-%d"),
                        "dies":int((fi-NOW).days),
                        "incumbent":txt(r.get("denominacio_adjudicatari")) or None,
                        "import":imp,"durada":(r.get("durada_contracte") or "")[:60],
                        "url":url_of(r.get("enllac_publicacio"))})
    # dedupe entre àmbits (CTTI també és Generalitat)
    ded={}; [ded.setdefault(x["exp"],x) for x in out]
    out=sorted(ded.values(), key=lambda x:x["fi"])
    return out[:50]

def main():
    print("Notícies…")
    news=collect_news()
    snap=load_snapshot()
    news=cross(news, snap)
    print(f"  {len(news)} notícies")
    print("Alertes: futures licitacions…")
    fut=futures(); print(f"  {len(fut)} futures")
    print("Alertes: contractes a punt de vèncer…")
    ven=venciments(); print(f"  {len(ven)} venciments <9 mesos")
    json.dump({"generated":NOW.isoformat(),"items":news}, open(os.path.join(HERE,"noticies.json"),"w",encoding="utf-8"), ensure_ascii=False)
    json.dump({"generated":NOW.isoformat(),"futures":fut,"venciments":ven}, open(os.path.join(HERE,"alertes.json"),"w",encoding="utf-8"), ensure_ascii=False)
    print("escrits noticies.json i alertes.json")

if __name__=="__main__":
    main()
