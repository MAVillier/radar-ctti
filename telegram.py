#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram.py — Notificació diària amb: noves licitacions (+dies restants),
terminis que s'acaben, futures licitacions noves, nous venciments de contractes
i titulars nous. Manté memòria a state/seen.json per no repetir.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (si falten, s'omet sense error).
     TELEGRAM_DRY=1 -> imprimeix el missatge en lloc d'enviar-lo.
"""
import json, os, re, sys, html, urllib.request, urllib.parse
from datetime import datetime, timezone

HERE=os.path.dirname(os.path.abspath(__file__))
NOW=datetime.now(timezone.utc)
TOKEN=os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
CHAT=os.environ.get("TELEGRAM_CHAT_ID","").strip()
DRY=os.environ.get("TELEGRAM_DRY","")=="1"
DIGEST=os.environ.get("TELEGRAM_DIGEST","")=="1"
URL_APP="https://mavillier.github.io/radar-ctti/"

def load_snapshot():
    h=open(os.path.join(HERE,"index.html"),encoding="utf-8").read()
    m=re.search(r"const SNAPSHOT=(\{.*?\});\n/\* SNAPSHOT:end", h, re.S)
    return json.loads(m.group(1)) if m else {}

def jload(name, default):
    try: return json.load(open(os.path.join(HERE,name),encoding="utf-8"))
    except Exception: return default

def days_left(iso):
    try:
        d=datetime.fromisoformat(iso[:19]).replace(tzinfo=timezone.utc)
        return max(0,(d-NOW).days)
    except Exception: return None

def h(s): return html.escape(str(s or ""), quote=False)
def crop(s,n): s=str(s or ""); return s[:n-1]+"…" if len(s)>n else s

def main():
    snap=load_snapshot()
    news=jload("noticies.json",{}).get("items",[])
    al=jload("alertes.json",{})
    fut=al.get("futures",[]); ven=al.get("venciments",[])
    opens=(snap.get("open",[])+snap.get("openLocal",[]))
    seen_path=os.path.join(HERE,"state","seen.json")
    first=not os.path.exists(seen_path)
    seen=jload(os.path.join("state","seen.json"), {"lic":[],"fut":[],"ven":[],"news":[]})
    S={k:set(v) for k,v in seen.items()}

    def nkey(it): return re.sub(r"\W+","",(it.get("t") or "").lower())[:70]

    new_lic=[r for r in opens if r.get("exp") and r["exp"] not in S["lic"]]
    closing=[r for r in opens if (dl:=days_left(r.get("termini") or "")) is not None and 0<dl<=7]
    new_fut=[f for f in fut if f.get("exp") and f["exp"] not in S["fut"]]
    new_ven=[v for v in ven if v.get("exp") and v["exp"] not in S["ven"] and v.get("dies",999)<=180]
    new_news=[n for n in news if nkey(n) not in S["news"]]

    # actualitza memòria (tot el que hi ha ara queda vist)
    S["lic"]|= {r["exp"] for r in opens if r.get("exp")}
    S["fut"]|= {f["exp"] for f in fut if f.get("exp")}
    S["ven"]|= {v["exp"] for v in ven if v.get("exp")}
    S["news"]|={nkey(n) for n in news}
    os.makedirs(os.path.dirname(seen_path),exist_ok=True)
    json.dump({k:sorted(v)[-1500:] for k,v in S.items()}, open(seen_path,"w",encoding="utf-8"))

    if not first and not DIGEST and not (new_lic or new_fut or new_ven or new_news):
        print("Sense novetats; execució horària silenciosa.")
        return

    d=NOW.strftime("%d/%m/%Y")
    L=[f"<b>📡 Radar TIC — {d}</b>"]
    if first:
        L.append(f"Primera execució. Ara mateix: <b>{len(opens)}</b> licitacions TIC obertes, <b>{len(fut)}</b> anuncis previs i <b>{len(ven)}</b> contractes que vencen en &lt;9 mesos.")
        for r in sorted(closing,key=lambda x:x.get("termini") or "")[:5]:
            L.append(f"⏳ <b>{days_left(r.get('termini'))} d</b> · {h(crop(r.get('organ'),28))} — {h(crop(r.get('objecte'),60))}")
    else:
        if new_lic:
            L.append(f"\n🆕 <b>Noves licitacions ({len(new_lic)})</b>")
            for r in sorted(new_lic,key=lambda x:x.get("termini") or "9999")[:6]:
                dl=days_left(r.get("termini") or ""); dtxt=f"{dl} d" if dl is not None else "—"
                sda=" 🟠SDA" if r.get("sda")=="child" else ""
                L.append(f"• <b>{dtxt}</b>{sda} · {h(crop(r.get('organ'),26))} — {h(crop(r.get('objecte'),58))}")
            if len(new_lic)>6: L.append(f"  …i {len(new_lic)-6} més")
        if closing and DIGEST:
            L.append(f"\n⏳ <b>Tanquen en ≤7 dies ({len(closing)})</b>")
            for r in sorted(closing,key=lambda x:x.get("termini") or "")[:6]:
                L.append(f"• <b>{days_left(r.get('termini'))} d</b> · {h(crop(r.get('organ'),26))} — {h(crop(r.get('objecte'),58))}")
        if new_fut:
            L.append(f"\n🔭 <b>A punt de sortir ({len(new_fut)})</b>")
            for f in new_fut[:4]:
                L.append(f"• {h(f.get('fase'))} · {h(crop(f.get('organ'),26))} — {h(crop(f.get('objecte'),56))}")
        if new_ven:
            L.append(f"\n⚠️ <b>Contractes que s'acaben ({len(new_ven)})</b>")
            for v in new_ven[:5]:
                fi=datetime.fromisoformat(v["fi"]).strftime("%d/%m/%y")
                inc=f" · ara: {h(crop(v.get('incumbent'),24))}" if v.get("incumbent") else ""
                L.append(f"• <b>{fi}</b> ({v.get('dies')} d) · {h(crop(v.get('organ'),24))}{inc}")
        if new_news:
            L.append(f"\n📰 <b>Titulars</b>")
            for n in new_news[:5]:
                L.append(f"• <a href=\"{html.escape(n.get('link') or URL_APP)}\">{h(crop(n.get('t'),70))}</a> <i>({h(crop(n.get('src'),20))})</i>")
        if len(L)==1:
            L.append("Sense novetats. Tot tranquil.")
    L.append(f"\n<a href=\"{URL_APP}\">Obrir el Radar</a>")
    msg="\n".join(L)

    if DRY or not (TOKEN and CHAT):
        print(("[DRY-RUN]" if DRY else "[SENSE SECRETS — ometo l'enviament]")+"\n"+msg)
        return
    api=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for chunk_start in range(0,len(msg),3900):
        body=urllib.parse.urlencode({"chat_id":CHAT,"text":msg[chunk_start:chunk_start+3900],
                                     "parse_mode":"HTML","disable_web_page_preview":"true"}).encode()
        req=urllib.request.Request(api,data=body,headers={"Content-Type":"application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req,timeout=30) as r:
            resp=json.loads(r.read().decode())
            if not resp.get("ok"): print("Telegram ERROR:",resp); sys.exit(1)
    print("Telegram: enviat.")

if __name__=="__main__":
    main()
