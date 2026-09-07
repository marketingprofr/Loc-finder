# Loc-finder

Cartes de scoring d'emplacements pour acheter un logement : chaque ville est un
dossier autonome contenant un script de préparation des données et une carte
HTML qui s'ouvre sans serveur.

Le principe est toujours le même : on découpe la ville en une grille de 100 m,
on calcule pour chaque case le temps de marche vers ce qui compte (transport
vers le centre, commerces, sport, espaces verts) et le prix au m² observé, puis
la carte laisse régler les poids de chaque critère et le budget.

## Villes

| Ville | Dossier | Sources |
| --- | --- | --- |
| Dijon Métropole | [`dijon/`](dijon/) | OpenStreetMap, GTFS DiviaMobilités, DVF |

## Démarrage rapide

```
pip install -r requirements.txt
cd dijon
python build_dijon.py
```

Puis ouvrir `dijon/index.html` dans le navigateur.

Le script écrit `data.js` à côté de `index.html` et met les téléchargements en
cache dans `cache/`. Ces deux éléments ne sont pas versionnés : la carte n'est
utilisable qu'après avoir lancé le script au moins une fois.

Détails, paramètres et sources : voir le README de chaque ville.
