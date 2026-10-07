"""
Altcoin Tracker - Lot 5 : mise a jour quotidienne incrementale + archivage.
Bibliotheque standard uniquement.

Chaque nuit :
  1. recupere les 15 derniers jours de chaque coin sur SA source (celle choisie par la collecte complete)
  2. controle la coherence avec l'historique existant, puis fusionne
  3. rafraichit le Fear & Greed
  4. archive (au mieux) : dominance BTC, funding rate / open interest, TVL
  5. ecrit data/update_report.json ; sort en erreur si plus de 30 % des coins echouent

(Variable d'environnement ALT_TODAY=AAAA-MM-JJ : uniquement pour les tests.)
"""
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

UA = {"User-Agent": "altcoin-tracker/0.5 (+https://github.com/NalistPro/Altracker)"}
CG_KEY = os.environ.get("COINGECKO_KEY", "").strip()
CG = "https://api.coingecko.com/api/v3"
BIN = "https://data-api.binance.vision/api/v3"
OKX = "https://www.okx.com/api/v5"
GATE = "https://api.gateio.ws/api/v4"
KUC = "https://api.kucoin.com/api/v1"
MEXC = "https://api.mexc.com/api/v3"
BGT = "https://api.bitget.com/api/v2"

DATA = sys.argv[1] if len(sys.argv) > 1 else "data"
ENTETE = ["date", "open", "high", "low", "close", "volume", "quote_volume", "trades"]
N = 15  # jours recuperes a chaque passage (rattrape aussi un oubli de quelques jours)
SEUIL_ECHEC = 0.30
MAX_AGE = 2  # une serie dont la derniere bougie a plus de 2 jours est consideree perimee

NOW = datetime.now(timezone.utc)
TODAY = os.environ.get("ALT_TODAY") or NOW.strftime("%Y-%m-%d")


def get_json(url, headers=None, retries=3, timeout=30):
    h = dict(UA)
    if headers:
        h.update(headers)
    err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code == 429:
                time.sleep(20 * (i + 1))
            elif e.code in (400, 403, 404, 451):
                return None, err
            else:
                time.sleep(3)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(3)
    return None, err


def cg(path):
    return get_json(CG + path, {"x-cg-demo-api-key": CG_KEY} if CG_KEY else None)


def jour(ms):
    return datetime.fromtimestamp(int(float(ms)) / 1000, timezone.utc).strftime("%Y-%m-%d")


