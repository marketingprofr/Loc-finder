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

1. Créer un favori dont l'adresse est la ligne `javascript:…` qui se trouve en
   bas de `capture-annonce.js` (dans Chrome : clic droit sur la barre de
   favoris → Ajouter un raccourci, coller la ligne dans le champ URL).
2. Ouvrir une annonce, cliquer le favori. Un fichier `annonce-….json` part
   dans les téléchargements.
3. `python annonces.py` — les captures sont rangées dans `captures/`, et
   `annonces.js` est écrit à côté de `data.js`.

Le script cherche dans le texte de l'annonce un nom de rue, de parc ou
d'arrêt, et retient l'indice le plus précis. La carte dessine un point quand
la position est sûre à 150 m près, un cercle quand elle ne l'est pas : une
annonce située « d'après le quartier » ne doit pas ressembler à une adresse.
`--sans-geo` traite les captures sans appel réseau, pour vérifier ce qui est
extrait du texte.

## Paramètres

Tout est en tête de `build_dijon.py` (section CONFIG) : emprise, points « centre », 20 min max,
fenêtre 7h–20h, seuil de fréquence, taille des parcs, années DVF…

Les poids, la pente du score, les bornes de prix et le filtre budget se règlent dans la carte.

## Sources

- OpenStreetMap (Overpass) : supérettes/supermarchés, boulangeries, salles de sport, parcs/jardins publics ≥ 1 ha, bois ≥ 5 ha
- GTFS DiviaMobilités : https://transport.data.gouv.fr/datasets/gtfs-diviamobilites/
- DVF géolocalisé : https://files.data.gouv.fr/geo-dvf/latest/csv/
- Adresses : api-adresse.data.gouv.fr (depuis la carte)
