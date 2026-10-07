"""
Altcoin Tracker - Lot 3 : univers nettoye + historique valide multi-sources.
Bibliotheque standard uniquement (rien a installer).

Nouveautes par rapport au lot 2 :
  - exclusion des tokens de bourses et des produits financiers tokenises
  - 6 sources de prix (Binance, OKX, Gate, KuCoin, MEXC, Bitget) + CoinGecko en dernier recours
  - validation de chaque serie : fraicheur, coherence du prix, jours manquants
  - choix automatique de la meilleure source (la plus longue parmi les valides)

Produit : data/universe.json, data/history/*.csv, data/snapshots/global.csv, data/coverage_report.json
"""
import csv
import glob
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

UA = {"User-Agent": "altcoin-tracker/0.3 (+https://github.com/NalistPro/Altracker)"}
CG_KEY = os.environ.get("COINGECKO_KEY", "").strip()
CG = "https://api.coingecko.com/api/v3"
BIN = "https://data-api.binance.vision/api/v3"
OKX = "https://www.okx.com/api/v5"
GATE = "https://api.gateio.ws/api/v4"
KUC = "https://api.kucoin.com/api/v1"
MEXC = "https://api.mexc.com/api/v3"
BGT = "https://api.bitget.com/api/v2"

ORDRE = ["binance", "okx", "gate", "kucoin", "mexc", "bitget"]
MIN_BON, MIN_LIMITE, ASSEZ_LONG = 365, 180, 1900
ENTETE = ["date", "open", "high", "low", "close", "volume", "quote_volume", "trades"]

os.makedirs("data/history", exist_ok=True)
os.makedirs("data/snapshots", exist_ok=True)
for f in glob.glob("data/history/*.csv"):  # on repart d'une base propre
    os.remove(f)

NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")


# ------------------------------------------------------------------
# Outils
# ------------------------------------------------------------------
def get_json(url, headers=None, retries=3, timeout=30):
    h = dict(UA)
    if headers:
        h.update(headers)
    err, code = None, None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), r.status, None
        except urllib.error.HTTPError as e:
            err, code = f"HTTP {e.code}", e.code
            if e.code == 429:
                time.sleep(20 * (i + 1))
            elif e.code in (400, 403, 404, 451):
                return None, code, err
            else:
                time.sleep(3)
        except Exception as e:
            err, code = f"{type(e).__name__}: {e}", None
            time.sleep(3)
    return None, code, err


def cg(path):
    headers = {"x-cg-demo-api-key": CG_KEY} if CG_KEY else None
    return get_json(CG + path, headers)


def jour(ms):
    return datetime.fromtimestamp(int(float(ms)) / 1000, timezone.utc).strftime("%Y-%m-%d")


def jour_s(sec):
    return datetime.fromtimestamp(int(float(sec)), timezone.utc).strftime("%Y-%m-%d")


def en_lignes(d):
    d.pop(TODAY, None)  # la bougie du jour est incomplete
    return [d[k] for k in sorted(d)]


