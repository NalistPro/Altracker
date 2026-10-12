"""
Altcoin Tracker - Alertes e-mail.
Bibliotheque standard uniquement.

Regles (modifiables ci-dessous) :
  OPPORTUNITE : un coin liquide ENTRE dans le top 3 du classement (il n'etait pas dans le top 5 ces 5 derniers
                jours), avec une probabilite du modele >= MIN_PROBA, hors periode de repos du coin.
  REEVALUATION : pour un coin signale, on previent si son prix passe sous -STOP %, s'il sort du top 15 des coins
                liquides, ou apres 20 jours (fin de l'horizon du modele).
Le script ne passe jamais d'ordre : il informe.

Secrets GitHub : GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO (jamais ecrits dans le depot).
Usage : python scripts/alerts.py data [--test]     (ALERT_DRY=1 : affiche le message au lieu de l'envoyer)
"""
import csv
import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape

DATA = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "data"
TEST = "--test" in sys.argv
SITE = "https://nalistpro.github.io/Altracker"

TOP_ENTREE = 3        # le coin doit entrer dans le top 3 des coins liquides
MIN_PROBA = 0.45      # probabilite minimale du modele
JOURS_SANS_REVOIR = 5  # ... sans avoir ete dans le top 5 durant ces jours
REPOS_COIN = 14       # jours avant de resignaler le meme coin
STOP = 0.15           # alerte de reevaluation si -15 % depuis le signal
SORTIE_RANG = 15
HORIZON = 20
MAX_PAR_MAIL = 3

NOM_GROUPE = {"trend": "la tendance", "risk": "la volatilité", "highs": "la distance aux plus hauts",
              "vol": "le volume et la liquidité", "rsi": "le RSI", "mkt": "le contexte de marché",
              "btc": "le lien avec BTC"}


def lire(chemin, defaut=None):
    try:
        return json.load(open(os.path.join(DATA, chemin), encoding="utf-8"))
    except Exception:
        return defaut


def usd(p):
    return "$" + (f"{p:,.0f}" if p >= 100 else f"{p:,.2f}" if p >= 1 else f"{p:.4f}").replace(",", " ")


def pc(v):
    return "–" if v is None else f"{v:+.1f} %".replace(".", ",")


def phase(jour):
    return ("début de cycle" if jour < 365 else "zone de sommet historique" if jour <= 550 else
            "marché baissier" if jour < 777 else "zone de creux historique" if jour <= 930 else "fin de cycle")


def contexte(market):
    if not market:
        return ""
    h = market["halving"]
    return (f"Contexte de marché : Fear & Greed à {market['fng']['valeur']}, Alt Season à {market['alt']['valeur']} %, "
            f"BTC à {str(market['btc_ath']['valeur']).replace('.', ',')} % de son plus haut, jour {h['jour']} du cycle "
            f"du halving ({phase(h['jour'])}).")


def pourquoi(detail, sym):
    e = ((detail or {}).get("coins", {}).get(sym) or {}).get("e") or []
    pos = sorted([x for x in e if x[1] > 0], key=lambda x: -x[1])[:2]
    if not pos:
        return ""
    return "Le modèle s'appuie surtout sur " + " et ".join(f"{NOM_GROUPE.get(g, g)} (+{v:.0f} pts)" for g, v in pos) + "."


