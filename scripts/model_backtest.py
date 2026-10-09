"""
Altcoin Tracker - Lot 4 : indicateurs + modele de scoring + backtest walk-forward.

Principe
  * Pour chaque coin et chaque jour, on calcule ~45 indicateurs (momentum, volatilite, volume,
    drawdown, force relative vs BTC, contexte de marche, Fear & Greed, rangs entre coins).
  * Etiquette : le coin finit-il dans les 30 % meilleurs de l'univers sur les 20 jours suivants ?
  * Modele : gradient boosting sobre (HistGradientBoosting), entraine uniquement sur le passe.
  * Backtest walk-forward : on entraine jusqu'a la date T (moins 21 jours de securite),
    on teste sur les 30 jours suivants, puis on avance. Aucune donnee du futur n'est utilisee.

Sorties (dans data/model/)
  backtest_report.json   metriques du backtest
  latest_scores.json     classement actuel des coins
  scores_history.csv     historique des scores quotidiens (sert au test reel de 15 jours)
"""
import json
import os
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")

DATA = sys.argv[1] if len(sys.argv) > 1 else "data"
OUT = os.path.join(DATA, "model")
os.makedirs(OUT, exist_ok=True)

H = 20               # horizon (jours) : milieu de la fourchette swing 15-30 j
GAP = H + 1          # jours de securite entre entrainement et test (evite les fuites)
TOP_Q = 0.70         # etiquette = parmi les 30 % meilleurs
MIN_AGE = 100        # on ignore les 100 premiers jours d'un coin (lancement tres bruite)
TEST_START = "2023-01-01"
TEST_STEP = 30
N_PICK = 5
MIN_VOL_USD = 2_000_000   # volume moyen 30 j minimum (sur la bourse source) pour etre eligible au top 5
COST = 0.004         # 0,4 % par cycle de 20 j (frais + glissement, aller-retour)
PARAMS = dict(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=300,
              l2_regularization=5.0, max_bins=64, random_state=0)


# ------------------------------------------------------------------
# 1. Chargement
# ------------------------------------------------------------------
def lire(path):
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


univers = json.load(open(os.path.join(DATA, "universe.json"), encoding="utf-8"))["coins"]
univers = [u for u in univers if u.get("statut") == "ok"]
series = {u["symbole"]: lire(os.path.join(DATA, "history", u["fichier"])) for u in univers}
noms = {u["symbole"]: u["nom"] for u in univers}
btc = lire(os.path.join(DATA, "history", "BTC.csv"))
eth = lire(os.path.join(DATA, "history", "ETH.csv"))
fng = pd.read_csv(os.path.join(DATA, "history", "_fear_greed.csv"), parse_dates=["date"]).set_index("date")["valeur"]

coins = sorted(series)
debut = min(d.index.min() for d in series.values())
fin = max(d.index.max() for d in series.values())  # un coin perime est simplement ignore le dernier jour
idx = pd.date_range(debut, fin, freq="D")


def matrice(col):
    return pd.DataFrame({s: series[s][col] for s in coins}).reindex(idx)


close, high, low = matrice("close"), matrice("high"), matrice("low")
qv = matrice("quote_volume").where(lambda x: x > 0)
btc_c = btc["close"].reindex(idx)
eth_c = eth["close"].reindex(idx)
print(f"Donnees : {len(coins)} coins, {idx[0].date()} -> {idx[-1].date()}")


# ------------------------------------------------------------------
# 2. Indicateurs
# ------------------------------------------------------------------
def bc(s):  # serie de marche -> meme valeur pour tous les coins
    return pd.DataFrame(np.repeat(s.to_numpy()[:, None], len(coins), axis=1), index=s.index, columns=coins)


lr = np.log(close).diff()
F = {}
for n in (1, 3, 7, 14, 30, 60, 90):
    F[f"ret{n}"] = np.log(close / close.shift(n))
F["vol7"] = lr.rolling(7).std()
F["vol30"] = lr.rolling(30).std()
F["vol_ratio"] = F["vol7"] / F["vol30"]
for n in (20, 50, 100):
    F[f"dist_sma{n}"] = close / close.rolling(n).mean() - 1
