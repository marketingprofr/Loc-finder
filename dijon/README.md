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

## Paramètres

Tout est en tête de `build_dijon.py` (section CONFIG) : emprise, points « centre », 20 min max,
fenêtre 7h–20h, seuil de fréquence, taille des parcs, années DVF…

Les poids, la pente du score, les bornes de prix et le filtre budget se règlent dans la carte.

## Sources

- OpenStreetMap (Overpass) : supérettes/supermarchés, boulangeries, salles de sport, parcs/jardins publics ≥ 1 ha, bois ≥ 5 ha
- GTFS DiviaMobilités : https://transport.data.gouv.fr/datasets/gtfs-diviamobilites/
- DVF géolocalisé : https://files.data.gouv.fr/geo-dvf/latest/csv/
- Adresses : api-adresse.data.gouv.fr (depuis la carte)