# ------------------------------------------------------------------
def envoyer(sujet, blocs):
    """blocs : liste de (style, texte). Renvoie True si le message est parti (ou affiche en mode DRY)."""
    texte = "\n\n".join(t for _, t in blocs)
    corps = "".join(f"<p><b>{escape(t)}</b></p>" if s == "h" else
                    f"<p style='color:#666;font-size:12px'>{escape(t)}</p>" if s == "s" else
                    f"<p>{escape(t).replace(chr(10), '<br>')}</p>" for s, t in blocs)
    if os.environ.get("ALERT_DRY"):
        print(f"\n===== SUJET : {sujet} =====\n{texte}\n=====")
        return True
    user, mdp, dest = (os.environ.get(k, "").strip() for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "ALERT_TO"))
    manquants = [k for k, v in (("GMAIL_USER", user), ("GMAIL_APP_PASSWORD", mdp), ("ALERT_TO", dest)) if not v]
    if manquants:
        print("ECHEC : secret(s) absent(s) ou vide(s) : " + ", ".join(manquants) + ". Verifie le nom exact dans "
              "Settings > Secrets and variables > Actions, onglet 'Secrets' (pas 'Variables').")
        return False
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = sujet, f"Altracker <{user}>", dest
    m.set_content(texte)
    m.add_alternative(f"<div style='font-family:Georgia,serif;font-size:15px;line-height:1.55;max-width:560px'>{corps}</div>",
                      subtype="html")
    mdp = mdp.replace(" ", "")  # Google affiche le code par blocs de 4 : les espaces ne font pas partie du code
    ctx = ssl.create_default_context()
    erreurs = []
    try:
        for nom, ouvrir in (("port 587 (STARTTLS)", lambda: smtplib.SMTP("smtp.gmail.com", 587, timeout=30)),
                            ("port 465 (SSL)", lambda: smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30))):
            etape = "connexion"
            try:
                with ouvrir() as s:
                    s.ehlo()
                    if "587" in nom:
                        etape = "chiffrement"
                        s.starttls(context=ctx)
                        s.ehlo()
                    etape = "identification"
                    s.login(user, mdp)
                    etape = "envoi"
                    s.send_message(m)
                print(f"E-mail envoyé via {nom} : {sujet}")
                return True
            except smtplib.SMTPAuthenticationError:
                raise
            except Exception as ex:
                erreurs.append(f"{nom}, étape '{etape}' : {type(ex).__name__} {ex}")
                print("Tentative échouée -> " + erreurs[-1])
        print("ECHEC d'envoi : les deux modes de connexion ont échoué (voir les lignes ci-dessus).")
        return False
    except smtplib.SMTPAuthenticationError as ex:
        print(f"ECHEC d'authentification Gmail (code {ex.smtp_code}) : le mot de passe d'application est refuse. Verifie que "
              "GMAIL_USER est l'adresse complete du compte qui a cree ce mot de passe, que la validation en 2 etapes est "
              "active sur ce compte, puis cree un nouveau mot de passe d'application si besoin.")
        return False
    except Exception as ex:
        print(f"ECHEC d'envoi ({type(ex).__name__}) : {ex}")
        return False


