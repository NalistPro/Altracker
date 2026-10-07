"""
Altcoin Tracker - Lot 5 : instantane horaire des prix (top 100).
Ecrit un fichier JSON leger, publie ensuite sur la branche 'live' (historique ecrase a chaque fois).
Un seul appel a CoinGecko pour les prix + un pour la dominance.
Usage : python scripts/live_snapshot.py /chemin/live.json
"""
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
SORTIE = sys.argv[1] if len(sys.argv) > 1 else "live.json"


def cg(path, retries=3):
    h = dict(UA)
    if CG_KEY:
        h["x-cg-demo-api-key"] = CG_KEY
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(CG + path, headers=h), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):
                return None
            time.sleep(15 * (i + 1) if e.code == 429 else 3)
        except Exception:
            time.sleep(3)
    return None


def main():
    marches = cg("/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
                 "&sparkline=false&price_change_percentage=1h,24h,7d")
    if not isinstance(marches, list) or len(marches) < 50:
        sys.exit("ECHEC : CoinGecko n'a pas renvoye la liste des prix.")
    time.sleep(3)
    g = cg("/global")
    gd = g.get("data", {}) if isinstance(g, dict) else {}
    out = {
        "mis_a_jour_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dominance_btc": (gd.get("market_cap_percentage") or {}).get("btc"),
        "cap_totale_usd": (gd.get("total_market_cap") or {}).get("usd"),
        "coins": [{"symbole": c["symbol"].upper(), "nom": c["name"], "rang": c["market_cap_rank"],
                   "prix": c["current_price"], "var_1h": c.get("price_change_percentage_1h_in_currency"),
                   "var_24h": c.get("price_change_percentage_24h_in_currency"),
                   "var_7j": c.get("price_change_percentage_7d_in_currency"),
                   "volume_24h": c["total_volume"], "cap": c["market_cap"]} for c in marches],
    }
    with open(SORTIE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out['coins'])} coins ecrits dans {SORTIE}")


if __name__ == "__main__":
    main()
