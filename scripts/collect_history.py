"""
Altcoin Tracker - Lot 2 : univers renforce + historique des prix.
Bibliotheque standard uniquement (rien a installer).

Produit :
  data/universe.json            univers final (avec source de prix et nb de jours)
  data/history/<SYMBOLE>.csv    bougies journalieres par coin (+ BTC et ETH)
  data/history/_fear_greed.csv  historique du Fear & Greed
  data/snapshots/global.csv     dominance BTC/ETH (1 ligne par jour, a partir d'aujourd'hui)
  data/coverage_report.json     rapport de couverture
"""
import csv
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

UA = {"User-Agent": "altcoin-tracker/0.2 (+https://github.com/NalistPro/Altracker)"}
CG_KEY = os.environ.get("COINGECKO_KEY", "").strip()
CG = "https://api.coingecko.com/api/v3"
BIN = "https://data-api.binance.vision/api/v3"
OKX = "https://www.okx.com/api/v5"

MIN_BON, MIN_LIMITE = 365, 180  # jours d'historique : bon / limite / insuffisant
ENTETE = ["date", "open", "high", "low", "close", "volume", "quote_volume", "trades"]

os.makedirs("data/history", exist_ok=True)
os.makedirs("data/snapshots", exist_ok=True)
NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")


def get_json(url, headers=None, retries=3, timeout=30):
    h = dict(UA)
    if headers:
        h.update(headers)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), r.status, None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (i + 1))
            elif e.code in (403, 451, 400, 404):
                return None, e.code, f"HTTP {e.code}"
            else:
                time.sleep(3)
            err, code = f"HTTP {e.code}", e.code
        except Exception as e:
            err, code = f"{type(e).__name__}: {e}", None
            time.sleep(3)
    return None, code, err


def cg(path):
    headers = {"x-cg-demo-api-key": CG_KEY} if CG_KEY else None
    return get_json(CG + path, headers)


def jour(ms):
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------
# 1. Univers renforce
# ------------------------------------------------------------------
MANUEL = {
    "bitcoin": "BTC/ETH", "ethereum": "BTC/ETH",
    "wrapped-bitcoin": "wrapped", "staked-ether": "staked", "wrapped-steth": "staked",
    "weth": "wrapped", "wrapped-eeth": "staked", "coinbase-wrapped-btc": "wrapped",
    "tether-gold": "or tokenise", "pax-gold": "or tokenise",
}
MOTS = ("wrapped", "staked", "bridged", "restaked", "liquid staking", "stablecoin",
        "tokenized", "tokenised", "treasury", "gold", " usd", "usd ")
CATEGORIES = ["stablecoins", "wrapped-tokens", "liquid-staking-tokens", "bridged-tokens"]

print("=== 1. Univers ===")
markets, code, err = cg("/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
                        "&sparkline=false&price_change_percentage=24h,7d,30d")
if not markets:
    raise SystemExit(f"CoinGecko indisponible ({err}). Arret.")

par_categorie = {}
for cat in CATEGORIES:
    time.sleep(4)  # 30 appels/minute max
    items, c, e = cg(f"/coins/markets?vs_currency=usd&category={cat}&per_page=250&page=1")
    n = len(items) if items else 0
    print(f"  categorie {cat}: {n} coins ({e or 'ok'})")
    for x in items or []:
        par_categorie[x["id"]] = cat

univers, retires = [], []
for c in markets:
    nom = c["name"].lower()
    if c["id"] in MANUEL:
        raison = MANUEL[c["id"]]
    elif c["id"] in par_categorie:
        raison = par_categorie[c["id"]]
    elif any(m in nom for m in MOTS):
        raison = "nom suspect"
    else:
        raison = None
    if raison:
        retires.append(f"{c['symbol'].upper()} ({raison})")
        continue
    univers.append({
        "id": c["id"], "symbole": c["symbol"].upper(), "nom": c["name"],
        "rang": c["market_cap_rank"], "prix": c["current_price"], "cap": c["market_cap"],
        "volume_24h": c["total_volume"],
        "var_24h": c.get("price_change_percentage_24h_in_currency"),
        "var_7j": c.get("price_change_percentage_7d_in_currency"),
        "var_30j": c.get("price_change_percentage_30d_in_currency"),
        "ath_distance_pct": c.get("ath_change_percentage"),
    })
print(f"  retenus: {len(univers)} | retires: {len(retires)}")

# ------------------------------------------------------------------
# 2. Paires disponibles sur Binance / OKX
# ------------------------------------------------------------------
print("=== 2. Paires USDT ===")
d, _, e = get_json(BIN + "/ticker/price")
paires_bin = {x["symbol"] for x in d if x["symbol"].endswith("USDT")} if d else set()
d, _, e2 = get_json(OKX + "/public/instruments?instType=SPOT")
paires_okx = {x["instId"] for x in d.get("data", [])} if d else set()
print(f"  Binance: {len(paires_bin)} paires ({e or 'ok'}) | OKX: {len(paires_okx)} paires ({e2 or 'ok'})")


# ------------------------------------------------------------------
# 3. Telechargement de l'historique
# ------------------------------------------------------------------
def fetch_binance(sym):
    lignes, fin = {}, None
    for _ in range(2):  # 2 pages de 1000 jours max (~5,5 ans)
        url = f"{BIN}/klines?symbol={sym}USDT&interval=1d&limit=1000" + (f"&endTime={fin}" if fin else "")
        data, _, _ = get_json(url)
        if not data:
            break
        for k in data:
            dj = jour(k[0])
            lignes[dj] = [dj, k[1], k[2], k[3], k[4], k[5], k[7], k[8]]
        if len(data) < 1000:
            break
        fin = data[0][0] - 1
        time.sleep(0.15)
    lignes.pop(TODAY, None)  # bougie du jour incomplete : on l'ecarte
    return [lignes[k] for k in sorted(lignes)]


