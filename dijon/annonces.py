#!/usr/bin/env python3
"""
Situe des annonces immobilières sur la carte, à partir de leur texte.

Usage :
    python annonces.py              → lit les captures, écrit annonces.js
    python annonces.py --sans-geo   → sans appel réseau (diagnostic)

Le principe : le favori capture-annonce.js enregistre le texte d'une annonce
que vous avez ouverte. Ce script relit ces captures, en extrait prix, surface,
type, et surtout cherche dans le texte de quoi situer le bien — un nom de rue,
un parc, un arrêt. C'est volontairement le texte libre qui sert de source :
le champ « localisation » d'une annonce est un levier de visibilité, la
description l'est beaucoup moins.

Chaque annonce sort avec une précision honnête : un numéro de rue ne vaut pas
un nom de commune, et la carte les dessine différemment.
"""
import glob
import json
import math
import os
import re
import shutil
import sys
import time
import unicodedata
from collections import Counter

import requests

# =============================== CONFIG ======================================

BBOX = (47.24, 4.93, 47.40, 5.16)          # même emprise que build_dijon.py
BIAIS = (47.3231, 5.0321)                  # Darcy, pour orienter le géocodage

CAPTURES_DIR = "captures"                  # les captures y sont archivées
DATA_JS = "data.js"
OUTPUT = "annonces.js"

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
USER_AGENT = "loc-finder/1.0 (+https://github.com/marketingprofr/Loc-finder)"

# Rayon d'incertitude affiché sur la carte, par type d'indice.
PRECISION_M = {
    "housenumber": 60,
    "street": 150,
    "repere": 400,        # parc, arrêt, quartier nommé
    "annonceur": 800,     # position donnée par l'annonce, volontairement floue
    "municipality": 1500,
}

# Une même coordonnée revenant sur plusieurs annonces n'est pas la position des
# biens : c'est le centre de la commune. On la traite comme telle.
CENTROIDE_MIN = 3

# Bornes de vraisemblance, pour ne pas retenir n'importe quel nombre.
PRIX_MIN, PRIX_MAX = 30_000, 3_000_000
SURFACE_MIN, SURFACE_MAX = 15, 600

VOIE = (r"(?:rue|avenue|av\.|boulevard|bd|impasse|all[ée]e|place|chemin|route|"
        r"quai|cours|square|passage|sentier|mail|faubourg|montée|esplanade)")
MOT = r"[A-ZÉÈÀÂÔÎÇ][\wÀ-ÿ'’\-]*"
LIAISON = r"(?:de |du |des |la |le |les |d'|l'|d’|l’)"
RE_VOIE = re.compile(rf"\b{VOIE}\s+(?:{LIAISON})*{MOT}(?:\s+(?:{LIAISON})*{MOT}){{0,3}}", re.I)

SEP = "[ \u00a0\u202f.]"           # espace, insécable, fine insécable, point — jamais \n
NOMBRE_FR = rf"\d{{1,3}}(?:{SEP}?\d{{3}})+"
RE_PRIX_LABEL = re.compile(rf"prix[^\d€\n]{{0,20}}({NOMBRE_FR})", re.I)
RE_PRIX = re.compile(rf"({NOMBRE_FR})\s*€")
RE_SURFACE = re.compile(r"(\d{2,4}(?:[.,]\d+)?)\s*m\s*(?:²|2\b|\^2)", re.I)
RE_PIECES = re.compile(r"(\d+)\s*pi[eè]ces?", re.I)
RE_TN = re.compile(r"\b[TF](\d)\b")


def log(msg):
    print(msg, flush=True)


def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def nombre(s):
    """'185 000' ou '185.000' → 185000.0 ; None si illisible."""
    s = re.sub(r"[\s  .]", "", s).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def dans_bbox(lat, lon):
    return BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]


# ============================ EXTRACTION =====================================

def extrait_prix(texte):
    """Le prix affiché, en préférant celui qui est explicitement étiqueté."""
    for regex in (RE_PRIX_LABEL, RE_PRIX):
        valeurs = [v for v in (nombre(m.group(1)) for m in regex.finditer(texte))
                   if v is not None and PRIX_MIN <= v <= PRIX_MAX]
        if valeurs:
            # plusieurs prix (honoraires, mensualités de prêt…) : le bien est le plus élevé
            return int(max(valeurs))
    return None