d = close.diff()
up, dn = d.clip(lower=0).rolling(14).mean(), (-d.clip(upper=0)).rolling(14).mean()
F["rsi14"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
F["dd90"] = close / close.rolling(90).max() - 1
F["dd365"] = close / close.rolling(365, min_periods=180).max() - 1
F["atr14"] = ((high - low) / close).rolling(14).mean()
F["vol_rel"] = np.log(qv.rolling(7).mean() / qv.rolling(90, min_periods=60).mean())
F["liq30"] = np.log(qv.rolling(30).mean())
F["dd_ath"] = close / close.cummax() - 1  # distance au plus haut de tout l'historique (depuis 2021)

blr = np.log(btc_c).diff()
F["corr_btc60"] = lr.rolling(60).corr(blr)
F["rel7"] = F["ret7"].sub(np.log(btc_c / btc_c.shift(7)), axis=0)
F["rel30"] = F["ret30"].sub(np.log(btc_c / btc_c.shift(30)), axis=0)

# contexte de marche (identique pour tous les coins un jour donne)
fng_s = fng.reindex(idx).ffill()
marche = {
    "btc_ret7": np.log(btc_c / btc_c.shift(7)),
    "btc_ret30": np.log(btc_c / btc_c.shift(30)),
    "btc_vol30": blr.rolling(30).std(),
    "btc_dist200": btc_c / btc_c.rolling(200, min_periods=120).mean() - 1,
    "ethbtc_ret30": np.log((eth_c / btc_c) / (eth_c / btc_c).shift(30)),
    "fng": fng_s,
    "fng_chg7": fng_s - fng_s.shift(7),
    "alt_ret30": F["ret30"].median(axis=1),
    "breadth30": (F["ret30"] > 0).where(F["ret30"].notna()).mean(axis=1),
}
for k, s in marche.items():
    F[k] = bc(s)

# rangs entre coins le meme jour
for k in ("ret7", "ret30", "ret90", "vol_rel", "dd90", "vol30"):
    F[f"rk_{k}"] = F[k].rank(axis=1, pct=True)

age = close.notna().cumsum()
FEATS = list(F)

mi = pd.MultiIndex.from_product([idx, coins], names=["date", "coin"])
panel = pd.DataFrame({k: v.reindex(index=idx, columns=coins).to_numpy().ravel() for k, v in F.items()}, index=mi)
panel["age"] = age.to_numpy().ravel()

# ------------------------------------------------------------------
# 3. Etiquettes (futur : utilisees uniquement pour entrainer / evaluer)
# ------------------------------------------------------------------
fwd = np.log(close.shift(-H) / close)
n_valides = fwd.notna().sum(axis=1)
rang_fwd = fwd.rank(axis=1, pct=True).where(n_valides >= 20, np.nan)
panel["fwd"] = fwd.to_numpy().ravel()
panel["fwds"] = np.expm1(panel["fwd"])
panel["y"] = (rang_fwd >= TOP_Q).where(rang_fwd.notna()).to_numpy().ravel()
btc_fwd = np.expm1(np.log(btc_c.shift(-H) / btc_c))

base = panel[panel["age"] >= MIN_AGE]
labeled = base.dropna(subset=["y", "fwd"]).copy()
labeled["y"] = labeled["y"].astype(float).astype(int)
print(f"Lignes etiquetees : {len(labeled):,} | indicateurs : {len(FEATS)} | part de 'y=1' : {labeled['y'].mean():.1%}")

# ------------------------------------------------------------------
# 4. Backtest walk-forward
# ------------------------------------------------------------------
dates_l = labeled.index.get_level_values(0)
derniere_date_etiq = dates_l.max()
starts = pd.date_range(TEST_START, derniere_date_etiq, freq=f"{TEST_STEP}D")
oos, dernier_modele, nb_folds = [], None, 0
for ts in starts:
    te = ts + pd.Timedelta(days=TEST_STEP - 1)
    train = labeled[dates_l <= ts - pd.Timedelta(days=GAP)]
    test = labeled[(dates_l >= ts) & (dates_l <= te)]
    if len(train) < 5000 or test.empty:
        continue
    m = HistGradientBoostingClassifier(**PARAMS).fit(train[FEATS], train["y"])
    t = test.copy()
    t["score"] = m.predict_proba(test[FEATS])[:, 1]
    oos.append(t)
    dernier_modele, nb_folds = m, nb_folds + 1
oos = pd.concat(oos)
print(f"Backtest : {nb_folds} periodes, {len(oos):,} predictions hors-echantillon "
      f"({oos.index.get_level_values(0).min().date()} -> {oos.index.get_level_values(0).max().date()})")


def ic_par_date(df, a, b):
    ra = df.groupby(level=0)[a].rank()
    rb = df.groupby(level=0)[b].rank()
    return pd.DataFrame({"a": ra, "b": rb}).groupby(level=0).apply(lambda x: x["a"].corr(x["b"]))


def top_n(df, col, n=N_PICK):
    d_ = df[[col, "fwds"]].copy()
    d_["rk"] = d_.groupby(level=0)[col].rank(ascending=False, method="first")
    return d_[d_["rk"] <= n].groupby(level=0)["fwds"].mean()


dts = oos.index.get_level_values(0).unique().sort_values()
strat = {
    "modele_top5": top_n(oos, "score") - COST,
    "modele_top5_liquide": top_n(oos[oos["liq30"] >= np.log(MIN_VOL_USD)], "score") - COST,
    "momentum30_top5": top_n(oos, "ret30") - COST,
    "momentum90_top5": top_n(oos, "ret90") - COST,
    "univers_equipondere": oos.groupby(level=0)["fwds"].mean() - COST,
    "btc": btc_fwd.reindex(dts) - COST,
}


def resume(s):
    s = s.dropna()
    mult = [float((1 + s.iloc[o::H]).prod()) for o in range(H)]
    return {"rendement_moyen_20j_%": round(float(s.mean()) * 100, 2),
            "rendement_median_20j_%": round(float(s.median()) * 100, 2),
            "periodes_positives_%": round(float((s > 0).mean()) * 100, 1),
            "multiple_cumule_median": round(float(np.median(mult)), 2),
            "multiple_cumule_min_max": [round(min(mult), 2), round(max(mult), 2)]}


resultats = {k: resume(v) for k, v in strat.items()}
bat_univers = round(float((strat["modele_top5_liquide"] > strat["univers_equipondere"]).mean()) * 100, 1)
par_an = {}
for an in sorted(set(dts.year)):
    msk = dts.year == an
    par_an[int(an)] = {k: round(float(v.reindex(dts)[msk].mean()) * 100, 2) for k, v in strat.items()
                       if k in ("modele_top5", "modele_top5_liquide", "momentum30_top5", "univers_equipondere", "btc")}
ic = ic_par_date(oos, "score", "fwd")
ic_na = ic.iloc[::H]  # echantillon sans chevauchement pour le test statistique
auc = float(roc_auc_score(oos["y"], oos["score"]))
t_stat = float(ic_na.mean() / (ic_na.std() / np.sqrt(len(ic_na))))
ic_mom = ic_par_date(oos, "ret30", "fwd")
print(f"AUC {auc:.3f} | IC moyen {ic.mean():.3f} (t={t_stat:.1f}) | IC momentum30 {ic_mom.mean():.3f}")

# importance des indicateurs (derniere periode, 6 derniers mois hors-echantillon)
recent = oos[oos.index.get_level_values(0) >= oos.index.get_level_values(0).max() - pd.Timedelta(days=180)]
recent = recent.sample(min(len(recent), 6000), random_state=0)
pi = permutation_importance(dernier_modele, recent[FEATS], recent["y"], scoring="roc_auc",
                            n_repeats=3, random_state=0, n_jobs=1)
importance = sorted(zip(FEATS, pi.importances_mean), key=lambda x: -x[1])[:12]

rapport = {
    "date_utc": datetime.now(timezone.utc).isoformat(),
    "parametres": {"horizon_jours": H, "etiquette": "top 30% de l'univers sur 20 j", "modele": PARAMS,
                   "cout_par_cycle_%": COST * 100, "coins": len(coins), "indicateurs": len(FEATS),
                   "periodes_test": nb_folds,
                   "test_du": str(dts.min().date()), "test_au": str(dts.max().date())},
    "qualite_prediction": {"auc": round(auc, 3), "ic_rang_moyen": round(float(ic.mean()), 3),
                           "ic_t_stat_sans_chevauchement": round(t_stat, 1),
                           "ic_rang_momentum30_reference": round(float(ic_mom.mean()), 3)},
    "strategies_top5": resultats,
    "modele_liquide_bat_l_univers_%_des_periodes": bat_univers,
    "rendement_moyen_20j_par_annee_%": par_an,
    "indicateurs_les_plus_utiles": [{"nom": k, "importance": round(float(v), 4)} for k, v in importance],
    "avertissements": [
        "Biais du survivant : l'univers est le top 100 d'aujourd'hui ; les coins disparus ou tombes sont absents, ce qui gonfle les resultats passes.",
        "Les periodes de 20 jours se chevauchent : les moyennes sont fiables, les ecarts-types et les multiples cumules sont indicatifs.",
        "Un bon backtest ne garantit pas les performances futures ; seul le test reel en conditions normales le confirmera.",
    ],
}
with open(os.path.join(OUT, "backtest_report.json"), "w", encoding="utf-8") as f:
    json.dump(rapport, f, ensure_ascii=False, indent=1)

# ------------------------------------------------------------------
# 5. Scores actuels (modele entraine sur tout le passe etiquete)
# ------------------------------------------------------------------
final = HistGradientBoostingClassifier(**PARAMS).fit(labeled[FEATS], labeled["y"])
jour = idx[-1]
actuel = base[base.index.get_level_values(0) == jour].copy()
a_un_prix = close.loc[jour].notna()
actuel = actuel[[bool(a_un_prix[c]) for c in actuel.index.get_level_values(1)]]
ignores = [c for c in coins if not a_un_prix[c]]
if ignores:
    print(f"Coins ignores (pas de prix au {jour.date()}) : {ignores}")
actuel["proba"] = final.predict_proba(actuel[FEATS])[:, 1]
actuel = actuel.droplevel(0).sort_values("proba", ascending=False)
actuel["score"] = (actuel["proba"].rank(pct=True) * 100).round(0)
actuel["rang"] = np.arange(1, len(actuel) + 1)
liste = []
for sym, r in actuel.iterrows():
    liste.append({"rang": int(r["rang"]), "symbole": sym, "nom": noms[sym], "score": int(r["score"]),
                  "proba_top30": round(float(r["proba"]), 3), "prix": float(close.loc[jour, sym]),
                  "ret7_%": round(float(np.expm1(r["ret7"])) * 100, 1),
                  "ret30_%": round(float(np.expm1(r["ret30"])) * 100, 1),
                  "dist_plus_haut_90j_%": round(float(r["dd90"]) * 100, 1),
                  "volume_30j_Musd": round(float(np.exp(r["liq30"])) / 1e6, 2),
                  "liquide": bool(np.exp(r["liq30"]) >= MIN_VOL_USD)})
with open(os.path.join(OUT, "latest_scores.json"), "w", encoding="utf-8") as f:
    json.dump({"date_donnees": str(jour.date()), "horizon_jours": H,
               "top5": [e["symbole"] for e in liste if e["liquide"]][:N_PICK],
               "classement": liste}, f,
              ensure_ascii=False, indent=1)

# ---- contexte de marche + fiches detaillees (lus par le site)
def pts(x, n, d=2):
    x = x.dropna().iloc[-n:]
    return [[i.strftime("%Y-%m-%d"), round(float(v), d)] for i, v in x.items()]


r90 = F["ret90"].sub(np.log(btc_c / btc_c.shift(90)), axis=0)
alt = ((r90 > 0).where(F["ret90"].notna()).mean(axis=1) * 100).where(F["ret90"].notna().sum(axis=1) >= 20)
dd_btc = (btc_c / btc_c.cummax() - 1) * 100
H0 = pd.Timestamp("2024-04-20")  # dernier halving
cyc = btc_c[btc_c.index >= H0] / btc_c[H0] * 100
ath_i = btc_c.idxmax()
market = {
    "date": str(jour.date()),
    "fng": {"valeur": int(fng_s.iloc[-1]), "serie": pts(fng_s, 120, 0)},
    "alt": {"valeur": int(round(alt.dropna().iloc[-1])), "serie": pts(alt, 365, 0)},
    "btc_ath": {"valeur": round(float(dd_btc.iloc[-1]), 1), "ath_prix": int(btc_c.max()), "ath_date": str(ath_i.date()),
                "serie": pts(dd_btc, 365, 1)},
    "breadth": {"valeur": int(round(marche["breadth30"].iloc[-1] * 100)), "serie": pts(marche["breadth30"] * 100, 365, 0)},
    "halving": {"derniere": "2024-04-20", "prochaine": "2028-04-18", "jour": int((jour - H0).days),
                "ath_jour": int((ath_i - H0).days),
                "courbe": [[int((i - H0).days), round(float(v), 1)] for i, v in cyc.iloc[::7].items()],
                "pics": [368, 526, 548], "creux": [777, 889, 925]},
}
json.dump(market, open(os.path.join(OUT, "market.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

GR = {"trend": [k for k in FEATS if k.startswith(("ret", "rel", "dist_sma", "rk_ret"))],
      "risk": ["vol7", "vol30", "vol_ratio", "atr14", "rk_vol30"], "highs": ["dd90", "dd365", "dd_ath", "rk_dd90"],
      "vol": ["vol_rel", "liq30", "rk_vol_rel"], "rsi": ["rsi14"], "mkt": list(marche), "btc": ["corr_btc60"]}
X = actuel[FEATS]
p0 = final.predict_proba(X)[:, 1]
med = labeled[FEATS].median()
imp = {}
for g, cols in GR.items():
    Xg = X.copy()
    Xg[cols] = med[cols].to_numpy()
    imp[g] = p0 - final.predict_proba(Xg)[:, 1]
det = {}
for n_, sym in enumerate(actuel.index):
    c = close[sym].dropna().iloc[-280:]
    r = actuel.loc[sym]
    det[sym] = {"c": [float(f"{v:.6g}") for v in c],
                "i": {k: (None if pd.isna(r[k]) else round(float(r[k]), 4))
                      for k in ("ret7", "ret30", "ret90", "dd90", "dd365", "dd_ath", "rsi14", "vol30", "vol_rel")},
                "e": [[g, round(float(imp[g][n_]) * 100, 1)] for g in GR]}
json.dump({"date": str(jour.date()), "coins": det}, open(os.path.join(OUT, "detail.json"), "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))

hist = os.path.join(OUT, "scores_history.csv")
deja = os.path.exists(hist) and str(jour.date()) in open(hist, encoding="utf-8").read()
if not deja:
    nouveau = not os.path.exists(hist)
    with open(hist, "a", encoding="utf-8") as f:
        if nouveau:
            f.write("date,symbole,rang,score,proba,prix\n")
        for e in liste:
            f.write(f"{jour.date()},{e['symbole']},{e['rang']},{e['score']},{e['proba_top30']},{e['prix']}\n")



def evaluer_reel():
    """Compare les scores deja publies (scores_history.csv) aux rendements reellement observes."""
    h = pd.read_csv(hist, parse_dates=["date"])
    liq_ok = F["liq30"] >= np.log(MIN_VOL_USD)
    res = {}
    for hor in (7, 15, 20):
        lignes = []
        for d, g in h.groupby("date"):
            d2 = d + pd.Timedelta(days=hor)
            if d not in close.index or d2 not in close.index:
                continue
            r = close.loc[d2] / close.loc[d] - 1
            g = g.set_index("symbole").sort_values("rang")
            g = g[[(s in r.index) and pd.notna(r[s]) for s in g.index]]
            if len(g) < 10:
                continue
            top = g[[bool(liq_ok.loc[d, s]) for s in g.index]].head(N_PICK).index
            lignes.append((d, float(r[top].mean()), float(r[g.index].mean()),
                           float(btc_c.loc[d2] / btc_c.loc[d] - 1)))
        if lignes:
            df = pd.DataFrame(lignes, columns=["date", "top5", "univers", "btc"])
            res[f"{hor}j"] = {"dates_evaluees": len(df),
                              "periodes_independantes": max(1, len(df) // hor),
                              "rendement_top5_%": round(float(df.top5.mean()) * 100, 2),
                              "rendement_univers_%": round(float(df.univers.mean()) * 100, 2),
                              "rendement_btc_%": round(float(df.btc.mean()) * 100, 2),
                              "top5_bat_univers_%": round(float((df.top5 > df.univers).mean()) * 100, 1)}
        else:
            res[f"{hor}j"] = {"dates_evaluees": 0}
    res["note"] = ("Test en conditions reelles : fiable seulement apres plusieurs periodes independantes "
                   "(au moins 6 de 20 jours, soit environ 4 mois).")
    with open(os.path.join(OUT, "live_test.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


test_reel = evaluer_reel()
print("Test reel :", {k: v.get("dates_evaluees") for k, v in test_reel.items() if k != "note"})

print(f"\nTop 5 liquide au {jour.date()} : " + ", ".join(f"{e['symbole']} ({e['score']})" for e in [e for e in liste if e["liquide"]][:N_PICK]))
print("Rapport : data/model/backtest_report.json")