def fetch_okx(sym):
    lignes, apres = {}, None
    for _ in range(14):  # jusqu'a ~1400 jours
        url = f"{OKX}/market/history-candles?instId={sym}-USDT&bar=1Dutc&limit=100" + (f"&after={apres}" if apres else "")
        data, _, _ = get_json(url)
        lst = data.get("data") if data else None
        if not lst:
            break
        for k in lst:
            dj = jour(k[0])
            lignes[dj] = [dj, k[1], k[2], k[3], k[4], k[5], k[7], ""]
        apres = lst[-1][0]
        if len(lst) < 100:
            break
        time.sleep(0.3)
    lignes.pop(TODAY, None)
    return [lignes[k] for k in sorted(lignes)]


def ecrire_csv(nom, entete, lignes):
    with open(f"data/history/{nom}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(entete)
        w.writerows(lignes)


print("=== 3. Historique des prix ===")
utilises, couverture = set(), []
a_telecharger = [(u["symbole"], u) for u in univers]
a_telecharger += [("BTC", None), ("ETH", None)]  # references de marche

for sym, u in a_telecharger:
    source, lignes = "aucune", []
    if f"{sym}USDT" in paires_bin:
        lignes, source = fetch_binance(sym), "binance"
    if not lignes and f"{sym}-USDT" in paires_okx:
        lignes, source = fetch_okx(sym), "okx"
    if not lignes:
        source = "aucune"
    nom_fichier = sym if sym not in utilises else f"{sym}_{u['id']}"
    utilises.add(sym)
    if lignes:
        ecrire_csv(nom_fichier, ENTETE, lignes)
    n = len(lignes)
    niveau = "bon" if n >= MIN_BON else "limite" if n >= MIN_LIMITE else "insuffisant"
    if u is not None:
        u["source_prix"], u["jours_historique"], u["niveau"] = source, n, niveau
    ref = "" if u is not None else " (reference)"
    couverture.append(f"{sym}{ref}|{source}|{n}|{lignes[0][0] if lignes else '-'}|{niveau}")
    print(f"  {sym:8s} {source:8s} {n:5d} jours  {niveau}")
    time.sleep(0.1)

# ------------------------------------------------------------------
# 4. Fear & Greed (historique complet)
# ------------------------------------------------------------------
print("=== 4. Fear & Greed ===")
fg, _, e = get_json("https://api.alternative.me/fng/?limit=0&format=json")
nb_fg = 0
if fg and fg.get("data"):
    lignes = sorted(
        ([jour(int(x["timestamp"]) * 1000), x["value"], x["value_classification"]] for x in fg["data"]),
        key=lambda r: r[0])
    ecrire_csv("_fear_greed", ["date", "valeur", "classe"], lignes)
    nb_fg = len(lignes)
print(f"  {nb_fg} jours ({e or 'ok'})")

# ------------------------------------------------------------------
# 5. Instantane global (dominance) : on commence a l'enregistrer des aujourd'hui
# ------------------------------------------------------------------
print("=== 5. Dominance BTC (instantane) ===")
time.sleep(4)
g, _, e = cg("/global")
chemin = "data/snapshots/global.csv"
if g and g.get("data"):
    gd = g["data"]
    deja = os.path.exists(chemin) and TODAY in open(chemin, encoding="utf-8").read()
    if not deja:
        nouveau = not os.path.exists(chemin)
        with open(chemin, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if nouveau:
                w.writerow(["date", "btc_dominance", "eth_dominance", "cap_totale_usd", "var_cap_24h"])
            w.writerow([TODAY, gd["market_cap_percentage"].get("btc"), gd["market_cap_percentage"].get("eth"),
                        gd["total_market_cap"].get("usd"), gd.get("market_cap_change_percentage_24h_usd")])
    print(f"  dominance BTC: {gd['market_cap_percentage'].get('btc'):.1f} %")
else:
    print(f"  indisponible ({e})")

# ------------------------------------------------------------------
# 6. Sauvegardes et rapport
# ------------------------------------------------------------------
with open("data/universe.json", "w", encoding="utf-8") as f:
    json.dump({"date_utc": NOW.isoformat(), "nb": len(univers), "coins": univers}, f, ensure_ascii=False, indent=1)

niveaux = [u["niveau"] for u in univers]
rapport = {
    "date_utc": NOW.isoformat(),
    "resume": {
        "coins_retenus": len(univers),
        "historique_bon_365j+": niveaux.count("bon"),
        "historique_limite_180-364j": niveaux.count("limite"),
        "historique_insuffisant_<180j": niveaux.count("insuffisant"),
        "sans_donnees_de_prix": [u["symbole"] for u in univers if u["source_prix"] == "aucune"],
        "paires_binance": len(paires_bin), "paires_okx": len(paires_okx),
        "fear_greed_jours": nb_fg,
    },
    "retires": retires,
    "couverture(symbole|source|jours|debut|niveau)": couverture,
}
with open("data/coverage_report.json", "w", encoding="utf-8") as f:
    json.dump(rapport, f, ensure_ascii=False, indent=1)
print("\nTermine. Rapport : data/coverage_report.json")
