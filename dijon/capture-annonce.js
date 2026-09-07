// Capture d'une annonce — à installer comme favori (voir favoris.html).
//
// Le script s'exécute dans VOTRE navigateur, sur une annonce que vous avez
// ouverte. Il ne lance aucune requête : il lit ce que la page contient déjà.
//
// Il ne prend QUE l'annonce affichée. Une page d'annonce contient aussi un
// en-tête, un pied de page et un bloc « annonces similaires » avec dix autres
// biens — leurs surfaces, leurs prix, leurs rues. Les avaler revient à
// attribuer au bien la description de ses voisins.
//
// Trois voies, de la plus sûre à la plus approximative :
// Deux sources, combinées :
//   - __NEXT_DATA__, où le site range l'annonce sous forme structurée : on y
//     prend celle dont l'identifiant est dans l'URL, pour le prix, la surface
//     et la commune, qui valent mieux que ce qu'on tirerait du texte ;
//   - le conteneur de la description, #readme-content sur Leboncoin, à défaut
//     main ou article, à défaut le corps tronqué avant les recommandations.

(function () {
  var MAX_PROFONDEUR = 14;
  // Tout ce qui suit ces intitulés appartient à d'autres annonces.
  var COUPURES = /annonces?\s+similaires|vous\s+pourriez|peuvent\s+vous\s+int[ée]resser|autres\s+annonces|dans\s+la\s+m[êe]me|voir\s+plus\s+d.annonces|nos\s+suggestions|recherches?\s+associ[ée]es|derni[èe]res?\s+annonces/i;

  function idDeLUrl() {
    var m = location.pathname.match(/(\d{6,})/);
    return m ? m[1] : null;
  }

  function collecte(obj, out, vus, prof) {
    if (!obj || typeof obj !== 'object' || prof > MAX_PROFONDEUR) return out;
    if (vus.indexOf(obj) !== -1) return out;
    vus.push(obj);
    if (Array.isArray(obj)) {
      for (var i = 0; i < obj.length; i++) collecte(obj[i], out, vus, prof + 1);
      return out;
    }
    if ((obj.list_id || obj.listId) && (obj.subject || obj.title)) out.push(obj);
    for (var k in obj) if (Object.prototype.hasOwnProperty.call(obj, k)) collecte(obj[k], out, vus, prof + 1);
    return out;
  }

  function depuisNextData() {
    var nd = document.getElementById('__NEXT_DATA__');
    if (!nd || !nd.textContent) return null;
    var tous = collecte(JSON.parse(nd.textContent), [], [], 0);
    if (!tous.length) return null;
    // La page en contient plusieurs : celle qu'on regarde, et les suggérées.
    // Seul l'identifiant de l'URL désigne la bonne.
    var id = idDeLUrl();
    var a = null;
    for (var i = 0; i < tous.length && id; i++) {
      if (String(tous[i].list_id || tous[i].listId) === id) { a = tous[i]; break; }
    }
    if (!a && tous.length === 1) a = tous[0];
    if (!a) return null;

    var at = {}, attrs = a.attributes || [];
    for (var j = 0; j < attrs.length; j++) {
      if (attrs[j] && attrs[j].key) at[attrs[j].key] = attrs[j].value_label || attrs[j].value;
    }
    var loc = a.location || {};
    return {
      titre: a.subject || a.title || document.title,
      corps: a.body || '',
      prix: Array.isArray(a.price) ? a.price[0] : a.price,
      attributs: at,
      ville: loc.city || '', cp: loc.zipcode || '',
      lat: loc.lat, lon: loc.lng
    };
  }

  function tronque(texte) {
    var m = COUPURES.exec(texte);
    return (m ? texte.slice(0, m.index) : texte)
      .replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').slice(0, 20000);
  }

  // Du plus précis au plus large. #readme-content est le conteneur de la
  // description sur Leboncoin ; les suivants couvrent les autres sites.
  var CIBLES = ['#readme-content', '[data-qa-id=adview_description_container]',
                '[itemprop=description]', 'main', 'article', '[role=main]'];

  function description() {
    for (var i = 0; i < CIBLES.length; i++) {
      var el = null;
      try { el = document.querySelector(CIBLES[i]); } catch (e) { continue; }
      if (el && (el.innerText || '').trim().length > 40) {
        return { selecteur: CIBLES[i], texte: tronque(el.innerText) };
      }
    }
    return { selecteur: 'page entière', texte: tronque(document.body.innerText) };
  }

  var struct = null;
  try { struct = depuisNextData(); } catch (e) { /* structure inattendue */ }
  var desc = description();

  var data = {
    type: 'annonce',
    url: location.href,
    site: location.hostname.replace(/^www\./, ''),
    capture: new Date().toISOString()
  };

  if (struct) {
    // Le corps rangé par le site est propre par construction : on ne lui
    // préfère le texte affiché que s'il vient d'un conteneur identifié.
    var corps = desc.selecteur === 'page entière' ? struct.corps : desc.texte;
    data.source = '__NEXT_DATA__ + ' + desc.selecteur;
    data.titre = struct.titre;
    data.texte = [struct.titre, corps, struct.ville, struct.cp].filter(Boolean).join('\n');
    data.prix = struct.prix;
    data.attributs = struct.attributs;
    data.ville = struct.ville; data.cp = struct.cp;
    data.lat = struct.lat; data.lon = struct.lon;
  } else {
    data.source = desc.selecteur;
    data.titre = document.title;
    data.texte = desc.texte;
  }

  var json = JSON.stringify(data, null, 1);
  var nom = 'annonce-' + Date.now() + '.json';

  function toast(msg, ok) {
    var e = document.createElement('div');
    e.textContent = msg;
    e.style.cssText = 'position:fixed;z-index:2147483647;top:12px;right:12px;max-width:24em;' +
      'padding:10px 14px;border-radius:6px;font:14px system-ui,sans-serif;color:#fff;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.35);background:' + (ok ? '#15803d' : '#b91c1c');
    document.body.appendChild(e);
    setTimeout(function () { e.remove(); }, 3500);
  }

  var telecharge = false;
  try {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    a.download = nom;
    document.body.appendChild(a); a.click(); a.remove();
    telecharge = true;
  } catch (e) { /* CSP : presse-papiers */ }

  (navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject()).then(
    function () { toast('Annonce capturée (' + data.source + ', ' + data.texte.length + ' car.)' + (telecharge ? ' → ' + nom : ' → presse-papiers'), true); },
    function () {
      if (telecharge) toast('Annonce capturée (' + data.source + ') → ' + nom, true);
      else toast('Capture impossible sur cette page', false);
    }
  );
})();
