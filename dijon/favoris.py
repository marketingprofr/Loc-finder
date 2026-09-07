#!/usr/bin/env python3
"""
Fabrique favoris.html, la page depuis laquelle s'installent les deux favoris
de capture.

    python favoris.py

Les favoris sont de longues lignes de code : les recopier à la main est une
mauvaise idée. La page les présente comme des liens qu'on fait glisser dans
la barre de favoris du navigateur, ce qui est la façon habituelle de procéder.

À relancer après toute modification de capture-recherche.js ou capture-annonce.js.
"""
import html
import io
import os
import re

SOURCES = [
    ("capture-recherche.js", "Capturer la recherche",
     "Sur une page de résultats, capture toutes les annonces affichées."),
    ("capture-annonce.js", "Capturer l’annonce",
     "Sur une annonce ouverte, capture sa description entière."),
]
SORTIE = "favoris.html"


def ligne_favori(chemin):
    """La ligne `// javascript:…` en bas du fichier, sans son préfixe de commentaire."""
    with io.open(chemin, encoding="utf-8") as f:
        for ligne in f:
            l = ligne.strip()
            if l.startswith("// javascript:"):
                return l[3:]
    raise SystemExit(f"{chemin} : ligne « // javascript: » introuvable")


def main():
    ici = os.path.dirname(os.path.abspath(__file__))
    boutons = []
    for fichier, titre, description in SOURCES:
        code = ligne_favori(os.path.join(ici, fichier))
        boutons.append(f'''
    <div class="favori">
      <a class="bouton" href="{html.escape(code, quote=True)}">{html.escape(titre)}</a>
      <p>{html.escape(description)}</p>
      <details><summary>Ou copier le code à la main</summary>
        <textarea readonly rows="3" onclick="this.select()">{html.escape(code)}</textarea>
      </details>
    </div>''')

    page = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Installer les favoris de capture</title>
<style>
  :root {{ --ink:#1f2328; --muted:#6b7280; --line:#e2e5e9; }}
  body {{ margin:0; padding:32px 24px; font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
         color:var(--ink); max-width:44em; margin-inline:auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 28px; }}
  ol {{ padding-left:20px; }}
  li {{ margin-bottom:10px; }}
  .favori {{ border:1px solid var(--line); border-radius:8px; padding:16px 18px; margin:14px 0;
            background:#fafafa; }}
  .favori p {{ margin:10px 0 0; color:var(--muted); font-size:14px; }}
  .bouton {{ display:inline-block; padding:9px 16px; background:#1d4ed8; color:#fff;
            border-radius:6px; text-decoration:none; font-weight:600; cursor:grab; }}
  .bouton:active {{ cursor:grabbing; }}
  details {{ margin-top:12px; }}
  summary {{ color:var(--muted); font-size:13px; cursor:pointer; }}
  textarea {{ width:100%; margin-top:8px; font:12px/1.4 ui-monospace,Consolas,monospace;
             border:1px solid var(--line); border-radius:4px; padding:8px; resize:vertical; }}
  .note {{ background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:14px 18px;
          font-size:14px; margin-top:28px; }}
  kbd {{ background:#eef0f2; border:1px solid #d4d8dc; border-bottom-width:2px; border-radius:4px;
        padding:1px 5px; font:12px ui-monospace,Consolas,monospace; }}
</style></head><body>
<h1>Installer les favoris de capture</h1>
<p class="sub">Deux boutons à faire glisser une fois pour toutes dans votre barre de favoris.</p>

<ol>
  <li><b>Afficher la barre de favoris</b> si elle est masquée : <kbd>Ctrl</kbd> + <kbd>Maj</kbd> + <kbd>B</kbd>.</li>
  <li><b>Faire glisser</b> chaque bouton bleu ci-dessous vers cette barre. Ne cliquez pas dessus
      ici : ils ne servent que sur une page d'annonces.</li>
  <li>C'est tout. Sur Leboncoin ou SeLoger, un clic sur le favori enregistre ce que
      vous regardez dans vos téléchargements.</li>
</ol>
{''.join(boutons)}

<div class="note">
  Ces deux favoris ne vont rien chercher sur Internet. Ils lisent la page que votre
  navigateur affiche déjà, une page à la fois, quand vous le décidez. Le fichier
  déposé dans vos téléchargements est ensuite relu par <code>python annonces.py</code>,
  qui écrit <code>annonces.js</code> à côté de la carte.
</div>
</body></html>
"""
    chemin = os.path.join(ici, SORTIE)
    with io.open(chemin, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"OK → {SORTIE} ({len(boutons)} favoris). Ouvrir ce fichier dans le navigateur.")


if __name__ == "__main__":
    main()
