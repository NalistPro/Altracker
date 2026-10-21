#!/usr/bin/env python3
"""Prépare un BROUILLON de newsletter (jamais envoyé automatiquement).
- "opportunite" : toutes les conditions sont réunies (et 7 jours depuis la dernière)
- "quinzaine"   : bilan régulier si 15 jours sans brouillon
Usage : python scripts/newsletter_draft.py data [--force opportunite|quinzaine]
Écrit newsletter/drafts/AAAA-MM-JJ-type.md ; affiche NOUVEAU_BROUILLON=chemin si créé."""
import json, os, random, re, sys
from datetime import date

D = sys.argv[1] if len(sys.argv) > 1 else "data"
FORCE = sys.argv[sys.argv.index("--force") + 1] if "--force" in sys.argv else None
rj = lambda p, d=None: (json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d)
sc, det, mk = rj(f"{D}/model/latest_scores.json"), rj(f"{D}/model/detail.json", {}), rj(f"{D}/model/market.json", {})
tr, st = rj(f"{D}/track/track.json", {}), rj(f"{D}/newsletter/state.json", {})
today = date.fromisoformat(sc["date_donnees"]); rnd = random.Random(sc["date_donnees"])
by = {c["symbole"]: c for c in sc["classement"]}
top = [by[s] for s in sc["top5"] if s in by]; c = top[0]; sym = c["symbole"]
d = (det.get("coins") or {}).get(sym, {}); cl = d.get("c", []); ind = d.get("i", {})
prof = tr.get("profil", {"objectif": 12, "stop": -8, "horizon": 20, "nom": "Père de famille"})
fng = (mk.get("fng") or {}).get("valeur"); alt = (mk.get("alt") or {}).get("valeur"); vol = (mk.get("volbtc") or {}).get("valeur")
note = (tr.get("score") or {}).get("valeur")
sma = lambda n: sum(cl[-n:]) / n
haussier = len(cl) >= 50 and cl[-1] > sma(20) > sma(50)
rsi = ind.get("rsi14")
conds = [
    ("coin liquide", c.get("liquide", False)), ("score >= 85", c["score"] >= 85),
    ("tendance haussière", haussier), ("RSI < 70", rsi is not None and rsi < 70),
    ("Fear & Greed < 75", fng is not None and fng < 75), ("volatilité BTC < 60", vol is not None and vol < 60),
    ("note de fiabilité >= 40 (ou pas encore mesurée)", note is None or note >= 40)]
ok = all(v for _, v in conds)
since = lambda k: (today - date.fromisoformat(st[k])).days if st.get(k) else 999
kind = FORCE or ("opportunite" if ok and since("opportunite") >= 7 else "quinzaine" if since("brouillon") >= 15 else None)
if not kind: print("Aucun brouillon aujourd'hui."); sys.exit(0)

def px(p): return f"${p:,.0f}".replace(",", " ") if p >= 100 else f"${p:,.2f}" if p >= 1 else f"${p:.4f}"
LAB = {"trend": "la tendance", "risk": "le profil de volatilité", "highs": "la distance aux plus hauts", "vol": "le volume et la liquidité",
       "rsi": "le RSI", "mkt": "le contexte de marché", "btc": "son lien avec BTC"}
pos = [LAB.get(k, k) for k, v in sorted(d.get("e", []), key=lambda x: -x[1]) if v > 0][:3]
humeur = ("peur extrême" if fng < 25 else "peur" if fng < 45 else "neutre" if fng < 56 else "avidité" if fng < 75 else "euphorie") if fng is not None else "n/a"
saison = "saison des alts" if (alt or 0) >= 75 else "saison BTC" if (alt or 100) <= 25 else "zone intermédiaire"
fiab = (f"La note de fiabilité de l'outil est aujourd'hui de **{note}/100** ({'provisoire, peu de lots terminés' if tr['score']['provisoire'] else 'sur '+str(tr['score']['lots'])+' lots terminés'}). Elle compare mes prévisions passées à ce qui s'est réellement produit."
        if note is not None else f"La note de fiabilité réelle n'est pas encore calculée (première mesure le {(tr.get('score') or {}).get('premiere_mesure', 'bientôt')}). En attendant, le test sur le passé donne un modèle qui bat l'univers dans {(tr.get('reference') or {}).get('bat_univers_pct', '?')} % des périodes : un avantage modeste, qui n'a rien d'une garantie.")
