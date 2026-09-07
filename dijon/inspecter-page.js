// Inspecteur de structure — favori de mise au point.
//
// À cliquer sur une page d'annonce quand la capture rate quelque chose. Il
// relève les blocs identifiables de la page — id, data-qa-id, data-test-id —
// avec la taille et le début de leur texte, et dépose le tout dans les
// téléchargements. C'est ce relevé qui permet d'écrire les bons sélecteurs,
// sans deviner : la page est construite en JavaScript, son HTML livré ne
// contient aucun de ces blocs.

(function () {
  var MAX = 45, EXTRAIT = 110;

  function identifiant(el) {
    if (el.id) return '#' + el.id;
    var attrs = ['data-qa-id', 'data-test-id', 'data-testid', 'itemprop', 'role'];
    for (var i = 0; i < attrs.length; i++) {
      var v = el.getAttribute(attrs[i]);
      if (v) return '[' + attrs[i] + '="' + v + '"]';
    }
    return el.tagName.toLowerCase();
  }

  var vus = [];
  var candidats = document.querySelectorAll(
    '[id], [data-qa-id], [data-test-id], [data-testid], [itemprop], main, article, section');
  for (var i = 0; i < candidats.length; i++) {
    var el = candidats[i];
    var txt = (el.innerText || '').trim();
    if (txt.length < 15) continue;
    vus.push({
      quoi: identifiant(el),
      balise: el.tagName.toLowerCase(),
      longueur: txt.length,
      // Ce qui trahit un bloc de caractéristiques.
      chiffres: /€/.test(txt) + ',' + /m²|m2/.test(txt) + ',' + /pi[eè]ces?/i.test(txt),
      extrait: txt.slice(0, EXTRAIT).replace(/\s+/g, ' ')
    });
  }
  // Les plus gros d'abord : le corps de l'annonce s'y trouve, ses conteneurs aussi.
  vus.sort(function (a, b) { return b.longueur - a.longueur; });

  var data = {
    type: 'inspection',
    url: location.href,
    site: location.hostname.replace(/^www\./, ''),
    capture: new Date().toISOString(),
    next_data: !!document.getElementById('__NEXT_DATA__'),
    titre: document.title,
    blocs: vus.slice(0, MAX)
  };
  var json = JSON.stringify(data, null, 1);
  var nom = 'inspection-' + Date.now() + '.json';

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
  } catch (e) { /* CSP */ }

  (navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject()).then(
    function () { toast(vus.length + ' blocs relevés' + (telecharge ? ' → ' + nom : ' → presse-papiers') + ' (et copiés)', true); },
    function () { toast(telecharge ? vus.length + ' blocs relevés → ' + nom : 'Relevé impossible', telecharge); }
  );
})();
