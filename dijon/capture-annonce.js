// Capture d'une annonce — à installer comme favori (voir favoris.html).
//
// Le script s'exécute dans VOTRE navigateur, sur une annonce que vous avez
// ouverte. Il ne lance aucune requête : il lit ce que la page contient déjà.
//
// Il ne lit QUE les blocs de l'annonce, désignés par leurs identifiants. Une
// page d'annonce contient aussi les autres biens du vendeur et ceux qu'il a
// déjà vendus, avec leurs surfaces et leurs rues. Prendre le texte de la page
// entière revient à décrire un bien avec les caractéristiques de ses voisins.
//
// La description est repliée : la page n'en affiche que trois lignes et le
// reste n'est pas dans le document. Il faut déplier avant de lire.

(function () {
  var ATTENTE = 400;   // laisser la page se redessiner après les dépliages

  // Blocs de l'annonce sur Leboncoin, relevés sur une page réelle.
  var LBC = {
    titre: '[data-qa-id="adview_title"]',
    prix: '[data-qa-id="adview_price"]',
    description: '#readme-content',
    lieu: '[data-qa-id="adview_spotlight_description_container"] a[href*="#map"]',
    deplier: ['[data-qa-id="adview_description_container"] button[aria-expanded="false"]',
              '[data-qa-id="criteria_more"]']
  };
  // Les caractéristiques sont déjà structurées par le site : les lire évite de
  // les redécouvrir dans le texte, ce qui échouait sur les mises en page.
  var CRITERES = {
    square: 'criteria_item_square',
    rooms: 'criteria_item_rooms',
    real_estate_type: 'criteria_item_real_estate_type',
    land_plot_surface: 'criteria_item_land_plot_surface',
    bedrooms: 'criteria_item_bedrooms'
  };

  function texte(sel, racine) {
    var el = (racine || document).querySelector(sel);
    return el ? (el.innerText || '').trim() : '';
  }

  function critere(qaId) {
    var el = document.querySelector('[data-qa-id="' + qaId + '"]');
    if (!el) return '';
    // Le bloc porte deux paragraphes : le libellé puis la valeur.
    var ps = el.querySelectorAll('p');
    return ps.length ? (ps[ps.length - 1].innerText || '').trim() : '';
  }

  var nombre = function (s) { return (String(s).replace(/[^\d]/g, '') || ''); };

  function deplie() {
    for (var i = 0; i < LBC.deplier.length; i++) {
      try {
        var b = document.querySelector(LBC.deplier[i]);
        if (b) b.click();
      } catch (e) { /* bouton absent ou non cliquable */ }
    }
  }

  // Repli pour les autres sites : conteneurs plausibles, puis corps tronqué
  // avant les intitulés qui annoncent d'autres biens.
  var COUPURES = /annonces?\s+similaires|vous\s+pourriez|peuvent\s+vous\s+int[ée]resser|autres\s+annonces|les\s+annonces\s+de\s+ce|d[ée]j[àa]\s+vendus|dans\s+la\s+m[êe]me|nos\s+suggestions/i;
  var GENERIQUES = ['[itemprop=description]', '[data-qa-id="adview_description_container"]',
                    'main', 'article'];

  function tronque(t) {
    var m = COUPURES.exec(t);
    return (m ? t.slice(0, m.index) : t).replace(/[ \t]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n').slice(0, 20000);
  }

  function repli() {
    for (var i = 0; i < GENERIQUES.length; i++) {
      var el = null;
      try { el = document.querySelector(GENERIQUES[i]); } catch (e) { continue; }
      if (el && (el.innerText || '').trim().length > 40) {
        return { source: GENERIQUES[i], texte: tronque(el.innerText) };
      }
    }
    return { source: 'page entière', texte: tronque(document.body.innerText) };
  }

  function assemble() {
    var titre = texte(LBC.titre) || document.title;
    var description = texte(LBC.description);
    var lieu = texte(LBC.lieu);                       // « Longvic 21600 »
    var attributs = {};
    for (var k in CRITERES) {
      if (!Object.prototype.hasOwnProperty.call(CRITERES, k)) continue;
      var v = critere(CRITERES[k]);
      if (!v) continue;
      attributs[k] = (k === 'real_estate_type') ? v : nombre(v);
    }

    var data = {
      type: 'annonce',
      url: location.href,
      site: location.hostname.replace(/^www\./, ''),
      capture: new Date().toISOString()
    };

    if (description) {
      var m = lieu.match(/^(.*?)\s*(\d{5})\s*$/);
      data.source = 'blocs de l’annonce';
      data.titre = titre;
      data.texte = [titre, description, lieu].filter(Boolean).join('\n');
      data.prix = nombre(texte(LBC.prix)) || null;
      data.attributs = attributs;
      data.ville = m ? m[1].trim() : lieu;
      data.cp = m ? m[2] : '';
      data.tronquee = /[…]\s*$/.test(description);
    } else {
      var r = repli();
      data.source = r.source;
      data.titre = titre;
      data.texte = r.texte;
      data.attributs = attributs;
    }
    return data;
  }

  function toast(msg, ok) {
    var e = document.createElement('div');
    e.textContent = msg;
    e.style.cssText = 'position:fixed;z-index:2147483647;top:12px;right:12px;max-width:24em;' +
      'padding:10px 14px;border-radius:6px;font:14px system-ui,sans-serif;color:#fff;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.35);background:' + (ok ? '#15803d' : '#b91c1c');
    document.body.appendChild(e);
    setTimeout(function () { e.remove(); }, 4000);
  }

  function livre(data) {
    var json = JSON.stringify(data, null, 1);
    var nom = 'annonce-' + Date.now() + '.json';
    var telecharge = false;
    try {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
      a.download = nom;
      document.body.appendChild(a); a.click(); a.remove();
      telecharge = true;
    } catch (e) { /* CSP : presse-papiers */ }
    var resume = data.source + ', ' + data.texte.length + ' car.' +
      (data.attributs && data.attributs.square ? ', ' + data.attributs.square + ' m²' : '') +
      (data.tronquee ? ' — DESCRIPTION TRONQUÉE' : '');
    (navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject()).then(
      function () { toast('Annonce capturée (' + resume + ')' + (telecharge ? ' → ' + nom : ' → presse-papiers'), !data.tronquee); },
      function () {
        if (telecharge) toast('Annonce capturée (' + resume + ') → ' + nom, !data.tronquee);
        else toast('Capture impossible sur cette page', false);
      }
    );
  }

  deplie();
  setTimeout(function () { livre(assemble()); }, ATTENTE);
})();