def extrait_surface(texte):
    """Surface habitable : on écarte les m² qui suivent un mot de terrain."""
    candidates = []
    for m in RE_SURFACE.finditer(texte):
        avant = sans_accents(texte[max(0, m.start() - 30):m.start()])
        if re.search(r"terrain|parcelle|jardin|cour|garage|cave|balcon|terrasse", avant):
            continue
        v = nombre(m.group(1))
        if v is not None and SURFACE_MIN <= v <= SURFACE_MAX:
            candidates.append(v)
    return max(candidates) if candidates else None


def extrait_pieces(texte):
    m = RE_PIECES.search(texte)
    if m:
        return int(m.group(1))
    m = RE_TN.search(texte)
    return int(m.group(1)) if m else None


def extrait_type(texte):
    t = sans_accents(texte)
    maison = len(re.findall(r"\bmaison|pavillon|villa|longere\b", t))
    appart = len(re.findall(r"\bappartement|appart\b|studio|duplex", t))
    if maison > appart:
        return "maison"
    if appart > maison:
        return "appartement"
    return None


# ============================ LOCALISATION ===================================

def charge_reperes(chemin=DATA_JS):
    """Parcs, arrêts et commerces nommés de data.js → {nom normalisé: (lat, lon)}."""
    if not os.path.exists(chemin):
        log(f"  {chemin} absent : les repères (parcs, arrêts) ne serviront pas")
        return {}
    with open(chemin, encoding="utf-8") as f:
        brut = f.read()
    data = json.loads(brut[brut.index("{"):brut.rstrip().rstrip(";").rindex("}") + 1])
    reperes = {}
    for s in data.get("stops", []):
        nom = s[0]
        if len(nom) >= 4:
            reperes.setdefault(sans_accents(nom), (nom, (s[4], s[5])))
    # Les parcs n'ont pas de coordonnées dans data.js ; on les géocodera au besoin.
    for nom in data.get("parks", []):
        if len(nom) >= 5 and nom.lower() not in ("parc", "bois", "jardin"):
            reperes.setdefault(sans_accents(nom), (nom, None))
    return reperes


def indices(texte, reperes):
    """Indices de localisation trouvés dans le texte, du plus précis au moins précis."""
    trouves = []
    for m in RE_VOIE.finditer(texte):
        libelle = re.sub(r"\s+", " ", m.group(0)).strip(" ,.;:")
        if len(libelle) > 8:
            trouves.append(("voie", libelle, None))
    t = sans_accents(texte)
    for nom_norm, (nom, coord) in reperes.items():
        if nom_norm in t:
            trouves.append(("repere", nom, coord))
    # dédoublonnage en gardant l'ordre
    vus, sortie = set(), []
    for kind, libelle, coord in trouves:
        if libelle.lower() not in vus:
            vus.add(libelle.lower())
            sortie.append((kind, libelle, coord))
    return sortie


def geocode(question, session):
    """→ (lat, lon, type BAN, libellé) ou None."""
    params = {"q": question, "limit": 1, "lat": BIAIS[0], "lon": BIAIS[1]}
    try:
        r = session.get(BAN_URL, params=params, timeout=30)
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception as e:  # noqa
        log(f"    géocodage indisponible ({e})")
        return None
    if not feats:
        return None
    f = feats[0]
    lon, lat = f["geometry"]["coordinates"]
    p = f["properties"]
    if not dans_bbox(lat, lon) or p.get("score", 0) < 0.4:
        return None
    return lat, lon, p.get("type", "street"), p.get("label", question)


