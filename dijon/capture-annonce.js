// Capture d'annonce — à installer comme favori dans le navigateur.
//
// Ce script s'exécute dans VOTRE navigateur, sur une page que vous avez
// ouverte vous-même, une annonce à la fois. Il ne va rien chercher tout seul :
// il se contente de récupérer le texte déjà affiché à l'écran et de
// l'enregistrer, pour que annonces.py puisse le lire ensuite.
//
// Installation : voir le README. La version minifiée, à coller dans l'adresse
// du favori, est en bas de ce fichier.

(function () {
  var data = {
    url: location.href,
    site: location.hostname.replace(/^www\./, ''),
    titre: document.title,
    capture: new Date().toISOString(),
    texte: document.body.innerText.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').slice(0, 30000)
  };
  var json = JSON.stringify(data, null, 1);
  var nom = 'annonce-' + Date.now() + '.json';

  function toast(msg, ok) {
    var e = document.createElement('div');
    e.textContent = msg;
    e.style.cssText = 'position:fixed;z-index:2147483647;top:12px;right:12px;max-width:22em;' +
      'padding:10px 14px;border-radius:6px;font:14px system-ui,sans-serif;color:#fff;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.35);background:' + (ok ? '#15803d' : '#b91c1c');
    document.body.appendChild(e);
    setTimeout(function () { e.remove(); }, 3000);
  }

  // Deux voies, parce que certains sites bloquent l'une ou l'autre : on écrit
  // un fichier dans les téléchargements, et on copie aussi dans le presse-papiers.
  var telecharge = false;
  try {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    a.download = nom;
    document.body.appendChild(a);
    a.click();
    a.remove();
    telecharge = true;
  } catch (e) { /* CSP : on se rabat sur le presse-papiers */ }

  var copie = navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject();
  copie.then(
    function () { toast(telecharge ? 'Annonce capturée → ' + nom + ' (et copiée)' : 'Annonce copiée dans le presse-papiers', true); },
    function () {
      if (telecharge) toast('Annonce capturée → ' + nom, true);
      else toast('Capture impossible sur cette page — copiez le texte à la main', false);
    }
  );
})();

// --- version favori (tout sur une ligne, préfixée par javascript:) ---------
// javascript:(function(){var d={url:location.href,site:location.hostname.replace(/^www\./,''),titre:document.title,capture:new Date().toISOString(),texte:document.body.innerText.replace(/[ \t]+/g,' ').replace(/\n{3,}/g,'\n\n').slice(0,30000)},j=JSON.stringify(d,null,1),n='annonce-'+Date.now()+'.json';function t(m,o){var e=document.createElement('div');e.textContent=m;e.style.cssText='position:fixed;z-index:2147483647;top:12px;right:12px;max-width:22em;padding:10px 14px;border-radius:6px;font:14px system-ui,sans-serif;color:#fff;box-shadow:0 2px 12px rgba(0,0,0,.35);background:'+(o?'#15803d':'#b91c1c');document.body.appendChild(e);setTimeout(function(){e.remove()},3000)}var dl=false;try{var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([j],{type:'application/json'}));a.download=n;document.body.appendChild(a);a.click();a.remove();dl=true}catch(e){}(navigator.clipboard?navigator.clipboard.writeText(j):Promise.reject()).then(function(){t(dl?'Annonce capturée → '+n+' (et copiée)':'Annonce copiée dans le presse-papiers',true)},function(){t(dl?'Annonce capturée → '+n:'Capture impossible — copiez le texte à la main',dl)})})();
