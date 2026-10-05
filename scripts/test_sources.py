"""
Altcoin Tracker - Lot 1 : test des sources + construction de l'univers.
N'utilise que la bibliotheque standard de Python (rien a installer).
Resultats ecrits dans data/connectivity_report.json et data/universe.json
"""
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

UA = {"User-Agent": "altcoin-tracker/0.1 (+https://github.com/nalistpro/Altracker)"}
CG_KEY = os.environ.get("COINGECKO_KEY", "").strip()
CG = "https://api.coingecko.com/api/v3"

os.makedirs("data", exist_ok=True)
report = {"date_utc": datetime.now(timezone.utc).isoformat(), "tests": {}}


def get_json(url, headers=None, retries=3, timeout=25):
    """Appelle une URL, renvoie (donnees, code_http, erreur)."""
    h = dict(UA)
    if headers:
        h.update(headers)
    last_err, code = None, None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), r.status, None
        except urllib.error.HTTPError as e:
            code, last_err = e.code, f"HTTP {e.code}"
            if e.code == 429:
                time.sleep(20 * (i + 1))
            elif e.code in (403, 451):
                break  # blocage : inutile de reessayer
            else:
                time.sleep(3)
        except Exception as e:  # reseau, timeout, JSON invalide
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(3)
    return None, code, last_err


def cg(path):
    headers = {"x-cg-demo-api-key": CG_KEY} if CG_KEY else None
    return get_json(CG + path, headers)


def test(name, url, check, headers=None):
    data, code, err = get_json(url, headers, retries=2)
    ok = data is not None and check(data)
    report["tests"][name] = {"ok": bool(ok), "http": code, "erreur": err}
    print(f"[{'OK ' if ok else 'ECHEC'}] {name} {err or ''}")
    return data


# ---------- 1. Tests de connectivite ----------
test("Binance data-api (prix)", "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=5",
     lambda d: len(d) == 5)
test("Binance api.binance.com (prix)", "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=5",
     lambda d: len(d) == 5)
test("Binance futures (funding rate)", "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=5",
     lambda d: len(d) > 0)
test("Bybit (prix, secours)", "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=D&limit=5",
     lambda d: d.get("retCode") == 0)
test("OKX (prix, secours)", "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=5",
     lambda d: d.get("code") == "0")
test("Fear & Greed (alternative.me)", "https://api.alternative.me/fng/?limit=3",
     lambda d: "data" in d)
test("DefiLlama (TVL)", "https://api.llama.fi/v2/chains", lambda d: len(d) > 10)
test("GitHub API", "https://api.github.com/repos/bitcoin/bitcoin", lambda d: "stargazers_count" in d)

# ---------- 2. Univers : top 100 CoinGecko, sans stables / wrapped / staked / BTC / ETH ----------
print("\n--- Construction de l'univers ---")
markets, code, err = cg("/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
                        "&sparkline=false&price_change_percentage=24h,7d,30d")
report["tests"]["CoinGecko markets"] = {"ok": markets is not None, "http": code, "erreur": err,
                                        "cle_utilisee": bool(CG_KEY)}
print(f"[{'OK ' if markets else 'ECHEC'}] CoinGecko markets {err or ''} (cle: {'oui' if CG_KEY else 'non'})")

if markets:
    exclus_ids = set()
    for cat in ["stablecoins", "wrapped-tokens", "liquid-staking-tokens", "bridged-tokens"]:
        time.sleep(4)  # respecte les 30 appels/minute
        items, c, e = cg(f"/coins/markets?vs_currency=usd&category={cat}&per_page=250&page=1")
        if items:
            exclus_ids |= {x["id"] for x in items}
        print(f"  categorie {cat}: {len(items) if items else 0} coins ({e or 'ok'})")
        report["tests"][f"CoinGecko categorie {cat}"] = {"ok": items is not None, "http": c, "erreur": e}

    MANUEL = {"bitcoin", "ethereum"}
    MOTS = ("wrapped", "staked", "bridged", "usd ", " usd", "stablecoin")
    univers, retires = [], []
    for c in markets:
        nom = c["name"].lower()
        raison = None
        if c["id"] in MANUEL:
            raison = "BTC/ETH"
        elif c["id"] in exclus_ids:
            raison = "categorie exclue"
        elif any(m in nom for m in MOTS):
            raison = "nom suspect"
        if raison:
            retires.append({"id": c["id"], "symbole": c["symbol"], "raison": raison})
        else:
            univers.append({
                "id": c["id"], "symbole": c["symbol"].upper(), "nom": c["name"],
                "rang": c["market_cap_rank"], "prix": c["current_price"],
                "cap": c["market_cap"], "volume_24h": c["total_volume"],
                "var_24h": c.get("price_change_percentage_24h_in_currency"),
                "var_7j": c.get("price_change_percentage_7d_in_currency"),
                "var_30j": c.get("price_change_percentage_30d_in_currency"),
                "ath_distance_pct": c.get("ath_change_percentage"),
            })
    with open("data/universe.json", "w", encoding="utf-8") as f:
        json.dump({"date_utc": report["date_utc"], "nb": len(univers), "coins": univers,
                   "retires": retires}, f, ensure_ascii=False, indent=1)
    print(f"Univers : {len(univers)} coins retenus, {len(retires)} retires")
    report["univers"] = {"retenus": len(univers), "retires": [r["symbole"] for r in retires]}

with open("data/connectivity_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print("\nTermine. Rapport : data/connectivity_report.json")
