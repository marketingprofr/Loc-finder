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

Deux favoris à installer une fois pour toutes. Ouvrir `favoris.html` dans le
navigateur et faire glisser les deux boutons dans la barre de favoris
(`python favoris.py` régénère cette page après modification des scripts) :

- `capture-recherche.js` — sur une **page de résultats**, capture toutes les
  annonces affichées d'un seul clic : lien, prix, surface, pièces, description.
  C'est le point d'entrée normal : ouvrez votre recherche habituelle, faites
  défiler, cliquez le favori.
- `capture-annonce.js` — sur **une annonce ouverte**, capture sa description.
  À utiliser pour resserrer la position de celles qui vous intéressent. Il ne
  prend que l'annonce affichée : une page en contient une dizaine d'autres,
  dans le bloc « annonces similaires », dont les surfaces et les rues se
  mêleraient à celles du bien.

- `inspecter-page.js` — outil de mise au point. Sur une page d'annonce, relève
  les blocs identifiables et la taille de leur texte. À utiliser quand une
  capture rate ou ramène autre chose que l'annonce : le relevé dit quels
  sélecteurs écrire, ce que le HTML livré par le site ne permet pas de savoir
  puisque la page est construite en JavaScript.

Puis `python annonces.py` : les captures sont rangées dans `captures/`, et
`annonces.js` est écrit à côté de `data.js`.

Aucun des deux ne va chercher quoi que ce soit : ils lisent la page que le
navigateur a déjà reçue, une page à la fois, à votre rythme.

### Comment le bien est situé

Le texte prime sur la localisation déclarée : cocher « Dijon » gagne de la
visibilité, la description ment moins. Le script établit donc d'abord la
commune, puis cherche la rue **dans cette commune** — « rue des Vignes, à
Chenôve » ne doit pas atterrir à Dijon.

Les signaux, du plus au moins précis :

1. une rue, géocodée dans la commune retenue — 60 m si l'annonce donne un
   numéro (« au 12 rue de la Liberté »), 150 m si elle la donne comme adresse
   (« située rue X »), 300 m si elle ne fait que la citer ;
2. un quartier nommé (Montchapet, Fontaine d'Ouche…) — 500 m ;
3. un parc ou un arrêt cité — 400 m ;
4. la commune seule — 1 500 m ;
5. à défaut, la position donnée par l'annonce, volontairement floue — 800 m,
   ou 1 500 m si plusieurs annonces partagent la même coordonnée, auquel cas
   c'est le centre de la commune et non la position du bien.

Toutes les voies citées sont essayées, pas seulement la première : une annonce
mentionne souvent une rue voisine avant la sienne. Est retenue celle qui porte
un numéro, puis celle qui tombe dans la commune retenue, puis celle qui est
donnée comme l'adresse du bien (« située rue X ») plutôt que comme un voisinage
(« à 200 m de la rue X »). Les libellés couvrent aussi les résidences, clos,
hameaux et lotissements, ce qui oblige à deux garde-fous : un nom de voie doit
contenir un mot capitalisé, et pas seulement un nombre — sans quoi « rue calme
et arborée » et « terrain clos de 300 m² » passaient pour des adresses. Et
comme le géocodeur répond toujours quelque chose, sa réponse doit reprendre
tous les mots du nom demandé : à « clos de 300 » il proposait « Rue du Clos de
Tart », à l'autre bout de la ville.

Une commune n'est retenue que si le contexte la désigne : « à Chenôve » ou
« Chenôve 21300 » comptent, « proche de Chenôve » et « à 10 min de Dijon » sont
écartés — ils disent ce qu'il y a autour, pas où est le bien. Les noms les plus
longs l'emportent, sans quoi « Dijon » se reconnaîtrait dans
« Fontaine-lès-Dijon ».

Quand le texte contredit la déclaration, l'annonce est replacée et le signale,
dans la sortie du script comme dans son popup sur la carte.

Leboncoin ne met pas la description dans ses pages de résultats : la capture de
recherche donne le prix, la surface et la commune, jamais la rue. Le script
écrit donc `a_preciser.html`, la liste des annonces restées à la commune ou au
quartier près, du meilleur prix au m² au moins bon. Il suffit d'ouvrir celles
qui valent le coup et de cliquer le second favori sur chacune ; elles
descendent alors à 150 m, ou 60 m si l'annonce donne un numéro.

La carte dessine un point quand la position vaut 150 m, la zone d'incertitude
au-delà. `--sans-geo` traite les captures sans appel réseau.

## Paramètres

Tout est en tête de `build_dijon.py` (section CONFIG) : emprise, points « centre », 20 min max,
fenêtre 7h–20h, seuil de fréquence, taille des parcs, années DVF…

Les poids, la pente du score, les bornes de prix et le filtre budget se règlent dans la carte.

## Sources

- OpenStreetMap (Overpass) : supérettes/supermarchés, boulangeries, salles de sport, parcs/jardins publics ≥ 1 ha, bois ≥ 5 ha
- GTFS DiviaMobilités : https://transport.data.gouv.fr/datasets/gtfs-diviamobilites/
- DVF géolocalisé : https://files.data.gouv.fr/geo-dvf/latest/csv/ (ventes de maisons
  et d'appartements, ces derniers ramenés sur l'échelle « maison » par le
  coefficient `APPART_VERS_MAISON`, fixé à 1,32 d'après les ventes de la
  métropole, et que le script revérifie à chaque run)
- Adresses : api-adresse.data.gouv.fr (depuis la carte)