def ecrire_csv(nom, entete, lignes):
    with open(f"data/history/{nom}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(entete)
        w.writerows(lignes)


# ------------------------------------------------------------------
# 1. Univers
# ------------------------------------------------------------------
MANUEL_IDS = {
    "bitcoin": "BTC/ETH", "ethereum": "BTC/ETH",
    "wrapped-bitcoin": "wrapped", "staked-ether": "staked", "wrapped-steth": "staked",
    "weth": "wrapped", "wrapped-eeth": "staked", "coinbase-wrapped-btc": "wrapped",
    "tether-gold": "or tokenise", "pax-gold": "or tokenise",
}
EXCL_SYMBOLES = {
    "BNB": "token de bourse", "OKB": "token de bourse", "CRO": "token de bourse",
    "LEO": "token de bourse", "KCS": "token de bourse", "GT": "token de bourse",
    "BGB": "token de bourse", "HTX": "token de bourse", "WBT": "token de bourse",
    "FIGR_HELOC": "actif tokenise", "USYC": "actif tokenise", "USDY": "actif tokenise",
    "USTB": "actif tokenise", "BCAP": "actif tokenise", "EURSAFO": "actif tokenise/stable",
}
MOTS = ("wrapped", "staked", "bridged", "restaked", "liquid staking", "stablecoin",
        "tokenized", "tokenised", "treasury", "gold", " usd", "usd ")
CATEGORIES = ["stablecoins", "wrapped-tokens", "liquid-staking-tokens", "bridged-tokens"]

print("=== 1. Univers ===")
markets, code, err = cg("/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
                        "&sparkline=false&price_change_percentage=24h,7d,30d")
if not markets:
    raise SystemExit(f"CoinGecko indisponible ({err}). Arret.")
prix_par_symbole = {c["symbol"].upper(): c["current_price"] for c in markets}

par_categorie = {}
for cat in CATEGORIES:
    time.sleep(4)
    items, c, e = cg(f"/coins/markets?vs_currency=usd&category={cat}&per_page=250&page=1")
    print(f"  categorie {cat}: {len(items) if items else 0} coins ({e or 'ok'})")
    for x in items or []:
        par_categorie[x["id"]] = cat

univers, retires = [], []
for c in markets:
    sym, nom = c["symbol"].upper(), c["name"].lower()
    if c["id"] in MANUEL_IDS:
        raison = MANUEL_IDS[c["id"]]
    elif sym in EXCL_SYMBOLES:
        raison = EXCL_SYMBOLES[sym]
    elif c["id"] in par_categorie:
        raison = par_categorie[c["id"]]
    elif any(m in nom for m in MOTS):
        raison = "nom suspect"
    else:
        raison = None
    if raison:
        retires.append(f"{sym} ({raison})")
        continue
    univers.append({
        "id": c["id"], "symbole": sym, "nom": c["name"], "rang": c["market_cap_rank"],
        "prix": c["current_price"], "cap": c["market_cap"], "volume_24h": c["total_volume"],
        "var_24h": c.get("price_change_percentage_24h_in_currency"),
        "var_7j": c.get("price_change_percentage_7d_in_currency"),
        "var_30j": c.get("price_change_percentage_30d_in_currency"),
        "ath_distance_pct": c.get("ath_change_percentage"),
    })
print(f"  retenus: {len(univers)} | retires: {len(retires)}")

# ------------------------------------------------------------------
# 2. Paires USDT disponibles par bourse
# ------------------------------------------------------------------
print("=== 2. Bourses ===")
PAIRES, ETAT_BOURSES = {}, {}


def lister(nom, url, extraire):
    d, code, e = get_json(url, retries=2)
    try:
        ens = extraire(d) if d is not None else set()
    except Exception as ex:
        ens, e = set(), f"format inattendu ({ex})"
    PAIRES[nom] = ens
    ETAT_BOURSES[nom] = {"paires_usdt": len(ens), "erreur": e}
    print(f"  {nom:8s} {len(ens):5d} paires  {e or 'ok'}")


lister("binance", BIN + "/ticker/price",
       lambda d: {x["symbol"][:-4] for x in d if x["symbol"].endswith("USDT")})
lister("okx", OKX + "/public/instruments?instType=SPOT",
       lambda d: {x["instId"].split("-")[0] for x in d["data"] if x["instId"].endswith("-USDT")})
lister("gate", GATE + "/spot/currency_pairs",
       lambda d: {x["id"].split("_")[0] for x in d if x["id"].endswith("_USDT")
                  and x.get("trade_status") == "tradable"})
lister("kucoin", "https://api.kucoin.com/api/v2/symbols",
       lambda d: {x["symbol"].split("-")[0] for x in d["data"] if x["symbol"].endswith("-USDT")
                  and x.get("enableTrading")})
lister("mexc", MEXC + "/ticker/price",
       lambda d: {x["symbol"][:-4] for x in d if x["symbol"].endswith("USDT")})
lister("bitget", BGT + "/spot/public/symbols",
       lambda d: {x["symbol"][:-4] for x in d["data"] if x["symbol"].endswith("USDT")
                  and x.get("status") == "online"})


# ------------------------------------------------------------------
# 3. Telechargement : une fonction par source (renvoie des lignes triees)
# ------------------------------------------------------------------
def f_binance(sym):
    r, fin = {}, None
    for _ in range(2):
        url = f"{BIN}/klines?symbol={sym}USDT&interval=1d&limit=1000" + (f"&endTime={fin}" if fin else "")
        data, _, _ = get_json(url, retries=2)
        if not isinstance(data, list) or not data:
            break
        for k in data:
            dj = jour(k[0])
            r[dj] = [dj, k[1], k[2], k[3], k[4], k[5], k[7], k[8]]
        if len(data) < 1000:
            break
        fin = data[0][0] - 1
        time.sleep(0.15)
    return en_lignes(r)


def f_okx(sym):
    r, apres = {}, None
    for _ in range(20):
        url = f"{OKX}/market/history-candles?instId={sym}-USDT&bar=1Dutc&limit=100" + (f"&after={apres}" if apres else "")
        data, _, _ = get_json(url, retries=2)
        lst = data.get("data") if isinstance(data, dict) else None
        if not lst:
            break
        for k in lst:
            dj = jour(k[0])
            r[dj] = [dj, k[1], k[2], k[3], k[4], k[5], k[7], ""]
        apres = lst[-1][0]
        if len(lst) < 100:
            break
        time.sleep(0.2)
    return en_lignes(r)


def f_gate(sym):
    r, to = {}, None
    for _ in range(2):
        url = f"{GATE}/spot/candlesticks?currency_pair={sym}_USDT&interval=1d&limit=1000" + (f"&to={to}" if to else "")
        data, _, _ = get_json(url, retries=2)
        if not isinstance(data, list) or not data:
            break
        for k in data:
            dj = jour_s(k[0])
            r[dj] = [dj, k[5], k[3], k[4], k[2], k[6] if len(k) > 6 else "", k[1], ""]
        if len(data) < 1000:
            break
        to = int(float(data[0][0])) - 1
        time.sleep(0.2)
    return en_lignes(r)


def f_kucoin(sym):
    r, fin = {}, int(NOW.timestamp())
    for _ in range(2):
        url = f"{KUC}/market/candles?type=1day&symbol={sym}-USDT&startAt={fin - 1500 * 86400}&endAt={fin}"
        data, _, _ = get_json(url, retries=2)
        lst = data.get("data") if isinstance(data, dict) else None
        if not lst:
            break
        for k in lst:
            dj = jour_s(k[0])
            r[dj] = [dj, k[1], k[3], k[4], k[2], k[5], k[6], ""]
        if len(lst) < 1500:
            break
        fin = int(float(lst[-1][0])) - 1
        time.sleep(0.4)
    return en_lignes(r)


def f_mexc(sym):
    r, fin = {}, None
    for _ in range(4):
        url = f"{MEXC}/klines?symbol={sym}USDT&interval=1d&limit=500" + (f"&endTime={fin}" if fin else "")
        data, _, _ = get_json(url, retries=2)
        if not isinstance(data, list) or not data:
            break
        for k in data:
            dj = jour(k[0])
            r[dj] = [dj, k[1], k[2], k[3], k[4], k[5], k[7], ""]
        if len(data) < 500:
            break
        fin = data[0][0] - 1
        time.sleep(0.2)
    return en_lignes(r)


def f_bitget(sym):
    r, fin = {}, None
    for _ in range(2):
        url = f"{BGT}/spot/market/candles?symbol={sym}USDT&granularity=1Dutc&limit=1000" + (f"&endTime={fin}" if fin else "")
        data, _, _ = get_json(url, retries=2)
        lst = data.get("data") if isinstance(data, dict) else None
        if not lst:
            break
        for k in lst:
            dj = jour(k[0])
            r[dj] = [dj, k[1], k[2], k[3], k[4], k[5], k[6], ""]
        if len(lst) < 1000:
            break
        fin = min(int(k[0]) for k in lst) - 1
        time.sleep(0.2)
    return en_lignes(r)


def f_coingecko(cid):
    """Dernier recours : prix et volume seulement, 365 jours."""
    time.sleep(3)
    data, _, _ = cg(f"/coins/{cid}/market_chart?vs_currency=usd&days=365&interval=daily")
    if not isinstance(data, dict) or not data.get("prices"):
        return []
    vols = {}
    for t, v in data.get("total_volumes", []):
        vols.setdefault(jour(t), v)
    r = {}
    for t, p in data["prices"]:
        # un point a 00:00 UTC du jour J = cloture du jour J-1
        d = (datetime.fromtimestamp(t / 1000, timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        r.setdefault(d, [d, "", "", "", p, "", vols.get(jour(t), ""), ""])
    return en_lignes(r)


FETCH = {"binance": f_binance, "okx": f_okx, "gate": f_gate,
         "kucoin": f_kucoin, "mexc": f_mexc, "bitget": f_bitget}


# ------------------------------------------------------------------
# 4. Validation d'une serie
# ------------------------------------------------------------------
def analyser(lignes, prix_ref):
    if not lignes:
        return {"n": 0, "debut": "-", "fin": "-", "trous": 0, "raison": "vide"}
    d0 = datetime.strptime(lignes[0][0], "%Y-%m-%d").date()
    d1 = datetime.strptime(lignes[-1][0], "%Y-%m-%d").date()
    age = (NOW.date() - d1).days
    etendue = (d1 - d0).days + 1
    trous = etendue - len(lignes)
    raison = None
    if age > 3:
        raison = f"perime (fin {lignes[-1][0]})"
    else:
        try:
            ratio = float(lignes[-1][4]) / float(prix_ref)
            if not (0.75 <= ratio <= 1.33):
                raison = f"prix incoherent (x{ratio:.2f})"
        except Exception:
            pass
        if raison is None and trous / max(etendue, 1) > 0.02:
            raison = f"trop de trous ({trous})"
    return {"n": len(lignes), "debut": lignes[0][0], "fin": lignes[-1][0], "trous": trous, "raison": raison}


def niveau(n):
    return "bon" if n >= MIN_BON else "limite" if n >= MIN_LIMITE else "insuffisant"


# ------------------------------------------------------------------
# 5. Choix de la meilleure source pour chaque coin
# ------------------------------------------------------------------
print("=== 3. Historique des prix ===")
utilises, couverture, echecs = set(), [], []
a_traiter = [(u["symbole"], u["id"], u["prix"], u) for u in univers]
a_traiter += [("BTC", "bitcoin", prix_par_symbole.get("BTC"), None),
              ("ETH", "ethereum", prix_par_symbole.get("ETH"), None)]

for sym, cid, prix, u in a_traiter:
    meilleur, essais = None, []
    for s in ORDRE:
        if sym not in PAIRES.get(s, set()):
            continue
        try:
            lignes = FETCH[s](sym)
        except Exception as ex:
            lignes, essais = [], essais + [f"{s}:erreur {type(ex).__name__}"]
        a = analyser(lignes, prix)
        a["source"], a["lignes"] = s, lignes
        essais.append(f"{s}:{a['raison'] or str(a['n']) + 'j ok'}")
        if a["raison"] is None:
            if meilleur is None or a["n"] > meilleur["n"]:
                meilleur = a
            if a["n"] >= ASSEZ_LONG:
                break
        time.sleep(0.1)

    if meilleur is None and u is not None:  # dernier recours : CoinGecko
        lignes = f_coingecko(cid)
        a = analyser(lignes, prix)
        a["source"], a["lignes"] = "coingecko", lignes
        essais.append(f"coingecko:{a['raison'] or str(a['n']) + 'j ok'}")
        if a["raison"] is None:
            meilleur = a

    ref = "" if u is not None else " (reference)"
    if meilleur:
        nom_fichier = sym if sym not in utilises else f"{sym}_{cid}"
        utilises.add(sym)
        ecrire_csv(nom_fichier, ENTETE, meilleur["lignes"])
        niv = niveau(meilleur["n"])
        if u is not None:
            u.update({"source_prix": meilleur["source"], "jours_historique": meilleur["n"],
                      "niveau": niv, "statut": "ok", "fichier": nom_fichier + ".csv"})
        couverture.append(f"{sym}{ref}|{meilleur['source']}|{meilleur['n']}|{meilleur['debut']}|"
                          f"{meilleur['fin']}|trous:{meilleur['trous']}|{niv}")
        print(f"  {sym:8s} {meilleur['source']:9s} {meilleur['n']:5d} j  {niv}")
    else:
        if u is not None:
            u.update({"source_prix": "aucune", "jours_historique": 0, "niveau": "echec", "statut": "echec"})
            echecs.append(sym)
        couverture.append(f"{sym}{ref}|ECHEC|0|-|-|-|essais: {' ; '.join(essais) or 'aucune paire trouvee'}")
        print(f"  {sym:8s} ECHEC  {' ; '.join(essais) or 'aucune paire'}")

# ------------------------------------------------------------------
# 6. Fear & Greed
# ------------------------------------------------------------------
print("=== 4. Fear & Greed ===")
fg, _, e = get_json("https://api.alternative.me/fng/?limit=0&format=json")
nb_fg = 0
if isinstance(fg, dict) and fg.get("data"):
    lignes = sorted(([jour(int(x["timestamp"]) * 1000), x["value"], x["value_classification"]]
                     for x in fg["data"]), key=lambda r: r[0])
    ecrire_csv("_fear_greed", ["date", "valeur", "classe"], lignes)
    nb_fg = len(lignes)
print(f"  {nb_fg} jours ({e or 'ok'})")

# ------------------------------------------------------------------
# 7. Dominance (instantane quotidien)
# ------------------------------------------------------------------
print("=== 5. Dominance BTC ===")
time.sleep(4)
g, _, e = cg("/global")
chemin = "data/snapshots/global.csv"
if isinstance(g, dict) and g.get("data"):
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
# 8. Sauvegardes et rapport
# ------------------------------------------------------------------
with open("data/universe.json", "w", encoding="utf-8") as f:
    json.dump({"date_utc": NOW.isoformat(), "nb": len(univers), "coins": univers}, f, ensure_ascii=False, indent=1)

niv = [u["niveau"] for u in univers]
sources = {}
for u in univers:
    sources[u["source_prix"]] = sources.get(u["source_prix"], 0) + 1
rapport = {
    "date_utc": NOW.isoformat(),
    "resume": {
        "coins_dans_l_univers": len(univers),
        "historique_bon_365j+": niv.count("bon"),
        "historique_limite_180-364j": niv.count("limite"),
        "historique_insuffisant_<180j": niv.count("insuffisant"),
        "echecs": echecs,
        "coins_par_source": sources,
        "bourses": ETAT_BOURSES,
        "fear_greed_jours": nb_fg,
    },
    "retires": retires,
    "couverture(symbole|source|jours|debut|fin|trous|niveau)": couverture,
}
with open("data/coverage_report.json", "w", encoding="utf-8") as f:
    json.dump(rapport, f, ensure_ascii=False, indent=1)
print("\nTermine. Rapport : data/coverage_report.json")