ouv = rnd.choice(["Bonjour à tous,", "Salut tout le monde,", "Bonjour,"])
fin = rnd.choice(["Prends soin de toi et à très vite,", "Je reste attentif et je te tiens au courant,", "À bientôt,"])
DISC = ("*Ce message est informatif. Les niveaux indiqués sont des niveaux de référence issus d'un modèle statistique, pas un conseil en investissement ni une recommandation personnalisée. "
        "Les crypto-actifs sont très volatils et tu peux perdre tout ou partie de ta mise. Les performances passées ne garantissent pas les résultats futurs. Décide toujours par toi-même.*")
L = []
if kind == "opportunite":
    e1, e2 = c["prix"] * .98, c["prix"] * 1.01
    obj, stp = c["prix"] * (1 + prof["objectif"] / 100), c["prix"] * (1 + prof["stop"] / 100)
    L += [f"# Objet : {sym} : toutes les conditions sont réunies", "", ouv, "",
      f"Je t'écris parce que, pour une fois, toutes les conditions que je me suis fixées sont réunies en même temps. Le modèle place **{c['nom']} ({sym})** en tête avec un score de **{c['score']}/100**, une tendance haussière confirmée et un RSI de {rsi:.0f}, donc sans signe de surchauffe.", "",
      f"Ce qui le porte surtout : {', '.join(pos)}." if pos else "",
      f"Côté marché : Fear & Greed à {fng} ({humeur}), {saison}, volatilité de BTC à {vol:.0f} %.", "",
      f"## Niveaux de référence (profil « {prof['nom']} », horizon {prof['horizon']} jours)", "",
      f"- **Zone d'observation d'entrée** : entre {px(e1)} et {px(e2)}", f"- **Niveau de référence haut** : {px(obj)} (+{prof['objectif']} %)",
      f"- **Seuil de sortie de prudence** : {px(stp)} ({prof['stop']} %)", "",
      "Ce sont des repères pour réfléchir, pas des ordres. Un altcoin peut perdre 30 % en quelques jours : n'y mets que ce que tu peux te permettre de perdre.", "",
      fiab, "", fin, "", "— Altracker", "", DISC]
else:
    lots = (tr.get("lots") or [])[:5]
    L += [f"# Objet : Le point de la quinzaine ({today.strftime('%d/%m')})", "", ouv, "",
      "Pas d'opportunité exceptionnelle à signaler, mais voici le point régulier.", "", "## Le Top 5 du moment", ""]
    L += [f"- **{x['symbole']}** ({x['nom']}) : score {x['score']}/100, {px(x['prix'])}, {x['ret7_%']:+.1f} % sur 7 jours" for x in top]
    L += ["", f"Humeur du marché : Fear & Greed à {fng} ({humeur}), {saison}.", "", "## Fiabilité de l'outil", "", fiab, ""]
    if lots: L += ["Derniers lots suivis : " + " ; ".join(f"{l['date'][5:]} → {l['ret']:+.1f} % (BTC {l['btc']:+.1f} %)" for l in lots) + ".", ""]
    L += [fin, "", "— Altracker", "", DISC]
L += ["", "[Me désinscrire]({{DESINSCRIPTION}})", "",
      "<!-- CONDITIONS : " + " | ".join(f"{k}={'OK' if v else 'NON'}" for k, v in conds) + " -->"]
os.makedirs("newsletter/drafts", exist_ok=True); os.makedirs(f"{D}/newsletter", exist_ok=True)
path = f"newsletter/drafts/{today.isoformat()}-{kind}.md"
txt = "\n".join(x for x in L if x is not None) + "\n"
txt = re.sub(r"(?<=\d)\.(?=\d)", ",", txt)   # décimales à la française
open(path, "w", encoding="utf-8").write(txt)
st["brouillon"] = today.isoformat()
if kind == "opportunite": st["opportunite"] = today.isoformat()
json.dump(st, open(f"{D}/newsletter/state.json", "w"), indent=1)
print("NOUVEAU_BROUILLON=" + path); print("conditions:", {k: v for k, v in conds})
