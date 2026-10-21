#!/usr/bin/env python3
"""Envoie un brouillon RELU vers le script Google (abonnés actifs uniquement).
Usage : python scripts/newsletter_send.py newsletter/drafts/XXXX.md [--test]
Variables : NEWSLETTER_URL, NEWSLETTER_SECRET (secrets GitHub)"""
import json, os, re, sys, urllib.parse, urllib.request

path = sys.argv[1]; test = "--test" in sys.argv
raw = open(path, encoding="utf-8").read()
raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
m = re.match(r"\s*#\s*Objet\s*:\s*(.+)", raw); assert m, "La 1re ligne doit être « # Objet : ... »"
sujet = m.group(1).strip(); body = raw[m.end():]

def inline(t):
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" style="color:#0b8a82">\1</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<em>\1</em>", t)
html, ul = [], False
for line in body.strip().split("\n"):
    if line.startswith("- "):
        if not ul: html.append("<ul>"); ul = True
        html.append(f"<li>{inline(line[2:])}</li>"); continue
    if ul: html.append("</ul>"); ul = False
    if line.startswith("## "): html.append(f'<h3 style="margin:22px 0 6px">{inline(line[3:])}</h3>')
    elif line.strip(): html.append(f'<p style="margin:0 0 12px">{inline(line)}</p>')
if ul: html.append("</ul>")
page = ('<div style="max-width:560px;margin:auto;font:16px/1.55 Georgia,serif;color:#1a1f24">' + "\n".join(html) + "</div>")
data = {"action": "send", "secret": os.environ["NEWSLETTER_SECRET"], "sujet": sujet, "html": page,
        "campagne": os.path.basename(path).replace(".md", ""), "test": "1" if test else "0"}
req = urllib.request.Request(os.environ["NEWSLETTER_URL"], data=urllib.parse.urlencode(data).encode())
print(urllib.request.urlopen(req, timeout=120).read().decode())