def jour_s(sec):
    return datetime.fromtimestamp(int(float(sec)), timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------
# Recuperation des derniers jours (meme format de lignes que la collecte complete)
# ------------------------------------------------------------------
def r_binance(sym, n=N):
    d, _ = get_json(f"{BIN}/klines?symbol={sym}USDT&interval=1d&limit={n}", retries=2)
    return {jour(k[0]): [jour(k[0]), k[1], k[2], k[3], k[4], k[5], k[7], k[8]] for k in d} if isinstance(d, list) else {}


def r_okx(sym, n=N):
    d, _ = get_json(f"{OKX}/market/history-candles?instId={sym}-USDT&bar=1Dutc&limit={n}", retries=2)
    lst = d.get("data") if isinstance(d, dict) else None
    return {jour(k[0]): [jour(k[0]), k[1], k[2], k[3], k[4], k[5], k[7], ""] for k in lst} if lst else {}


def r_gate(sym, n=N):
    d, _ = get_json(f"{GATE}/spot/candlesticks?currency_pair={sym}_USDT&interval=1d&limit={n}", retries=2)
    return {jour_s(k[0]): [jour_s(k[0]), k[5], k[3], k[4], k[2], k[6] if len(k) > 6 else "", k[1], ""]
            for k in d} if isinstance(d, list) else {}


def r_kucoin(sym, n=N):
    fin = int(NOW.timestamp())
    d, _ = get_json(f"{KUC}/market/candles?type=1day&symbol={sym}-USDT&startAt={fin - (n + 1) * 86400}&endAt={fin}", retries=2)
    lst = d.get("data") if isinstance(d, dict) else None
    return {jour_s(k[0]): [jour_s(k[0]), k[1], k[3], k[4], k[2], k[5], k[6], ""] for k in lst} if lst else {}


def r_mexc(sym, n=N):
    d, _ = get_json(f"{MEXC}/klines?symbol={sym}USDT&interval=1d&limit={n}", retries=2)
    return {jour(k[0]): [jour(k[0]), k[1], k[2], k[3], k[4], k[5], k[7], ""] for k in d} if isinstance(d, list) else {}


def r_bitget(sym, n=N):
    d, _ = get_json(f"{BGT}/spot/market/candles?symbol={sym}USDT&granularity=1Dutc&limit={n}", retries=2)
    lst = d.get("data") if isinstance(d, dict) else None
    return {jour(k[0]): [jour(k[0]), k[1], k[2], k[3], k[4], k[5], k[6], ""] for k in lst} if lst else {}


FETCH = {"binance": r_binance, "okx": r_okx, "gate": r_gate,
         "kucoin": r_kucoin, "mexc": r_mexc, "bitget": r_bitget}


# ------------------------------------------------------------------
# Fichiers
# ------------------------------------------------------------------
def lire_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[1:] if rows else []


def ecrire_csv(path, entete, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(entete)
        w.writerows(rows)


def ecart_median(anciennes, nouvelles):
    """Ecart relatif median entre clotures communes (None si moins de 3 jours en commun)."""
    try:
        old = {r[0]: float(r[4]) for r in anciennes}
        e = sorted(abs(float(r[4]) / old[r[0]] - 1) for r in nouvelles if r[0] in old and old[r[0]] > 0)
        return e[len(e) // 2] if len(e) >= 3 else None
    except Exception:
        return None


def mettre_a_jour_coin(sym, fichier, source):
    chemin = os.path.join(DATA, "history", fichier)
    if source not in FETCH:
        return {"statut": "ignore", "detail": f"source '{source}' : traitee par la reconstruction hebdomadaire"}
    if not os.path.exists(chemin):
        return {"statut": "echec", "detail": "fichier introuvable"}
    anciennes = lire_csv(chemin)
    recues = {d: r for d, r in FETCH[source](sym).items() if d < TODAY}
    if not recues:
        return {"statut": "echec", "detail": f"aucune donnee recue de {source}"}
    ecart = ecart_median(anciennes, list(recues.values()))
    if ecart is not None and ecart > 0.03:
        return {"statut": "discordance", "detail": f"ecart {ecart:.1%} avec l'historique ({source})"}
    fusion = {r[0]: r for r in anciennes}
    nouveaux = sum(1 for d in recues if d not in fusion)
    fusion.update(recues)
    rows = [fusion[d] for d in sorted(fusion)]
    ecrire_csv(chemin, ENTETE, rows)
    derniere = rows[-1][0]
    age = (datetime.strptime(TODAY, "%Y-%m-%d") - datetime.strptime(derniere, "%Y-%m-%d")).days
    return {"statut": "ok" if age <= MAX_AGE else "perime", "derniere_date": derniere,
            "nouveaux_jours": nouveaux, "detail": "" if age <= MAX_AGE else f"derniere bougie {derniere}"}


# ------------------------------------------------------------------
# Archivage (au mieux : une erreur ici ne bloque jamais la mise a jour des prix)
# ------------------------------------------------------------------
def deja_ecrit(chemin):
    return os.path.exists(chemin) and any(l.startswith(TODAY) for l in open(chemin, encoding="utf-8"))


def ajouter(chemin, entete, lignes):
    nouveau = not os.path.exists(chemin)
    with open(chemin, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nouveau:
            w.writerow(entete)
        w.writerows(lignes)


def archiver(symboles):
    res = {}
    snap = os.path.join(DATA, "snapshots")
    os.makedirs(snap, exist_ok=True)

    # a) dominance BTC / capitalisation totale
    try:
        chemin = os.path.join(snap, "global.csv")
        if deja_ecrit(chemin):
            res["global"] = "deja fait aujourd'hui"
        else:
            g, e = cg("/global")
            gd = g["data"]
            ajouter(chemin, ["date", "btc_dominance", "eth_dominance", "cap_totale_usd", "var_cap_24h"],
                    [[TODAY, gd["market_cap_percentage"].get("btc"), gd["market_cap_percentage"].get("eth"),
                      gd["total_market_cap"].get("usd"), gd.get("market_cap_change_percentage_24h_usd")]])
            res["global"] = "ok"
    except Exception as ex:
        res["global"] = f"erreur : {type(ex).__name__} {ex}"

    # b) funding rate et open interest (contrats perpetuels Gate.io, un seul appel)
    try:
        chemin = os.path.join(snap, "derivs.csv")
        if deja_ecrit(chemin):
            res["derives"] = "deja fait aujourd'hui"
        else:
            d, e = get_json(GATE + "/futures/usdt/contracts", retries=2)
            if not isinstance(d, list):
                raise RuntimeError(e or "reponse inattendue")
            lignes = []
            for c in d:
                sym = str(c.get("name", "")).split("_")[0]
                if sym in symboles:
                    try:
                        oi = abs(float(c["position_size"])) * float(c["quanto_multiplier"]) * float(c["mark_price"])
                    except Exception:
                        oi = ""
                    lignes.append([TODAY, sym, c.get("funding_rate", ""), oi, "gate"])
            ajouter(chemin, ["date", "symbole", "funding_rate", "open_interest_usd", "source"], lignes)
            res["derives"] = f"ok ({len(lignes)} coins)"
    except Exception as ex:
        res["derives"] = f"erreur : {type(ex).__name__} {ex}"

    # c) TVL des protocoles (DefiLlama, un seul appel)
    try:
        chemin = os.path.join(snap, "tvl.csv")
        if deja_ecrit(chemin):
            res["tvl"] = "deja fait aujourd'hui"
        else:
            d, e = get_json("https://api.llama.fi/protocols", retries=2, timeout=60)
            if not isinstance(d, list):
                raise RuntimeError(e or "reponse inattendue")
            tvl = {}
            for p in d:
                s = str(p.get("symbol", "")).upper()
                if s in symboles and p.get("tvl"):
                    tvl[s] = tvl.get(s, 0) + float(p["tvl"])
            ajouter(chemin, ["date", "symbole", "tvl_usd"], [[TODAY, s, round(v)] for s, v in sorted(tvl.items())])
            res["tvl"] = f"ok ({len(tvl)} coins)"
    except Exception as ex:
        res["tvl"] = f"erreur : {type(ex).__name__} {ex}"
    return res


# ------------------------------------------------------------------
def main():
    univers = json.load(open(os.path.join(DATA, "universe.json"), encoding="utf-8"))["coins"]
    a_faire = [(u["symbole"], u["fichier"], u["source_prix"]) for u in univers if u.get("statut") == "ok"]
    a_faire += [("BTC", "BTC.csv", "binance"), ("ETH", "ETH.csv", "binance")]

    detail, compte = {}, {}
    for sym, fichier, source in a_faire:
        try:
            r = mettre_a_jour_coin(sym, fichier, source)
        except Exception as ex:
            r = {"statut": "echec", "detail": f"{type(ex).__name__}: {ex}"}
        detail[sym] = r
        compte[r["statut"]] = compte.get(r["statut"], 0) + 1
        time.sleep(0.15)
    print("Prix :", compte)

    # Fear & Greed (historique complet, un seul appel)
    fg_res = "non mis a jour"
    d, e = get_json("https://api.alternative.me/fng/?limit=0&format=json")
    if isinstance(d, dict) and d.get("data"):
        rows = sorted(([jour(int(x["timestamp"]) * 1000), x["value"], x["value_classification"]] for x in d["data"]),
                      key=lambda r: r[0])
        ecrire_csv(os.path.join(DATA, "history", "_fear_greed.csv"), ["date", "valeur", "classe"], rows)
        fg_res = f"ok ({len(rows)} jours, derniere {rows[-1][0]})"
    else:
        fg_res = f"erreur : {e}"
    print("Fear & Greed :", fg_res)

    archive = archiver({s for s, _, _ in a_faire})
    print("Archivage :", archive)

    problemes = {s: r for s, r in detail.items() if r["statut"] not in ("ok", "ignore")}
    taux = len(problemes) / max(len(a_faire), 1)
    rapport = {"date_utc": NOW.isoformat(), "jour_traite": TODAY, "coins": len(a_faire), "statuts": compte,
               "taux_echec_%": round(taux * 100, 1), "fear_greed": fg_res, "archivage": archive,
               "problemes": problemes}
    with open(os.path.join(DATA, "update_report.json"), "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=1)
    if taux > SEUIL_ECHEC:
        sys.exit(f"ECHEC : {taux:.0%} des coins n'ont pas pu etre mis a jour (seuil {SEUIL_ECHEC:.0%}).")


if __name__ == "__main__":
    main()
