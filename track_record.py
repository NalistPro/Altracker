#!/usr/bin/env python3
"""Suivi de fiabilité d'Altracker.
Chaque jour : archive le Top 5 du jour, évalue les "lots" passés (prix à J+20),
calcule la note de fiabilité et son historique -> data/track/track.json
Usage : python scripts/track_record.py data
"""
import csv, json, os, sys
from datetime import date, timedelta

D = sys.argv[1] if len(sys.argv) > 1 else "data"
# Profil d'investisseur (à ajuster librement)
PROFIL = {"nom": "Père de famille", "objectif": 12.0, "stop": -8.0, "horizon": 20}
H = PROFIL["horizon"]
POIDS = (0.4, 0.3, 0.3)   # bat BTC / rendement positif / stop non touché
MIN_LOTS = 10              # en dessous : note "provisoire"
_cache = {}

def rj(p, d=None):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return d

def closes(sym):
    if sym not in _cache:
        out = {}
        try:
            with open(f"{D}/history/{sym}.csv", newline="") as f:
                for r in csv.DictReader(f):
                    out[date.fromisoformat(r["date"])] = float(r["close"])
        except Exception: pass
        _cache[sym] = out
    return _cache[sym]

# 1) archive du jour
os.makedirs(f"{D}/track", exist_ok=True)
log = rj(f"{D}/track/predictions.json", [])
sc = rj(f"{D}/model/latest_scores.json")
if sc and sc["date_donnees"] not in {b["date"] for b in log}:
    by = {c["symbole"]: c for c in sc["classement"]}
    log.append({"date": sc["date_donnees"], "picks": [
        {"symbole": s, "nom": by[s]["nom"], "prix": by[s]["prix"], "score": by[s]["score"]}
        for s in sc["top5"] if s in by]})
log.sort(key=lambda b: b["date"])
json.dump(log, open(f"{D}/track/predictions.json", "w"), ensure_ascii=False, indent=1)

# 2) évaluation
btc = closes("BTC"); last = max(btc) if btc else None
def eval_pick(p, d0):
    s = closes(p["symbole"]); entry = s.get(d0) or p["prix"]; b0 = btc.get(d0)
    first = None; k = 0; r = 0.0; rb = 0.0
    for i in range(1, H + 1):
        di = d0 + timedelta(days=i)
        if di > last: break
        if di in s and entry:
            r = (s[di] / entry - 1) * 100; k = i
            if di in btc and b0: rb = (btc[di] / b0 - 1) * 100
            if first is None:
                if r >= PROFIL["objectif"]: first = "objectif"
                elif r <= PROFIL["stop"]: first = "stop"
    return {"symbole": p["symbole"], "ret": round(r, 2), "btc": round(rb, 2), "premier": first, "jour": k}

lots = []
for b in log:
    d0 = date.fromisoformat(b["date"])
    if last is None or d0 > last: continue
    ps = [eval_pick(p, d0) for p in b["picks"]]
    if not ps: continue
    lots.append({"date": b["date"], "echeance": (d0 + timedelta(days=H)).isoformat(),
                 "mur": d0 + timedelta(days=H) <= last, "picks": ps})

def note(ls):
    ps = [p for l in ls for p in l["picks"]]
    if not ps: return None
    n = len(ps)
    a = 100 * sum(p["ret"] > p["btc"] for p in ps) / n
    pos = 100 * sum(p["ret"] > 0 for p in ps) / n
    prot = 100 * sum(p["premier"] != "stop" for p in ps) / n
    obj = 100 * sum(p["premier"] == "objectif" for p in ps) / n
    return {"valeur": round(POIDS[0]*a + POIDS[1]*pos + POIDS[2]*prot),
            "bat_btc": round(a), "positifs": round(pos), "capital_protege": round(prot),
            "objectif": round(obj), "stop": round(100 - prot), "picks": n}

murs = [l for l in lots if l["mur"]]
serie = []
if murs:
    d = min(date.fromisoformat(l["echeance"]) for l in murs)
    while d <= last:
        n = note([l for l in murs if date.fromisoformat(l["echeance"]) <= d])
        if n: serie.append([d.isoformat(), n["valeur"]])
        d += timedelta(days=1)
cur = note(murs)
prem = min((l["echeance"] for l in lots), default=None)
bt = (rj(f"{D}/model/backtest_report.json", {}) or {})
out = {
    "maj": last.isoformat() if last else None, "profil": PROFIL,
    "score": {"valeur": cur["valeur"] if cur else None, "lots": len(murs),
              "picks": cur["picks"] if cur else 0, "provisoire": len(murs) < MIN_LOTS,
              "premiere_mesure": prem, "poids": POIDS},
    "composantes": cur, "serie": serie[-120:],
    "lots": [{"date": l["date"], "statut": "termine" if l["mur"] else "en_cours",
              "jour": max(p["jour"] for p in l["picks"]),
              "ret": round(sum(p["ret"] for p in l["picks"]) / len(l["picks"]), 2),
              "btc": l["picks"][0]["btc"],
              "objectif": sum(p["premier"] == "objectif" for p in l["picks"]),
              "stop": sum(p["premier"] == "stop" for p in l["picks"]),
              "picks": [p["symbole"] for p in l["picks"]]} for l in lots[-8:][::-1]],
    "reference": {"auc": (bt.get("qualite_prediction") or {}).get("auc"),
                  "bat_univers_pct": bt.get("modele_liquide_bat_l_univers_%_des_periodes")},
}
json.dump(out, open(f"{D}/track/track.json", "w"), ensure_ascii=False, indent=1)
print("lots:", len(lots), "| terminés:", len(murs), "| note:", out["score"]["valeur"])
