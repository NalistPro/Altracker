# Newsletter Altracker : installation (gratuite, ~15 minutes)

Principe : les inscrits vont dans un **Google Sheet** que tu possèdes. Un petit script Google gère l'inscription (avec e-mail de confirmation), la désinscription et l'envoi. Le brouillon est préparé automatiquement par GitHub, **tu le relis**, puis tu déclenches l'envoi.

## 1. Le script Google (inscriptions + envoi)
1. Va sur sheets.google.com, crée une feuille vide nommée « Altracker abonnés ».
2. Menu **Extensions > Apps Script**. Efface le code par défaut et colle le contenu de `apps-script/Code.gs`.
3. À gauche, **Paramètres du projet** (roue dentée) > **Propriétés du script** > Ajouter : nom `NEWSLETTER_SECRET`, valeur = un mot de passe long de ton choix (garde-le).
4. **Déployer > Nouveau déploiement** > type **Application Web** : *Exécuter en tant que : moi*, *Accès : tout le monde*. Autorise l'accès (si Google affiche « application non validée » : Paramètres avancés > Continuer, c'est ton propre script).
5. Copie l'**URL de l'application Web** (elle finit par `/exec`).

## 2. Brancher le site
Dans `index.html`, remplace `const NEWSLETTER_URL='';` par `const NEWSLETTER_URL='L-URL-COPIEE';` (ou envoie-moi l'URL, je te régénère le fichier).

## 3. Brancher GitHub (envoi)
Dépôt > **Settings > Secrets and variables > Actions > New repository secret**, deux secrets :
- `NEWSLETTER_URL` = l'URL `/exec`
- `NEWSLETTER_SECRET` = le même mot de passe qu'à l'étape 1.3

## 4. Utilisation
- Chaque jour, l'action « Brouillon de newsletter » vérifie les conditions. Si elles sont réunies (au plus 1 fois par 7 jours), ou tous les 15 jours pour le point régulier, elle crée `newsletter/drafts/AAAA-MM-JJ-type.md` et t'ouvre une **Issue** (tu reçois un e-mail GitHub).
- Relis et corrige le fichier directement sur GitHub (crayon).
- Onglet **Actions > Envoyer la newsletter > Run workflow** : colle le chemin du fichier. Laisse « test » coché pour te l'envoyer d'abord, puis relance en décochant pour envoyer aux inscrits confirmés.

## Limites à connaître
- Gmail gratuit : **100 destinataires par jour** (les e-mails de confirmation comptent). Au-delà, relance le même envoi le lendemain : personne ne reçoit de doublon.
- Garde le Google Sheet privé. Si quelqu'un demande la suppression de son adresse, supprime sa ligne.
- Chaque e-mail contient un lien de désinscription en un clic.