def main():
    sc = lire("model/latest_scores.json")
    if not sc:
        sys.exit("latest_scores.json introuvable")
    market, detail = lire("model/market.json"), lire("model/detail.json")
    jour = sc["date_donnees"]
    liquides = [c for c in sc["classement"] if c["liquide"]]          # deja tries par rang
    par_sym = {c["symbole"]: c for c in sc["classement"]}
    rang_liq = {c["symbole"]: i + 1 for i, c in enumerate(liquides)}
    os.makedirs(os.path.join(DATA, "alerts"), exist_ok=True)
    chemin_etat = os.path.join(DATA, "alerts", "state.json")
    etat = lire("alerts/state.json", {"top5": {}, "positions": {}, "repos": {}, "premier_jour": jour})
    ref = datetime.strptime(jour, "%Y-%m-%d")

    # ---- reevaluations des coins deja signales
    reeval = []
    for sym, p in list(etat["positions"].items()):
        c = par_sym.get(sym)
        age = (ref - datetime.strptime(p["date"], "%Y-%m-%d")).days
        if not c:
            continue
        perf = c["prix"] / p["prix"] - 1
        motif = (f"son prix a reculé de {abs(perf) * 100:.0f} % depuis le signal" if perf <= -STOP else
                 f"il est sorti du top {SORTIE_RANG} (rang {rang_liq.get(sym, '>' + str(len(liquides)))})"
                 if rang_liq.get(sym, 999) > SORTIE_RANG else
                 f"l'horizon de {HORIZON} jours du modèle est atteint" if age >= HORIZON else None)
        if motif:
            reeval.append((sym, c, p, perf, motif))

    # ---- nouvelles opportunites
    recents = set()
    for d, liste in etat["top5"].items():
        if 0 < (ref - datetime.strptime(d, "%Y-%m-%d")).days <= JOURS_SANS_REVOIR:
            recents |= set(liste)
    opps = []
    if etat["top5"] or TEST:  # le tout premier jour sert de reference : pas d'alerte sans historique
        for c in liquides[:TOP_ENTREE]:
            s = c["symbole"]
            repos = etat["repos"].get(s)
            en_repos = repos and (ref - datetime.strptime(repos, "%Y-%m-%d")).days < REPOS_COIN
            if (s not in recents and c["proba_top30"] >= MIN_PROBA and not en_repos and s not in etat["positions"]) or TEST:
                opps.append(c)
    opps = opps[:MAX_PAR_MAIL]
    if TEST and not opps:
        opps = liquides[:1]

    # ---- messages
    envoye_ok = True
    if opps:
        blocs = [("h", "Un coin vient d'entrer dans le haut du classement."),
                 ("p", "Voici ce que le modèle a repéré à la clôture du " + datetime.strptime(jour, "%Y-%m-%d").strftime("%d/%m/%Y") + " :")]
        for c in opps:
            blocs.append(("p", f"{c['symbole']} ({c['nom']}) — score {c['score']}/100, rang {rang_liq[c['symbole']]} des coins liquides.\n"
                               f"Prix {usd(c['prix'])}, {pc(c['ret7_%'])} sur 7 j, {pc(c['ret30_%'])} sur 30 j, "
                               f"volume moyen {str(round(c['volume_30j_Musd'], 1)).replace('.', ',')} M$ par jour.\n"
                               f"Probabilité d'être parmi les 30 % meilleurs coins à 20 jours : {c['proba_top30'] * 100:.0f} %. "
                               f"{pourquoi(detail, c['symbole'])}\n"
                               f"Suivi : je te préviens si le prix passe sous {usd(c['prix'] * (1 - STOP))} ou si le coin sort du top {SORTIE_RANG}."))
        if market:
            blocs.append(("p", contexte(market)))
        blocs.append(("p", "À garder en tête : dans le test historique (2023 à 2026), un signal de ce type a donné en moyenne +5,5 % à 20 jours, "
                           "mais le résultat médian était de −0,5 % et un cas sur deux seulement était positif. Les pires cas ont perdu près de la moitié. "
                           "C'est une information pour t'aider à regarder au bon endroit, pas une garantie."))
        blocs.append(("p", f"Fiche détaillée : {SITE}"))
        blocs.append(("s", "Outil d'étude, pas un conseil en investissement. Les performances passées ne garantissent pas les résultats futurs."))
        noms = ", ".join(c["symbole"] for c in opps)
        sujet = ("[TEST] " if TEST else "") + f"Altracker : {'opportunité' if len(opps) == 1 else 'opportunités'} repérée{'s' if len(opps) > 1 else ''} ({noms})"
        envoye_ok = envoyer(sujet, blocs) and envoye_ok
        if TEST and not envoye_ok:
            sys.exit(1)  # le test doit apparaitre en rouge s'il echoue
        if envoye_ok and not TEST:
            for c in opps:
                etat["positions"][c["symbole"]] = {"date": jour, "prix": c["prix"]}
                etat["repos"][c["symbole"]] = jour
    if reeval and not TEST:
        blocs = [("h", "Il est temps de réévaluer " + ("ce coin." if len(reeval) == 1 else "ces coins."))]
        for sym, c, p, perf, motif in reeval:
            blocs.append(("p", f"{sym} ({c['nom']}) : {motif}.\nPrix {usd(c['prix'])} contre {usd(p['prix'])} au signal du {datetime.strptime(p['date'], '%Y-%m-%d').strftime('%d/%m/%Y')} ({pc(perf * 100)}). "
                               f"Score actuel : {c['score']}/100."))
        blocs.append(("p", "Ce n'est pas un ordre de vente : c'est le moment de regarder la fiche et de décider en connaissance de cause. " + SITE))
        blocs.append(("s", "Outil d'étude, pas un conseil en investissement."))
        if envoyer(f"Altracker : à réévaluer ({', '.join(r[0] for r in reeval)})", blocs):
            for r in reeval:
                etat["positions"].pop(r[0], None)

    if not TEST:
        etat["top5"][jour] = [c["symbole"] for c in liquides[:5]]
        for d in [d for d in etat["top5"] if (ref - datetime.strptime(d, "%Y-%m-%d")).days > 30]:
            etat["top5"].pop(d)
        json.dump(etat, open(chemin_etat, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if opps or reeval:
            nouveau = not os.path.exists(os.path.join(DATA, "alerts", "history.csv"))
            with open(os.path.join(DATA, "alerts", "history.csv"), "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if nouveau:
                    w.writerow(["date", "type", "symbole", "score", "prix"])
                w.writerows([[jour, "opportunite", c["symbole"], c["score"], c["prix"]] for c in opps])
                w.writerows([[jour, "reevaluation", r[0], r[1]["score"], r[1]["prix"]] for r in reeval])
    print(f"Jour {jour} : {len(opps)} opportunité(s), {len(reeval)} réévaluation(s), {len(etat['positions'])} coin(s) suivi(s).")


if __name__ == "__main__":
    main()
