#!/usr/bin/env python3
"""
Situe des annonces immobilières sur la carte, à partir de leur texte.

Usage :
    python annonces.py                → lit les captures, écrit annonces.js
    python annonces.py --diagnostic   → montre ce qui est lu dans chaque annonce
    python annonces.py --sans-geo     → sans appel réseau

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
import html
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
    "repere": 400,        # parc, arrêt nommé
    "quartier": 500,      # quartier nommé
    "annonceur": 800,     # position donnée par l'annonce, volontairement floue
    "municipality": 1500,
}

# Une même coordonnée revenant sur plusieurs annonces n'est pas la position des
# biens : c'est le centre de la commune. On la traite comme telle.
CENTROIDE_MIN = 3

# Bornes de vraisemblance, pour ne pas retenir n'importe quel nombre.
PRIX_MIN, PRIX_MAX = 30_000, 3_000_000
SURFACE_MIN, SURFACE_MAX = 15, 600

VOIE = (r"(?:rue|ruelle|avenue|av\.|boulevard|bd|bld|impasse|imp\.|all[ée]e|place|pl\.|"
        r"chemin|ch\.|route|rte|quai|cours|square|passage|sentier|venelle|mail|faubourg|"
        r"mont[ée]e|esplanade|promenade|parvis|traverse|cit[ée]|r[ée]sidence|clos|hameau|"
        r"lotissement|rond-point|voie)")
# Un mot de nom de voie commence par une majuscule ou un chiffre — « rue du
# 8 Mai 1945 ». Sans cette exigence, et le motif étant insensible à la casse,
# « rue calme et arborée » passait pour une adresse.
MOT = r"[A-ZÉÈÀÂÔÎÇÜŒ0-9][\wÀ-ÿ'’\-]*"
LIAISON = r"(?:de |du |des |la |le |les |d'|l'|d’|l’)"
RE_VOIE = re.compile(
    r"(?:(?P<num>\d{1,4})\s*(?P<suf>bis|ter|quater)?[\s,]+)?"
    rf"(?P<type>(?i:{VOIE}))\s+"
    rf"(?P<nom>(?:{LIAISON})*{MOT}(?:\s+(?:{LIAISON})*{MOT}){{0,3}})")

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

# Une commune citée après ces mots ne dit pas où est le bien, mais ce qu'il y a
# autour : « à 10 min de Dijon » se lit justement comme « pas à Dijon ».
MARQUEURS_NEGATIFS = (r"(?:proche|pres|a proximite|aux portes|limite|acces|direction|vers|"
                      r"non loin|face|a deux pas|a quelques (?:pas|minutes|metres)|"
                      # une distance chiffrée, en mètres comme en minutes : « à 200 m de
                      # la rue X » désigne une voisine, pas l'adresse du bien
                      r"(?:a|de) \d+ ?(?:m|metres?|min|mn|minutes?|km|kilometres?)\b)")

# À l'inverse, ce qui introduit l'adresse du bien lui-même.
MARQUEURS_ADRESSE = r"(?:situee?|sise?|adresse|se trouve|implantee?|donnant|au)"
# Ceux-ci, au contraire, désignent l'emplacement du bien.
MARQUEURS_POSITIFS = (r"(?:a|sur|dans|secteur|commune de|ville de|situee? a|situe a|"
                      r"centre de|centre|quartier de|quartier|au coeur de|coeur de)")

RE_CODE_POSTAL = re.compile(r"\b(\d{5})\b")


def charge_geo(chemin=DATA_JS):
    """Référentiel de lieux tiré de data.js : communes, quartiers, arrêts, parcs.

    → {"communes": {clé: (nom, lat, lon)}, "quartiers": …, "reperes": …}
    Les clés sont normalisées sans accents, pour être cherchées dans le texte.
    """
    vide = {"communes": {}, "quartiers": {}, "reperes": {}}
    if not os.path.exists(chemin):
        log(f"  {chemin} absent : aucun référentiel de lieux")
        return vide
    with open(chemin, encoding="utf-8") as f:
        brut = f.read()
    data = json.loads(brut[brut.index("{"):brut.rstrip().rstrip(";").rindex("}") + 1])

    def table(entrees, long_min):
        t = {}
        for e in entrees:
            nom = e[0] if isinstance(e, (list, tuple)) else e
            lat = e[1] if isinstance(e, (list, tuple)) and len(e) > 2 else None
            lon = e[2] if isinstance(e, (list, tuple)) and len(e) > 2 else None
            if nom and len(nom) >= long_min:
                t.setdefault(sans_accents(nom), (nom, lat, lon))
        return t

    geo = {
        "communes": table(data.get("communes", []), 3),
        "quartiers": table(data.get("quartiers", []), 4),
        "reperes": {},
    }
    # Arrêts et parcs : des points de repère cités en clair dans les annonces.
    reperes = [[s[0], s[4], s[5]] for s in data.get("stops", []) if len(s[0]) >= 4]
    reperes += [p for p in data.get("parks", [])
                if isinstance(p, (list, tuple)) and p[0].lower() not in ("parc", "bois", "jardin")]
    geo["reperes"] = table(reperes, 5)
    # Un arrêt de bus porte souvent le nom de sa commune — l'arrêt LONGVIC, à
    # Longvic. Le retenir comme repère placerait le bien sur un abribus, annoncé
    # à 400 m près, alors que le seul signal est le nom de la commune.
    for cle in list(geo["communes"]):
        geo["reperes"].pop(cle, None)
        geo["quartiers"].pop(cle, None)
    if not geo["communes"]:
        log("  data.js ne contient pas de communes : relancer build_dijon.py "
            "pour pouvoir corriger une localisation déclarée")
    return geo


# Le trait d'union et l'apostrophe font partie du nom : sans les exclure des
# bords, « Dijon » se reconnaît à l'intérieur de « Fontaine-lès-Dijon ».
BORD_G, BORD_D = r"(?<![a-z0-9'’\-])", r"(?![a-z0-9'’\-])"


def occurrences(t_norm, table):
    """Noms de `table` trouvés dans le texte, du plus long au plus court.

    Les plus longs sont servis d'abord et réservent leur emplacement : sinon
    « Fontaine-lès-Dijon » et « Dijon » se disputeraient le même passage, et
    l'annonce partirait dans la mauvaise commune.
    """
    pris = []
    for cle in sorted(table, key=len, reverse=True):
        valeur = table[cle]
        for m in re.finditer(BORD_G + re.escape(cle) + BORD_D, t_norm):
            if any(m.start() < fin and debut < m.end() for debut, fin in pris):
                continue
            pris.append((m.start(), m.end()))
            yield cle, valeur, m


def commune_du_texte(t_norm, geo):
    """Commune déduite du contenu de l'annonce.

    → (nom, lat, lon, force) où force vaut "forte" ou "faible", ou None.
    """
    fortes, faibles = Counter(), Counter()
    coords = {}
    for cle, (nom, lat, lon), m in occurrences(t_norm, geo["communes"]):
        avant = t_norm[max(0, m.start() - 30):m.start()]
        apres = t_norm[m.end():m.end() + 14]
        coords[nom] = (lat, lon)
        if re.search(MARQUEURS_NEGATIFS + r"[ ,;:'’a-z]{0,14}$", avant):
            continue
        # « à Chenôve », « secteur Chenôve », ou « Chenôve 21300 » : le bien y est.
        if re.search(MARQUEURS_POSITIFS + r"[ ,]+$", avant) or re.match(r"[ ,]*\d{5}\b", apres):
            fortes[nom] += 1
        else:
            faibles[nom] += 1
    for table, force in ((fortes, "forte"), (faibles, "faible")):
        if table:
            nom = table.most_common(1)[0][0]
            return nom, coords[nom][0], coords[nom][1], force
    return None


def codes_postaux(t_norm, session):
    """Communes déduites des codes postaux cités. Nécessite le réseau."""
    if session is None:
        return []
    out = []
    for cp in dict.fromkeys(RE_CODE_POSTAL.findall(t_norm)):
        r = geocode(cp, session, type_ban="municipality")
        if r:
            out.append((r[3], r[0], r[1]))
    return out


_CACHE_GEO = {}
# Une panne de géocodeur se voyait à peine : chaque échec passait dans une ligne
# noyée au milieu des annonces, et le résultat final n'en disait rien.
_STATS = {"appels": 0, "reseau": 0, "sans_resultat": 0}


def geocode(question, session, type_ban=None):
    """→ (lat, lon, type BAN, libellé, score, commune) ou None.

    Les réponses sont retenues : une même rue revient d'une annonce à l'autre.
    """
    cle = (question, type_ban)
    if cle in _CACHE_GEO:
        return _CACHE_GEO[cle]
    params = {"q": question, "limit": 1, "lat": BIAIS[0], "lon": BIAIS[1]}
    if type_ban:
        params["type"] = type_ban
    _STATS["appels"] += 1
    try:
        r = session.get(BAN_URL, params=params, timeout=30)
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception as e:  # noqa
        _STATS["reseau"] += 1
        if _STATS["reseau"] <= 3:
            log(f"    géocodage indisponible ({e})")
        return None
    if not feats:
        _STATS["sans_resultat"] += 1
    reponse = None
    if feats:
        f = feats[0]
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        if dans_bbox(lat, lon) and p.get("score", 0) >= 0.4:
            reponse = (lat, lon, p.get("type", "street"), p.get("label", question),
                       float(p.get("score", 0)), p.get("city", ""))
    _CACHE_GEO[cle] = reponse
    return reponse


MAX_VOIES = 6          # plafond d'appels au géocodeur par annonce


def voies(texte):
    """Voies citées : libellé, numéro éventuel, et si elle est donnée comme voisine."""
    vus, out = set(), []
    for m in RE_VOIE.finditer(texte):
        libelle = re.sub(r"\s+", " ", f"{m.group('type')} {m.group('nom')}").strip(" ,.;:")
        cle = sans_accents(libelle)
        if len(libelle) < 9 or cle in vus:
            continue
        vus.add(cle)
        avant = sans_accents(texte[max(0, m.start() - 30):m.start()])
        out.append({
            "libelle": libelle,
            "numero": m.group("num"),
            # « à 200 m de la rue X » situe encore, mais moins bien qu'« au 12 rue X ».
            "proximite": bool(re.search(MARQUEURS_NEGATIFS + r"[ ,;:'’a-z]{0,14}$", avant)),
            # « située rue X » désigne l'adresse du bien.
            "adresse": bool(re.search(MARQUEURS_ADRESSE + r"[ ,;:'’a-z]{0,10}$", avant)),
        })
        if len(out) >= MAX_VOIES:
            break
    return out


def situe(texte, geo, session, commune_declaree=None):
    """Place le bien à partir des indices du texte.

    L'ordre compte : on établit d'abord la commune, puis on cherche la rue
    *dans cette commune*. Sans ça, « rue des Vignes » d'une annonce à Chenôve
    serait géocodée à Dijon, et le bien atterrirait à cinq kilomètres de là.
    Le texte prime sur la localisation déclarée, qui est un levier de
    visibilité pour l'annonceur.
    """
    t_norm = sans_accents(texte)

    trouvee = commune_du_texte(t_norm, geo)
    commune, c_lat, c_lon, force = trouvee if trouvee else (None, None, None, None)
    if commune is None:
        for nom, lat, lon in codes_postaux(t_norm, session):
            commune, c_lat, c_lon, force = nom, lat, lon, "forte"
            break
    if commune is None and commune_declaree:
        commune, force = commune_declaree, "declaree"

    conflit = bool(commune and commune_declaree
                   and sans_accents(commune) != sans_accents(commune_declaree)
                   and force == "forte")

    def resultat(lat, lon, precision, indice, source):
        return {"lat": lat, "lon": lon, "precision": precision, "indice": indice,
                "source": source, "commune": commune, "conflit": conflit}

    # 1. une rue, cherchée dans la commune retenue. On les essaie toutes et on
    # garde la meilleure : une annonce cite souvent une rue voisine avant la
    # sienne, et un numéro vaut mieux qu'un nom seul.
    candidats = []
    if session is not None:
        for v in voies(texte):
            question = " ".join(x for x in (v["numero"], v["libelle"]) if x)
            if commune:
                question += f", {commune}"
            r = geocode(question, session)
            if not r:
                continue
            lat, lon, typ, label, score, ville_ban = r
            candidats.append({
                "lat": lat, "lon": lon, "label": label, "score": score,
                "numero": typ == "housenumber",
                "bonne_commune": (not commune
                                  or sans_accents(ville_ban) == sans_accents(commune)),
                "proximite": v["proximite"],
                "adresse": v["adresse"],
                "precision": PRECISION_M.get(typ, PRECISION_M["street"]),
            })
    if candidats:
        candidats.sort(key=lambda c: (not c["numero"], not c["bonne_commune"],
                                      c["proximite"], not c["adresse"], -c["score"]))
        meilleur = candidats[0]
        return resultat(meilleur["lat"], meilleur["lon"], meilleur["precision"],
                        meilleur["label"], "adresse")

    # 2. un quartier nommé
    for cle, (nom, lat, lon), m in occurrences(t_norm, geo["quartiers"]):
        if lat is not None:
            return resultat(lat, lon, PRECISION_M["quartier"], nom, "quartier")

    # 3. un repère : parc, arrêt
    for cle, (nom, lat, lon), m in occurrences(t_norm, geo["reperes"]):
        if lat is not None:
            return resultat(lat, lon, PRECISION_M["repere"], nom, "repère")
        if session is not None:
            r = geocode(f"{nom}, {commune}" if commune else nom, session)
            if r:
                return resultat(r[0], r[1], PRECISION_M["repere"], r[3], "repère")

    # 4. la commune seule
    if c_lat is not None:
        return resultat(c_lat, c_lon, PRECISION_M["municipality"], commune, "commune")
    if commune and session is not None:
        r = geocode(commune, session, type_ban="municipality")
        if r:
            return resultat(r[0], r[1], PRECISION_M["municipality"], r[3], "commune")
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
                    # Une ligne de recherche ne porte pas la description : sa
                    # position ne pourra jamais dépasser la commune.
                    "detail": False,
                })
        else:
            out.append({
                "url": c.get("url"), "site": c.get("site"),
                "titre": (c.get("titre") or "").strip()[:120],
                "texte": c.get("texte") or "",
                "capture": (c.get("capture") or "")[:10],
                "prix": None, "surface": None, "pieces": None, "type": None,
                "ville": None, "lat_annonceur": None, "lon_annonceur": None,
                "detail": True,
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

def diagnostic(annonce, geo):
    """Ce que le script voit dans une annonce, avant tout appel au géocodeur."""
    texte = annonce["texte"]
    t_norm = sans_accents(texte)
    v = voies(texte)
    com = [nom for _, (nom, _, _), _ in occurrences(t_norm, geo["communes"])]
    qua = [nom for _, (nom, _, _), _ in occurrences(t_norm, geo["quartiers"])]
    rep = [nom for _, (nom, _, _), _ in occurrences(t_norm, geo["reperes"])]
    source = "annonce ouverte" if annonce.get("detail") else "ligne de recherche seule"
    log(f"  ── {annonce['titre'][:60]}")
    log(f"     texte : {len(texte)} caractères  ({source})")
    log(f"     début : {texte[:150].replace(chr(10), ' ⏎ ')}")
    log(f"     voies : {[x['libelle'] for x in v] or '—'}")
    log(f"     communes : {com or '—'} · quartiers : {qua or '—'} · repères : {rep or '—'}")


A_PRECISER = "a_preciser.html"
PRECISION_FINE = 200          # au-delà, l'annonce mérite d'être ouverte


def ecrit_a_preciser(annonces):
    """Page de liens vers les annonces encore imprécises, à ouvrir puis capturer."""
    # Une annonce déjà ouverte a livré tout ce qu'elle avait : la redemander
    # ferait refaire un travail sans effet.
    floues = [a for a in annonces if a["precision"] > PRECISION_FINE and not a.get("detail")]
    if not floues:
        if os.path.exists(A_PRECISER):
            os.remove(A_PRECISER)
        return 0
    # Le meilleur rapport au m² d'abord : c'est par là qu'on a envie de creuser.
    floues.sort(key=lambda a: (a["prix"] / a["surface"]) if a["prix"] and a["surface"] else 1e9)
    lignes = []
    for a in floues:
        ppm2 = f"{a['prix'] / a['surface']:.0f} €/m²" if a["prix"] and a["surface"] else "—"
        lignes.append(
            f'<tr><td><a href="{html.escape(a["url"] or "#", quote=True)}" target="_blank" '
            f'rel="noopener">{html.escape(a["titre"] or "annonce")}</a></td>'
            f'<td>{fmt_eur(a["prix"])}</td><td>{ppm2}</td>'
            f'<td>{html.escape(str(a.get("commune") or "—"))}</td>'
            f'<td>±{a["precision"]} m</td></tr>')
    page = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Annonces à préciser</title><style>
body {{ font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; max-width:60em;
       margin:32px auto; padding:0 24px; color:#1f2328; }}
h1 {{ font-size:21px; margin:0 0 4px; }} .sub {{ color:#6b7280; margin:0 0 22px; }}
table {{ border-collapse:collapse; width:100%; }}
th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid #e2e5e9; }}
th {{ font-size:13px; color:#6b7280; font-weight:600; }}
td:nth-child(2),td:nth-child(3),td:nth-child(5) {{ text-align:right;
       font-variant-numeric:tabular-nums; white-space:nowrap; }}
ol {{ background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:14px 18px 14px 38px;
      font-size:14px; }}
</style></head><body>
<h1>{len(floues)} annonces à préciser</h1>
<p class="sub">Situées à la commune ou au quartier près. Leur description contient
souvent une rue, mais Leboncoin ne la met pas dans ses pages de résultats.</p>
<ol>
  <li>Ouvrir celles qui vous intéressent (clic du milieu, ou Ctrl + clic, pour un nouvel onglet).</li>
  <li>Sur chacune, cliquer le favori <b>Capturer l'annonce</b>.</li>
  <li>Relancer <code>python annonces.py</code>. Elles descendront à ±150 m, ou ±60 m avec un numéro.</li>
</ol>
<table><tr><th>Annonce</th><th>Prix</th><th>Au m²</th><th>Commune</th><th>Précision</th></tr>
{''.join(lignes)}</table></body></html>
"""
    with open(A_PRECISER, "w", encoding="utf-8") as f:
        f.write(page)
    return len(floues)


