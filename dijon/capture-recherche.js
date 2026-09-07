// Capture d'une page de résultats — à installer comme favori, à côté de
// capture-annonce.js.
//
// Même principe : le script s'exécute dans VOTRE navigateur, sur une page de
// résultats que vous avez ouverte vous-même. Il ne lance aucune requête et ne
// tourne aucune page ; il lit ce que le navigateur a déjà reçu et affiché.
// Un clic capture toutes les annonces de la page courante.
//
// Les sites en Next.js (Leboncoin, entre autres) déposent leurs données dans
// une balise __NEXT_DATA__ : on la lit en priorité, elle est propre et
// complète. À défaut, on retombe sur le texte des cartes affichées.

(function () {
  var MAX_PROFONDEUR = 14, MAX_ANNONCES = 200;

  // Cherche récursivement les objets qui ressemblent à une annonce.
  function collecte(obj, out, vus, prof) {
    if (!obj || typeof obj !== 'object' || prof > MAX_PROFONDEUR || out.length >= MAX_ANNONCES) return out;
    if (vus.indexOf(obj) !== -1) return out;
    vus.push(obj);
    if (Array.isArray(obj)) {
      for (var i = 0; i < obj.length; i++) collecte(obj[i], out, vus, prof + 1);
      return out;
    }
    if ((obj.list_id || obj.listId) && (obj.subject || obj.title)) { out.push(obj); return out; }
    for (var k in obj) if (Object.prototype.hasOwnProperty.call(obj, k)) collecte(obj[k], out, vus, prof + 1);
    return out;
  }

  function normalise(a) {
    var at = {}, attrs = a.attributes || [];
    for (var i = 0; i < attrs.length; i++) {
      if (attrs[i] && attrs[i].key) at[attrs[i].key] = attrs[i].value_label || attrs[i].value;
    }
    var loc = a.location || {};
    var id = String(a.list_id || a.listId || '');
    return {
      url: a.url || (id ? 'https://www.leboncoin.fr/ad/ventes_immobilieres/' + id : ''),
      id: id,
      titre: a.subject || a.title || '',
      // Le corps de l'annonce est souvent présent dès la liste : c'est lui qui
      // porte les indices de lieu utilisables.
      texte: [a.subject, a.body, loc.city, loc.zipcode].filter(Boolean).join('\n'),
      prix: Array.isArray(a.price) ? a.price[0] : a.price,
      attributs: at,
      ville: loc.city || '',
      cp: loc.zipcode || '',
      lat: loc.lat, lon: loc.lng,
      date: a.index_date || a.first_publication_date || ''
    };
  }

  // Repli : ce qui est affiché à l'écran.
  function cartes() {
    var vus = {}, out = [];
    var liens = document.querySelectorAll('a[href*="/ad/"], a[href*="/annonces/"], a[href*="/annonce"]');
    for (var i = 0; i < liens.length && out.length < MAX_ANNONCES; i++) {
      var href = liens[i].href.split('?')[0];
      if (!href || vus[href]) continue;
      vus[href] = 1;
      var bloc = liens[i].closest('article, li, [data-test-id], [data-qa-id]') || liens[i];
      var txt = (bloc.innerText || '').replace(/[ \t]+/g, ' ').trim();
      if (txt.length < 25) continue;
      out.push({ url: href, id: '', titre: txt.split('\n')[0].slice(0, 140), texte: txt, attributs: {} });
    }
    return out;
  }

  var annonces = [], source = 'cartes';
  try {
    var nd = document.getElementById('__NEXT_DATA__');
    if (nd && nd.textContent) {
      var brut = collecte(JSON.parse(nd.textContent), [], [], 0);
      if (brut.length) { annonces = brut.map(normalise); source = '__NEXT_DATA__'; }
    }
  } catch (e) { /* structure inattendue : on passera par les cartes */ }
  if (!annonces.length) annonces = cartes();

  var data = {
    type: 'recherche',
    url: location.href,
    site: location.hostname.replace(/^www\./, ''),
    source: source,
    capture: new Date().toISOString(),
    annonces: annonces
  };
  var json = JSON.stringify(data);
  var nom = 'annonce-recherche-' + Date.now() + '.json';

  function toast(msg, ok) {
    var e = document.createElement('div');
    e.textContent = msg;
    e.style.cssText = 'position:fixed;z-index:2147483647;top:12px;right:12px;max-width:24em;' +
      'padding:10px 14px;border-radius:6px;font:14px system-ui,sans-serif;color:#fff;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.35);background:' + (ok ? '#15803d' : '#b91c1c');
    document.body.appendChild(e);
    setTimeout(function () { e.remove(); }, 3500);
  }

  if (!annonces.length) { toast('Aucune annonce trouvée sur cette page', false); return; }

  var telecharge = false;
  try {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    a.download = nom;
    document.body.appendChild(a); a.click(); a.remove();
    telecharge = true;
  } catch (e) { /* CSP : presse-papiers */ }

  (navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject()).then(
    function () { toast(annonces.length + ' annonces capturées (' + source + ')' + (telecharge ? ' → ' + nom : ' → presse-papiers'), true); },
    function () {
      if (telecharge) toast(annonces.length + ' annonces capturées → ' + nom, true);
      else toast('Capture impossible sur cette page', false);
    }
  );
})();

