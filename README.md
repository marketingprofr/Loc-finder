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

## Sur une machine neuve

Sous Windows, dans PowerShell. Git et Python d'abord, une seule fois — puis
**fermer et rouvrir PowerShell**, sans quoi les deux commandes restent
introuvables :

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
```

Ensuite :

```powershell
cd $HOME\Documents
git clone https://github.com/marketingprofr/Loc-finder.git
cd Loc-finder
pip install -r requirements.txt
python dijon\build_dijon.py
```

Le dernier prend quelques minutes : il télécharge OpenStreetMap, les horaires
Divia et les ventes DVF. Puis `Invoke-Item dijon\index.html`.

Trois choses ne sont pas dans le dépôt et ne suivent donc pas d'un ordinateur à
l'autre :

| | Comment le retrouver |
| --- | --- |
| `data.js`, `cache/` | reconstruits par `build_dijon.py` |
| les favoris de capture | `python dijon\favoris.py`, puis reglisser les boutons dans la barre du nouveau navigateur |
| `dijon/captures/` — vos annonces capturées | à recopier depuis l'ancien poste, sinon elles sont à recapturer |

## Démarrage rapide

```
pip install -r requirements.txt
python dijon/build_dijon.py
```

Puis ouvrir `dijon/index.html` dans le navigateur.

Le script écrit `data.js` à côté de `index.html` et met les téléchargements en
cache dans `dijon/cache/`, quel que soit le dossier depuis lequel il est lancé. Ces deux éléments ne sont pas versionnés : la carte n'est
utilisable qu'après avoir lancé le script au moins une fois.

Détails, paramètres et sources : voir le README de chaque ville.