def fmt_eur(v):
    return f"{v:,.0f} €".replace(",", " ") if v else "—"


def main():
    avec_geo = "--sans-geo" not in sys.argv
    mode_diag = "--diagnostic" in sys.argv
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
                    "lat_annonceur", "lon_annonceur", "titre", "site", "capture", "detail")
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

    log("Référentiel de lieux…")
    geo = charge_geo()
    log(f"  {len(geo['communes'])} communes, {len(geo['quartiers'])} quartiers, "
        f"{len(geo['reperes'])} arrêts et parcs")
    flous = centroides(list(par_url.values()))
    if flous:
        log(f"  {len(flous)} coordonnée(s) partagée(s) par plusieurs annonces : "
            f"traitées comme des centres de commune")

    if mode_diag:
        log("Diagnostic — ce que le script lit dans chaque annonce :")
        for c in par_url.values():
            diagnostic(c, geo)
        log("")

    log("Lecture des annonces…")
    annonces, sans_position, conflits = [], 0, 0
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
        pos = situe(texte, geo, session, commune_declaree=c["ville"])
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
                     precision=pos["precision"], indice=pos["indice"], source=pos["source"],
                     commune=pos.get("commune"), declaree=c["ville"],
                     conflit=bool(pos.get("conflit")), detail=bool(c.get("detail")))
            annonces.append(a)
            if a["conflit"]:
                conflits += 1
            ppm2 = f"{a['prix'] / a['surface']:.0f} €/m²" if a["prix"] and a["surface"] else "—"
            log(f"  {'!' if a['conflit'] else '✓'} {a['titre'][:38]:38s} "
                f"{str(a['prix'] or '—'):>9s} € · {ppm2:>10s}"
                f" · ±{pos['precision']:>4} m · {pos['indice'][:36]}")
            if a["conflit"]:
                log(f"      annonce déclarée à {c['ville']}, le texte dit {pos['commune']}")
        else:
            sans_position += 1
            log(f"  ? {a['titre'][:40]:40s} aucun indice de lieu exploitable")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("window.ANNONCES = ")
        json.dump(annonces, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    if conflits:
        log(f"  {conflits} annonce(s) replacée(s) dans une autre commune que celle déclarée")
    if _STATS["reseau"]:
        log(f"  ATTENTION : {_STATS['reseau']} appel(s) au géocodeur sur {_STATS['appels']} ont échoué.")
        log("  Sans lui, aucune rue ne peut être placée. Vérifier l'accès à "
            "api-adresse.data.gouv.fr.")
    elif _STATS["appels"]:
        log(f"  géocodeur : {_STATS['appels']} appels, {_STATS['sans_resultat']} sans réponse")
    par_precision = Counter(a["precision"] for a in annonces)
    log(f"OK → {OUTPUT} : {len(annonces)} annonce(s) placée(s), {sans_position} sans position.")
    for prec in sorted(par_precision):
        log(f"  ±{prec:>4} m : {par_precision[prec]} annonce(s)")
    muettes = [a for a in annonces
               if a["precision"] > PRECISION_FINE and a.get("detail")]
    if muettes:
        log(f"  {len(muettes)} annonce(s) ouverte(s) ne donnent aucune rue : "
            f"leur description n'en cite pas. Rien de plus à en tirer.")
    n_floues = ecrit_a_preciser(annonces)
    if n_floues:
        log(f"  {n_floues} annonce(s) restent à ouvrir une à une : voir {A_PRECISER}")
    elif muettes:
        log(f"  Toutes les autres ont été ouvertes : {A_PRECISER} est vide.")


if __name__ == "__main__":
    main()
