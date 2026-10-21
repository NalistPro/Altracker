/** Altracker : inscriptions + envoi de la newsletter (Google Apps Script, gratuit).
 *  Déploiement : voir GUIDE-NEWSLETTER.md */
const FEUILLE = 'Abonnes';
const NOM = 'Altracker';

function feuille_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let s = ss.getSheetByName(FEUILLE);
  if (!s) { s = ss.insertSheet(FEUILLE); s.appendRow(['date', 'email', 'langue', 'jeton', 'statut', 'derniere_campagne']); }
  return s;
}
const sortie_ = o => ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
const page_ = (titre, texte) => HtmlService.createHtmlOutput(
  '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<body style="font-family:system-ui;background:#0a0e13;color:#e8edf2;display:grid;place-items:center;min-height:90vh;text-align:center;padding:20px">' +
  '<div><h2>' + titre + '</h2><p>' + texte + '</p></div>').setTitle(NOM);

function doPost(e) {
  const p = (e && e.parameter) || {};
  try {
    if (p.action === 'subscribe') return sortie_(inscrire_(p));
    if (p.action === 'send') return sortie_(envoyer_(p));
  } catch (err) { return sortie_({ ok: false, erreur: String(err) }); }
  return sortie_({ ok: false });
}
function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.a === 'confirm' && p.t) return maj_(p.t, 'actif') ? page_('Inscription confirmée ✅', 'Merci ! Tu recevras la prochaine newsletter.') : page_('Lien invalide', 'Ce lien n\'est plus valide.');
  if (p.a === 'unsub' && p.t) return maj_(p.t, 'desinscrit') ? page_('Désinscription effectuée', 'Tu ne recevras plus d\'e-mails d\'Altracker.') : page_('Lien invalide', 'Ce lien n\'est plus valide.');
  return page_('Altracker', 'Service de newsletter.');
}
function maj_(jeton, statut) {
  const s = feuille_(), d = s.getDataRange().getValues();
  for (let i = 1; i < d.length; i++) if (d[i][3] === jeton) { s.getRange(i + 1, 5).setValue(statut); return true; }
  return false;
}
function inscrire_(p) {
  if (p.website) return { ok: true };                       // piège anti-robot
  const email = String(p.email || '').trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email) || p.consent !== '1') return { ok: false, erreur: 'invalide' };
  const verrou = LockService.getScriptLock(); verrou.waitLock(15000);
  try {
    const s = feuille_(), d = s.getDataRange().getValues();
    let jeton = null;
    for (let i = 1; i < d.length; i++) if (String(d[i][1]).toLowerCase() === email) {
      if (d[i][4] === 'actif') return { ok: true };
      jeton = d[i][3]; s.getRange(i + 1, 5).setValue('en_attente'); break;
    }
    if (!jeton) { jeton = Utilities.getUuid(); s.appendRow([new Date(), email, p.lang || 'fr', jeton, 'en_attente', '']); }
    const lien = ScriptApp.getService().getUrl() + '?a=confirm&t=' + jeton;
    MailApp.sendEmail({ to: email, subject: 'Confirme ton inscription à Altracker', name: NOM,
      htmlBody: '<p>Bonjour,</p><p>Clique pour confirmer ton inscription à la newsletter d\'Altracker :</p><p><a href="' + lien + '">Confirmer mon inscription</a></p><p style="color:#666;font-size:12px">Si tu n\'es pas à l\'origine de cette demande, ignore simplement ce message : aucune inscription ne sera faite.</p>' });
    return { ok: true };
  } finally { verrou.releaseLock(); }
}
function envoyer_(p) {
  const secret = PropertiesService.getScriptProperties().getProperty('NEWSLETTER_SECRET');
  if (!secret || p.secret !== secret) return { ok: false, erreur: 'non autorisé' };
  const sujet = String(p.sujet || ''), html = String(p.html || ''), camp = String(p.campagne || '');
  if (!sujet || !html || !camp) return { ok: false, erreur: 'incomplet' };
  const url = ScriptApp.getService().getUrl();
  if (p.test === '1') {   // test : envoi uniquement à toi
    MailApp.sendEmail({ to: Session.getEffectiveUser().getEmail(), subject: '[TEST] ' + sujet, name: NOM, htmlBody: html.replace(/\{\{DESINSCRIPTION\}\}/g, url + '?a=unsub&t=TEST') });
    return { ok: true, test: true };
  }
  const s = feuille_(), d = s.getDataRange().getValues();
  let envoyes = 0, restants = 0;
  for (let i = 1; i < d.length; i++) {
    if (d[i][4] !== 'actif' || d[i][5] === camp) continue;      // actifs seulement, pas de doublon
    if (MailApp.getRemainingDailyQuota() < 1) { restants++; continue; }   // quota gratuit : 100/jour
    MailApp.sendEmail({ to: d[i][1], subject: sujet, name: NOM, htmlBody: html.replace(/\{\{DESINSCRIPTION\}\}/g, url + '?a=unsub&t=' + d[i][3]) });
    s.getRange(i + 1, 6).setValue(camp); envoyes++;
  }
  return { ok: true, envoyes: envoyes, restants: restants };
}
