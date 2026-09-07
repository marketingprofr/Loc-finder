# Où acheter — Dijon Métropole

Deux fichiers :

- `build_dijon.py` — télécharge les données (OSM, GTFS Divia, DVF), score une grille de 100 m et écrit `data.js`
- `index.html` — la carte (s'ouvre directement dans le navigateur, sans serveur)

## Lancer

```
pip install requests numpy pandas scipy
python build_dijon.py
```

Puis ouvrir `index.html`. Les téléchargements sont mis en cache dans `cache/` :
relancer le script après un changement de paramètre ne retélécharge rien.
`python build_dijon.py --no-dvf` pour aller plus vite sans les prix.

## Placer des annonces sur la carte

`annonces.py` situe des annonces immobilières d'après leur texte, et la carte
les affiche avec un filtre prix / surface / type.

Il n'y a pas d'API publique chez SeLoger ou Leboncoin, et leurs conditions
interdisent l'extraction automatisée : rien ici ne va chercher les pages tout
seul. La capture se fait depuis votre navigateur, une annonce à la fois.

Deux favoris à installer, dont l'adresse est la ligne `javascript:…` qui se
trouve en bas de chaque fichier (dans Chrome : clic droit sur la barre de
favoris → Ajouter un raccourci, coller la ligne dans le champ URL) :

- `capture-recherche.js` — sur une **page de résultats**, capture toutes les
  annonces affichées d'un seul clic : lien, prix, surface, pièces, description.
  C'est le point d'entrée normal : ouvrez votre recherche habituelle, faites
  défiler, cliquez le favori.
- `capture-annonce.js` — sur **une annonce ouverte**, capture sa description
  entière. À utiliser pour resserrer la position de celles qui vous intéressent.

Puis `python annonces.py` : les captures sont rangées dans `captures/`, et
`annonces.js` est écrit à côté de `data.js`.

Aucun des deux ne va chercher quoi que ce soit : ils lisent la page que le
navigateur a déjà reçue, une page à la fois, à votre rythme.

Pour situer le bien, le script cherche dans le texte un nom de rue, de parc ou
d'arrêt et retient l'indice le plus précis. À défaut il retombe sur la position
donnée par l'annonce, qui est volontairement floue — et si plusieurs annonces
partagent la même coordonnée, il en déduit que c'est le centre de la commune
et le dit. La carte dessine un point quand la position vaut 150 m, la zone
d'incertitude au-delà. `--sans-geo` traite les captures sans appel réseau.

## Paramètres

Tout est en tête de `build_dijon.py` (section CONFIG) : emprise, points « centre », 20 min max,
fenêtre 7h–20h, seuil de fréquence, taille des parcs, années DVF…

Les poids, la pente du score, les bornes de prix et le filtre budget se règlent dans la carte.

## Sources

- OpenStreetMap (Overpass) : supérettes/supermarchés, boulangeries, salles de sport, parcs/jardins publics ≥ 1 ha, bois ≥ 5 ha
- GTFS DiviaMobilités : https://transport.data.gouv.fr/datasets/gtfs-diviamobilites/
- DVF géolocalisé : https://files.data.gouv.fr/geo-dvf/latest/csv/ (ventes de maisons
  et d'appartements, ces derniers ramenés sur l'échelle « maison » par le
  coefficient `APPART_VERS_MAISON`, que le script mesure et commente à chaque run)
- Adresses : api-adresse.data.gouv.fr (depuis la carte)