def situe(texte, reperes, session):
    """Retient l'indice le plus précis qu'on sache placer."""
    for kind, libelle, coord in indices(texte, reperes):
        if kind == "repere" and coord:
            return {"lat": coord[0], "lon": coord[1], "precision": PRECISION_M["repere"],
                    "indice": libelle, "source": "repère"}
        if session is None:
            continue
        r = geocode(f"{libelle}, Dijon", session)
        if r:
            lat, lon, typ, label = r
            precision = (PRECISION_M["repere"] if kind == "repere"
                         else PRECISION_M.get(typ, PRECISION_M["street"]))
            return {"lat": lat, "lon": lon, "precision": precision,
                    "indice": label, "source": "adresse" if kind == "voie" else "repère"}
    return None


# ============================== CAPTURES =====================================

def entier(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def reel(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def type_annonce(libelle):
    t = sans_accents(str(libelle or ""))
    if "maison" in t or "villa" in t or "pavillon" in t:
        return "maison"
    if "appartement" in t or "appart" in t:
        return "appartement"
    return None


def deplie(captures):
    """Aplatit captures d'annonce et captures de recherche en une liste unique.

    Une capture de recherche apporte déjà prix, surface et nombre de pièces sous
    forme structurée : inutile de les redécouvrir dans le texte. Ce qu'elle
    n'apporte pas, c'est une position fiable, et c'est là que le texte sert.
    """
    out = []
    for c in captures:
        if c.get("type") == "recherche":
            for a in c.get("annonces", []):
                at = a.get("attributs") or {}
                out.append({
                    "url": a.get("url"), "site": c.get("site"),
                    "titre": (a.get("titre") or "").strip()[:120],
                    "texte": a.get("texte") or "",
                    "capture": (c.get("capture") or "")[:10],
                    "prix": entier(a.get("prix")),
                    "surface": reel(at.get("square")),
                    "pieces": entier(at.get("rooms")),
                    "type": type_annonce(at.get("real_estate_type")),
                    "ville": a.get("ville"),
                    "lat_annonceur": reel(a.get("lat")), "lon_annonceur": reel(a.get("lon")),
                })
        else:
            out.append({
                "url": c.get("url"), "site": c.get("site"),
                "titre": (c.get("titre") or "").strip()[:120],
                "texte": c.get("texte") or "",
                "capture": (c.get("capture") or "")[:10],
                "prix": None, "surface": None, "pieces": None, "type": None,
                "ville": None, "lat_annonceur": None, "lon_annonceur": None,
            })
    return out


def centroides(annonces):
    coords = Counter((round(a["lat_annonceur"], 4), round(a["lon_annonceur"], 4))
                     for a in annonces if a.get("lat_annonceur") and a.get("lon_annonceur"))
    return {k for k, n in coords.items() if n >= CENTROIDE_MIN}


def dossiers_source():
    maison = os.path.expanduser("~")
    return [os.path.join(maison, "Downloads"), os.path.join(maison, "Téléchargements"), "."]


def archive_captures():
    """Déplace les annonce-*.json trouvés vers captures/ et renvoie tout le contenu."""
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    deplaces = 0
    for d in dossiers_source():
        if not os.path.isdir(d) or os.path.abspath(d) == os.path.abspath(CAPTURES_DIR):
            continue
        for src in glob.glob(os.path.join(d, "annonce-*.json")):
            dst = os.path.join(CAPTURES_DIR, os.path.basename(src))
            if not os.path.exists(dst):
                shutil.move(src, dst)
                deplaces += 1
    if deplaces:
        log(f"  {deplaces} nouvelle(s) capture(s) rangée(s) dans {CAPTURES_DIR}/")
    captures = []
    for p in sorted(glob.glob(os.path.join(CAPTURES_DIR, "annonce-*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                captures.append(json.load(f))
        except Exception as e:  # noqa
            log(f"  capture illisible, ignorée : {os.path.basename(p)} ({e})")
    return captures


# ================================ MAIN =======================================

def main():
    avec_geo = "--sans-geo" not in sys.argv
    session = None
    if avec_geo:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

    log("Captures…")
    captures = archive_captures()
    if not captures:
        log("  aucune capture. Installez les favoris (voir README), puis cliquez-les")
        log("  sur une page de résultats ou sur une annonce ouverte.")
        return
    brutes = deplie(captures)
    # Une même annonce vue en liste puis ouverte : on garde la capture la plus
    # fournie, celle de la page de l'annonce, qui porte la description entière.
    # On garde le texte le plus long, mais on complète champ par champ : la ligne
    # de recherche porte le prix, la surface et la position de l'annonceur, que la
    # page de l'annonce, elle, ne donne pas sous forme structurée.
    COMPLETABLES = ("prix", "surface", "pieces", "type", "ville",
                    "lat_annonceur", "lon_annonceur", "titre", "site", "capture")
    par_url = {}
    for a in brutes:
        cle = a.get("url") or id(a)
        if cle not in par_url:
            par_url[cle] = a
            continue
        b = par_url[cle]
        garde, autre = (a, b) if len(a["texte"]) > len(b["texte"]) else (b, a)
        for champ in COMPLETABLES:
            if not garde.get(champ):
                garde[champ] = autre.get(champ)
        par_url[cle] = garde
    log(f"  {len(par_url)} annonce(s) distincte(s) sur {len(brutes)} ligne(s) capturée(s)")

    log("Repères…")
    reperes = charge_reperes()
    log(f"  {len(reperes)} noms d'arrêts et de parcs utilisables")
    flous = centroides(list(par_url.values()))
    if flous:
        log(f"  {len(flous)} coordonnée(s) partagée(s) par plusieurs annonces : "
            f"traitées comme des centres de commune")

    log("Lecture des annonces…")
    annonces, sans_position = [], 0
    for c in par_url.values():
        texte = c["texte"]
        a = {
            "url": c["url"], "site": c["site"], "titre": c["titre"], "capture": c["capture"],
            # La recherche fournit déjà ces champs ; sinon on les tire du texte.
            "type": c["type"] or extrait_type(texte),
            "prix": c["prix"] or extrait_prix(texte),
            "surface": c["surface"] or extrait_surface(texte),
            "pieces": c["pieces"] or extrait_pieces(texte),
        }
        pos = situe(texte, reperes, session)
        if pos is None and c["lat_annonceur"] and c["lon_annonceur"]:
            cle = (round(c["lat_annonceur"], 4), round(c["lon_annonceur"], 4))
            centre = cle in flous
            pos = {"lat": c["lat_annonceur"], "lon": c["lon_annonceur"],
                   "precision": PRECISION_M["municipality" if centre else "annonceur"],
                   "indice": (f"centre de {c['ville']}" if centre
                              else f"position indiquée par l'annonce ({c['ville'] or '?'})"),
                   "source": "annonceur"}
        if pos is None and c["ville"] and session is not None:
            r = geocode(c["ville"], session)
            if r:
                pos = {"lat": r[0], "lon": r[1], "precision": PRECISION_M["municipality"],
                       "indice": r[3], "source": "commune"}
        if pos:
            a.update(lat=round(pos["lat"], 5), lon=round(pos["lon"], 5),
                     precision=pos["precision"], indice=pos["indice"], source=pos["source"])
            annonces.append(a)
            ppm2 = f"{a['prix'] / a['surface']:.0f} €/m²" if a["prix"] and a["surface"] else "—"
            log(f"  ✓ {a['titre'][:40]:40s} {str(a['prix'] or '—'):>9s} € · {ppm2:>10s}"
                f" · ±{pos['precision']:>4} m · {pos['indice'][:38]}")
        else:
            sans_position += 1
            log(f"  ? {a['titre'][:40]:40s} aucun indice de lieu exploitable")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("window.ANNONCES = ")
        json.dump(annonces, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    par_precision = Counter(a["precision"] for a in annonces)
    log(f"OK → {OUTPUT} : {len(annonces)} annonce(s) placée(s), {sans_position} sans position.")
    for prec in sorted(par_precision):
        log(f"  ±{prec:>4} m : {par_precision[prec]} annonce(s)")
    if par_precision.get(PRECISION_M["municipality"]) or par_precision.get(PRECISION_M["annonceur"]):
        log("  Les moins précises se resserrent en ouvrant l'annonce et en la recapturant :")
        log("  la description entière contient souvent une rue ou un repère.")


if __name__ == "__main__":
    main()
