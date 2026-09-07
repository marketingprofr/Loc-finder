#!/usr/bin/env python3
"""
Scoring d'emplacements pour acheter une maison — Dijon Métropole.

Usage :
    pip install requests numpy pandas scipy
    python build_dijon.py            → écrit data.js (à côté de index.html)
    python build_dijon.py --no-dvf   → sans les prix (plus rapide)

Sources (gratuites, sans clé) :
  - OpenStreetMap via Overpass : supérettes, salles de sport, boulangeries, parcs
  - GTFS Divia (transport.data.gouv.fr) : arrêts, horaires, fréquences
  - DVF géolocalisé (files.data.gouv.fr) : ventes réelles de maisons

Les téléchargements sont mis en cache dans ./cache/ — supprimer un fichier pour forcer
un nouveau téléchargement.

Tous les paramètres sont dans la section CONFIG ci-dessous.
"""
import io
import json
import math
import os
import sys
import time
import zipfile
from collections import Counter

import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree

# =============================== CONFIG ======================================

# Emprise : Dijon Métropole (lat_min, lon_min, lat_max, lon_max)
BBOX = (47.24, 4.93, 47.40, 5.16)

# Les trois "centres". Un arrêt est considéré "au centre" s'il est à moins de
# CENTRE_RADIUS_M de l'un d'eux.
CENTRE_POINTS = {
    "Darcy": (47.3231, 5.0321),
    "République": (47.3237, 5.0420),
    "Libération": (47.3213, 5.0412),
}
CENTRE_RADIUS_M = 250

# Transport
MAX_RIDE_MIN = 20          # temps en véhicule maxi arrêt → centre
FREQ_WINDOW_H = (7, 20)    # fenêtre de comptage des départs (jour de semaine)
FULL_FREQ_PER_H = 6        # ≥ 6 départs/h → facteur 1 (indicatif, cf. TRAM_* ci-dessous)
MAX_STOP_WALK_MIN = 12     # au-delà, on ne cherche plus d'arrêt

# Barème « tram / bus ». Il est répété dans index.html, qui s'en sert pour
# noter ; ici il sert à choisir, pour chaque case, l'arrêt le plus intéressant.
# Les deux doivent rester d'accord, sinon la carte note un arrêt qui n'est pas
# le meilleur au sens de son propre barème.
#   points de marche  : 10 à ≤ 1 min, 0 à ≥ 10 min
#   facteur fréquence : proportionnel, plafonné à 10 départs/h
#   facteur trajet    : 1 à ≤ 5 min, 0,8 à 10 min, 0,4 à 20 min
TRAM_WALK_FULL_MIN = 1
TRAM_WALK_ZERO_MIN = 10
TRAM_FREQ_FULL_PER_H = 10
TRAM_RIDE_FULL_MIN = 5
TRAM_RIDE_PER_MIN = 0.04

# Marche
WALK_SPEED_M_PER_MIN = 5000 / 60   # 5 km/h
DETOUR_FACTOR = 1.3                # vol d'oiseau × 1,3 ≈ distance réelle à pied

# Grille
GRID_STEP_M = 100
KEEP_CELL_IF_ANY_WITHIN_MIN = 12   # on ne garde que les cases ayant au moins un critère ≤ 12 min

# Espaces verts
PARK_MIN_AREA_M2 = 10_000          # 1 ha
WOOD_MIN_AREA_M2 = 50_000          # 5 ha pour les bois/forêts

# Prix (DVF)
DVF_YEARS = [2023, 2024, 2025]
DVF_DEPARTEMENT = "21"
# Rayons essayés dans l'ordre autour de chaque case : on s'élargit tant qu'on
# n'a pas DVF_MIN_SALES ventes. Le rayon retenu est affiché dans la carte, une
# médiane sur 2,5 km ne valant pas une médiane sur 500 m.
DVF_RADII_M = [500, 1000, 1500, 2500]
DVF_MIN_SALES = 5

# À surface et emplacement égaux, une maison vaut plus qu'un appartement — on
# a le jardin et le garage en plus. Pour verser les deux dans une même médiane,
# le prix au m² des appartements est multiplié par ce coefficient, ce qui les
# ramène sur l'échelle « maison » : à 1,20, un appartement à 2 200 €/m² compte
# pour 2 640, prix qu'aurait une maison équivalente au même endroit.
# Le script vérifie ce coefficient sur les ventes réelles et le signale s'il
# s'en écarte.
APPART_VERS_MAISON = 1.20

# Bornes de surface plausibles, par type.
SURFACE_MAISON = (25, 400)
SURFACE_APPART = (15, 250)

# URLs
GTFS_URL = "https://www.data.gouv.fr/api/1/datasets/r/e0dbd217-15cd-4e28-9459-211a27511a34"
DVF_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/departements/{dep}.csv.gz"

# Miroirs Overpass, essayés dans l'ordre. overpass-api.de filtre les clients
# non-navigateurs et répond 406 quel que soit le User-Agent envoyé ; il passe
# donc en dernier, en secours. kumi.systems est un miroir public à forte
# capacité qui sert la planète entière, comme private.coffee.
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# S'identifier est demandé par la politique d'usage d'OSM.
USER_AGENT = "loc-finder/1.0 (+https://github.com/marketingprofr/Loc-finder)"

CACHE_DIR = "cache"
OUTPUT = "data.js"

# ============================== OUTILS =======================================

LAT0 = (BBOX[0] + BBOX[2]) / 2
LON0 = (BBOX[1] + BBOX[3]) / 2
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def to_xy(lat, lon):
    """Projection locale équirectangulaire en mètres (suffisante à l'échelle d'une ville)."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return np.column_stack(((lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT))


def to_latlon(xy):
    xy = np.asarray(xy, dtype=float)
    return xy[:, 1] / M_PER_DEG_LAT + LAT0, xy[:, 0] / M_PER_DEG_LON + LON0


def walk_minutes(dist_m):
    return dist_m * DETOUR_FACTOR / WALK_SPEED_M_PER_MIN


def walk_radius_m(minutes):
    return minutes * WALK_SPEED_M_PER_MIN / DETOUR_FACTOR


def log(msg):
    print(msg, flush=True)


def download(url, cache_name, data=None):
    """GET (ou POST si data) avec cache disque. Retourne les bytes."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_name)
    if os.path.exists(path):
        log(f"  cache : {path}")
        with open(path, "rb") as f:
            return f.read()
    log(f"  téléchargement : {url}")
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            if data is None:
                r = requests.get(url, timeout=600, headers=headers)
            else:
                r = requests.post(url, data=data, timeout=600, headers=headers)
            r.raise_for_status()
            break
        except Exception as e:  # noqa
            # 4xx hors 429 : le serveur refuse la requête, réessayer à
            # l'identique ne changera rien — autant passer au miroir suivant.
            r_err = getattr(e, "response", None)
            refus = (r_err is not None and 400 <= r_err.status_code < 500
                     and r_err.status_code != 429)
            if refus or attempt == 2:
                raise
            log(f"  échec ({e}), nouvel essai dans 10 s")
            time.sleep(10)
    with open(path, "wb") as f:
        f.write(r.content)
    return r.content


# ============================== OSM ==========================================

OVERPASS_QUERY = """
[out:json][timeout:300];
(
  nwr["shop"~"^(supermarket|convenience)$"]({bbox});
  nwr["shop"="bakery"]({bbox});
  nwr["leisure"="fitness_centre"]({bbox});
) -> .poi;
(
  nwr["leisure"~"^(park|garden)$"]["access"!="private"]({bbox});
  nwr["natural"="wood"]({bbox});
  nwr["landuse"="forest"]({bbox});
) -> .green;
.poi out center;
.green out geom;
"""


def fetch_osm():
    bbox = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    query = {"data": OVERPASS_QUERY.format(bbox=bbox)}
    for i, url in enumerate(OVERPASS_URLS):
        try:
            raw = download(url, "overpass.json", data=query)
            break
        except Exception as e:  # noqa
            if i == len(OVERPASS_URLS) - 1:
                raise
            log(f"  {url} indisponible ({e}), essai du miroir suivant")
    return json.loads(raw)["elements"]


def element_center(el):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    if c:
        return c["lat"], c["lon"]
    return None


# Des objets OSM cumulent un shop=* avec un amenity=* qui décrit leur vraie
# nature : l'auto-école Campus, à Dijon, est taguée shop=convenience *et*
# amenity=driving_school. On écarte ces cas, en gardant les cumuls légitimes
# (boutique de station-service, point poste, café d'une boulangerie).
AMENITY_COMPATIBLE = {"fuel", "post_office", "cafe", "restaurant", "fast_food",
                      "ice_cream", "marketplace"}


def parse_pois(elements):
    """→ dict catégorie → DataFrame(lat, lon, name)."""
    cats = {"s": [], "g": [], "b": []}
    ecartes = 0
    for el in elements:
        t = el.get("tags", {})
        amenity = t.get("amenity")
        if amenity and amenity not in AMENITY_COMPATIBLE:
            ecartes += 1
            continue
        if "shop" in t and t["shop"] in ("supermarket", "convenience"):
            cat = "s"
        elif t.get("shop") == "bakery":
            cat = "b"
        elif t.get("leisure") == "fitness_centre":
            cat = "g"
        else:
            continue
        c = element_center(el)
        if not c:
            continue
        name = t.get("name") or t.get("brand") or {"s": "Supérette", "g": "Salle de sport", "b": "Boulangerie"}[cat]
        cats[cat].append((c[0], c[1], name))
    if ecartes:
        log(f"  écartés (amenity incompatible avec le commerce) : {ecartes}")
    return {k: pd.DataFrame(v, columns=["lat", "lon", "name"]) for k, v in cats.items()}


def shoelace_area(ring_xy):
    x, y = ring_xy[:, 0], ring_xy[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def stitch_rings(lines):
    """Assemble des polylignes (listes de (lat, lon)) en anneaux fermés quand c'est possible."""
    lines = [list(l) for l in lines if len(l) >= 2]
    rings = []
    while lines:
        ring = lines.pop(0)
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, l in enumerate(lines):
                if l[0] == ring[-1]:
                    ring += l[1:]
                    lines.pop(i)
                    changed = True
                    break
                if l[-1] == ring[-1]:
                    ring += l[-2::-1]
                    lines.pop(i)
                    changed = True
                    break
        rings.append(ring)
    return rings


def sample_polyline(xy, step=25.0):
    """Points tous les `step` mètres le long d'une polyligne (xy en mètres)."""
    pts = [xy[0]]
    for a, b in zip(xy[:-1], xy[1:]):
        seg = b - a
        L = float(np.hypot(*seg))
        n = int(L // step)
        for k in range(1, n + 1):
            pts.append(a + seg * (k * step / L))
        pts.append(b)
    return np.array(pts)


def parse_green(elements):
    """→ (points de contour xy, index de l'espace vert pour chaque point, noms)."""
    names, boundary_pts, owner = [], [], []
    for el in elements:
        t = el.get("tags", {})
        is_park = t.get("leisure") in ("park", "garden")
        is_wood = t.get("natural") == "wood" or t.get("landuse") == "forest"
        if not (is_park or is_wood):
            continue
        min_area = PARK_MIN_AREA_M2 if is_park else WOOD_MIN_AREA_M2

        lines = []
        if el["type"] == "way" and "geometry" in el:
            lines = [[(p["lat"], p["lon"]) for p in el["geometry"]]]
        elif el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("type") == "way" and m.get("role", "outer") in ("outer", "") and "geometry" in m:
                    lines.append([(p["lat"], p["lon"]) for p in m["geometry"]])
        if not lines:
            continue

        rings = stitch_rings(lines)
        area = 0.0
        for ring in rings:
            xy = to_xy([p[0] for p in ring], [p[1] for p in ring])
            if ring[0] == ring[-1] and len(ring) >= 4:
                area += shoelace_area(xy[:-1])
            else:
                # anneau non fermé : approximation par la boîte englobante
                area += 0.6 * (np.ptp(xy[:, 0]) * np.ptp(xy[:, 1]))
        if area < min_area:
            continue

        idx = len(names)
        names.append(t.get("name") or ("Bois" if is_wood else "Parc"))
        for ring in rings:
            xy = to_xy([p[0] for p in ring], [p[1] for p in ring])
            pts = sample_polyline(xy)
            boundary_pts.append(pts)
            owner.extend([idx] * len(pts))
    if not boundary_pts:
        return np.zeros((0, 2)), np.zeros(0, dtype=int), names
    return np.vstack(boundary_pts), np.array(owner), names


# ============================== GTFS =========================================

def parse_gtfs_time(s):
    """'HH:MM:SS' (HH peut dépasser 24) → secondes ; NaN si vide."""
    s = pd.Series(s, dtype="string")
    parts = s.str.split(":", expand=True)
    if parts.shape[1] < 3:
        return pd.Series(np.nan, index=s.index)
    h = pd.to_numeric(parts[0], errors="coerce")
    m = pd.to_numeric(parts[1], errors="coerce")
    sec = pd.to_numeric(parts[2], errors="coerce")
    return h * 3600 + m * 60 + sec


def active_services_on(date, calendar, calendar_dates):
    """Services actifs à une date (datetime.date)."""
    d = int(date.strftime("%Y%m%d"))
    weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][date.weekday()]
    active = set()
    if calendar is not None and len(calendar):
        c = calendar
        mask = (c["start_date"].astype(int) <= d) & (c["end_date"].astype(int) >= d) & (c[weekday].astype(int) == 1)
        active |= set(c.loc[mask, "service_id"])
    if calendar_dates is not None and len(calendar_dates):
        cd = calendar_dates[calendar_dates["date"].astype(int) == d]
        active |= set(cd.loc[cd["exception_type"].astype(int) == 1, "service_id"])
        active -= set(cd.loc[cd["exception_type"].astype(int) == 2, "service_id"])
    return active


def pick_reference_tuesday(trips, calendar, calendar_dates):
    """Le mardi (dans la période couverte) qui a le plus de voyages."""
    dates = []
    if calendar is not None and len(calendar):
        dates += list(calendar["start_date"].astype(str)) + list(calendar["end_date"].astype(str))
    if calendar_dates is not None and len(calendar_dates):
        dates += list(calendar_dates["date"].astype(str))
    dmin, dmax = pd.to_datetime(min(dates)), pd.to_datetime(max(dates))
    trips_per_service = trips["service_id"].value_counts()
    best, best_n = None, -1
    for day in pd.date_range(dmin, dmax):
        if day.weekday() != 1:
            continue
        act = active_services_on(day.date(), calendar, calendar_dates)
        n = int(trips_per_service.reindex(list(act)).fillna(0).sum())
        if n > best_n:
            best, best_n = day, n
    return best, best_n


def load_gtfs():
    raw = download(GTFS_URL, "gtfs_divia.zip")
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = {n.split("/")[-1]: n for n in z.namelist()}

    def read(name, **kw):
        if name not in names:
            return None
        return pd.read_csv(z.open(names[name]), dtype=str, **kw)

    stops = read("stops.txt")
    routes = read("routes.txt")
    trips = read("trips.txt")
    stop_times = read("stop_times.txt")
    calendar = read("calendar.txt")
    calendar_dates = read("calendar_dates.txt")

    stops["stop_lat"] = stops["stop_lat"].astype(float)
    stops["stop_lon"] = stops["stop_lon"].astype(float)
    if "location_type" in stops:
        lt = pd.to_numeric(stops["location_type"], errors="coerce").fillna(0)
        stops = stops[lt == 0]
    stops = stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]].reset_index(drop=True)

    # Arrêts "au centre"
    stops_xy = to_xy(stops["stop_lat"], stops["stop_lon"])
    centre_xy = to_xy([p[0] for p in CENTRE_POINTS.values()], [p[1] for p in CENTRE_POINTS.values()])
    d_centre = np.min(np.linalg.norm(stops_xy[:, None, :] - centre_xy[None, :, :], axis=2), axis=1)
    centre_ids = set(stops.loc[d_centre <= CENTRE_RADIUS_M, "stop_id"])
    log(f"  arrêts au centre ({len(centre_ids)}) : "
        + ", ".join(sorted(set(stops.loc[stops['stop_id'].isin(centre_ids), 'stop_name']))))
    if not centre_ids:
        sys.exit("Aucun arrêt trouvé près des points centre — vérifier CENTRE_POINTS / CENTRE_RADIUS_M")

    # Jour de référence
    ref_day, n_trips = pick_reference_tuesday(trips, calendar, calendar_dates)
    log(f"  jour de référence : {ref_day.date()} ({n_trips} voyages)")
    active = active_services_on(ref_day.date(), calendar, calendar_dates)
    day_trips = trips[trips["service_id"].isin(active)][["trip_id", "route_id"]]
    day_trips = day_trips.merge(routes[["route_id", "route_short_name"]], on="route_id", how="left")

    st = stop_times[stop_times["trip_id"].isin(set(day_trips["trip_id"]))].copy()
    st["seq"] = st["stop_sequence"].astype(int)
    st["arr"] = parse_gtfs_time(st["arrival_time"]).astype(float)
    st["dep"] = parse_gtfs_time(st["departure_time"]).astype(float)
    st = st.sort_values(["trip_id", "seq"]).reset_index(drop=True)
    # horaires manquants aux arrêts intermédiaires → interpolation (premier/dernier arrêt toujours renseignés)
    st["arr"] = st["arr"].interpolate()
    st["dep"] = st["dep"].fillna(st["arr"])
    st = st.merge(day_trips, on="trip_id", how="left")

    # Premier passage au centre de chaque voyage
    st["is_centre"] = st["stop_id"].isin(centre_ids)
    firsts = st[st["is_centre"]].groupby("trip_id").first()[["seq", "arr"]]
    firsts.columns = ["centre_seq", "centre_arr"]
    st = st.merge(firsts, left_on="trip_id", right_index=True, how="inner")
    st = st[st["seq"] <= st["centre_seq"]]
    st["ride_min"] = (st["centre_arr"] - st["dep"]) / 60.0
    st = st[(st["ride_min"] >= 0) & (st["ride_min"] <= MAX_RIDE_MIN)]
    w0, w1 = FREQ_WINDOW_H
    st = st[(st["dep"] >= w0 * 3600) & (st["dep"] < w1 * 3600)]

    hours = w1 - w0
    agg = st.groupby("stop_id").agg(
        n=("trip_id", "count"),
        ride_med=("ride_min", "median"),
    )
    lines = st.groupby("stop_id")["route_short_name"].agg(
        lambda s: " ".join(f"{k}" for k, _ in Counter(s.fillna("?")).most_common(3)))
    agg["lines"] = lines
    agg["dph"] = agg["n"] / hours
    agg["ff"] = np.minimum(1.0, agg["dph"] / FULL_FREQ_PER_H)

    stops = stops.merge(agg, left_on="stop_id", right_index=True, how="inner").reset_index(drop=True)
    log(f"  arrêts desservant le centre en ≤ {MAX_RIDE_MIN} min : {len(stops)}")
    return stops


# ============================== DVF ==========================================

def ventes_du_type(df, principal, bornes_surface):
    """Ventes composées uniquement de `principal` (+ dépendances).

    Une mutation mêlant maison et appartement est écartée : impossible de dire
    quelle part du prix revient à quoi.
    """
    def keep(types):
        s = set(t for t in types if isinstance(t, str))
        return principal in s and s <= {principal, "Dépendance"}

    ok = df.groupby("id_mutation")["type_local"].agg(keep)
    sub = df[df["id_mutation"].isin(ok[ok].index)]
    lots = sub[sub["type_local"] == principal]
    if not len(lots):
        return pd.DataFrame(columns=["lat", "lon", "ppm2"])
    v = lots.groupby("id_mutation").agg(
        surface=("surface_reelle_bati", "sum"),
        price=("valeur_fonciere", "max"),
        lat=("latitude", "first"),
        lon=("longitude", "first"),
    )
    smin, smax = bornes_surface
    v = v[(v["surface"] >= smin) & (v["surface"] <= smax) & (v["price"] >= 30_000)]
    v["ppm2"] = v["price"] / v["surface"]
    v = v[(v["ppm2"] >= 500) & (v["ppm2"] <= 8000)]
    return v.reset_index(drop=True)[["lat", "lon", "ppm2"]]


def rapport_local(maisons, apparts, rayon=800, mini=5):
    """Rapport maison/appartement à emplacement comparable.

    Le rapport des médianes globales ne vaut rien : les appartements se
    concentrent au centre, où tout est plus cher, si bien que l'écart mesuré
    mélange l'effet du type de bien et celui de l'emplacement — et peut même
    s'inverser. On compare donc chaque appartement aux maisons vendues autour
    de lui, puis on prend la médiane de ces rapports.

    → (combien de fois une maison vaut le prix au m² d'un appartement voisin,
       nombre d'appariements). C'est exactement le coefficient à appliquer.
    """
    if len(maisons) < mini or not len(apparts):
        return None, 0
    tree = cKDTree(to_xy(maisons["lat"], maisons["lon"]))
    ppm2_m = maisons["ppm2"].to_numpy()
    voisins = tree.query_ball_point(to_xy(apparts["lat"], apparts["lon"]), rayon)
    rapports = [np.median(ppm2_m[v]) / a
                for a, v in zip(apparts["ppm2"].to_numpy(), voisins) if len(v) >= mini]
    if not rapports:
        return None, 0
    return float(np.median(rapports)), len(rapports)


def load_dvf():
    cols = ["id_mutation", "nature_mutation", "valeur_fonciere", "type_local",
            "surface_reelle_bati", "longitude", "latitude"]
    frames = []
    for y in DVF_YEARS:
        url = DVF_URL.format(year=y, dep=DVF_DEPARTEMENT)
        try:
            raw = download(url, f"dvf_{DVF_DEPARTEMENT}_{y}.csv.gz")
        except Exception as e:  # noqa
            log(f"  DVF {y} indisponible ({e}), ignoré")
            continue
        df = pd.read_csv(io.BytesIO(raw), compression="gzip", usecols=cols, low_memory=False)
        df = df[(df["latitude"] >= BBOX[0]) & (df["latitude"] <= BBOX[2])
                & (df["longitude"] >= BBOX[1]) & (df["longitude"] <= BBOX[3])]
        df = df[df["nature_mutation"] == "Vente"]
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["lat", "lon", "ppm2", "appart"])
    df = pd.concat(frames, ignore_index=True)

    maisons = ventes_du_type(df, "Maison", SURFACE_MAISON)
    apparts = ventes_du_type(df, "Appartement", SURFACE_APPART)
    log(f"  ventes retenues : {len(maisons)} maisons, {len(apparts)} appartements")

    coef, n_paires = rapport_local(maisons, apparts)
    if coef is not None:
        log(f"  mesuré : au même endroit, une maison vaut {coef:.2f} fois le prix au m² "
            f"d'un appartement, soit {(coef - 1) * 100:+.0f} % (sur {n_paires} appartements)")
        log(f"  appliqué : {APPART_VERS_MAISON:.2f}, soit {(APPART_VERS_MAISON - 1) * 100:+.0f} %"
            + ("" if abs(coef - APPART_VERS_MAISON) < 0.08
               else f"  ← écart notable, envisager APPART_VERS_MAISON = {coef:.2f}"))
    else:
        log("  trop peu de ventes voisines pour vérifier le coefficient appartement")

    apparts = apparts.copy()
    apparts["ppm2"] *= APPART_VERS_MAISON
    maisons["appart"] = False
    apparts["appart"] = True

    sales = pd.concat([maisons, apparts], ignore_index=True)
    # Le coefficient peut faire sortir des appartements des bornes : on les
    # réapplique après correction, pas avant.
    sales = sales[(sales["ppm2"] >= 500) & (sales["ppm2"] <= 8000)]
    return sales.reset_index(drop=True)[["lat", "lon", "ppm2", "appart"]]


# ============================== GRILLE =======================================

def build_grid():
    corner = to_xy([BBOX[0], BBOX[2]], [BBOX[1], BBOX[3]])
    xs = np.arange(corner[0, 0], corner[1, 0], GRID_STEP_M)
    ys = np.arange(corner[0, 1], corner[1, 1], GRID_STEP_M)
    gx, gy = np.meshgrid(xs, ys)
    return np.column_stack((gx.ravel(), gy.ravel()))


def nearest_minutes(grid_xy, pts_xy):
    """(minutes à pied vers le plus proche, index du plus proche) ; NaN si aucun point."""
    if len(pts_xy) == 0:
        return np.full(len(grid_xy), np.nan), np.full(len(grid_xy), -1)
    d, i = cKDTree(pts_xy).query(grid_xy)
    return walk_minutes(d), i


def best_stop(grid_xy, stops):
    """Pour chaque case : l'arrêt qui maximise marche × fréquence × trajet."""
    n = len(grid_xy)
    walk = np.full(n, np.nan)
    idx = np.full(n, -1)
    if len(stops) == 0:
        return walk, idx
    stops_xy = to_xy(stops["stop_lat"], stops["stop_lon"])
    tree = cKDTree(stops_xy)
    r = walk_radius_m(MAX_STOP_WALK_MIN)
    freq_f = np.clip(stops["dph"].to_numpy() / TRAM_FREQ_FULL_PER_H, 0, 1)
    ride_f = np.clip(1 - (stops["ride_med"].to_numpy() - TRAM_RIDE_FULL_MIN) * TRAM_RIDE_PER_MIN, 0, 1)
    span = TRAM_WALK_ZERO_MIN - TRAM_WALK_FULL_MIN
    neighbours = tree.query_ball_point(grid_xy, r)
    for k, cand in enumerate(neighbours):
        if not cand:
            continue
        cand = np.array(cand)
        d = np.linalg.norm(stops_xy[cand] - grid_xy[k], axis=1)
        wm = walk_minutes(d)
        walk_pts = np.clip(10 * (TRAM_WALK_ZERO_MIN - wm) / span, 0, 10)
        score = walk_pts * freq_f[cand] * ride_f[cand]
        j = int(np.argmax(score))
        walk[k], idx[k] = wm[j], cand[j]
    return walk, idx


def price_per_cell(grid_xy, sales):
    n = len(grid_xy)
    price = np.full(n, np.nan)
    count = np.zeros(n, dtype=int)
    radius_used = np.zeros(n, dtype=int)
    part_appart = np.zeros(n, dtype=int)
    if len(sales) == 0:
        return price, count, radius_used, part_appart
    tree = cKDTree(to_xy(sales["lat"], sales["lon"]))
    ppm2 = sales["ppm2"].to_numpy()
    est_appart = sales["appart"].to_numpy().astype(bool)
    for radius in DVF_RADII_M:
        todo = np.where(np.isnan(price))[0]
        if not len(todo):
            break
        neighbours = tree.query_ball_point(grid_xy[todo], radius)
        for k, cand in zip(todo, neighbours):
            if len(cand) >= DVF_MIN_SALES:
                price[k] = np.median(ppm2[cand])
                count[k] = len(cand)
                radius_used[k] = radius
                # Sur quoi repose la médiane : une case du centre s'appuie
                # surtout sur des appartements, la périphérie sur des maisons.
                part_appart[k] = round(100 * est_appart[cand].mean())
        log(f"  rayon {radius} m : {int((~np.isnan(price)).sum())}/{n} cases estimées")
    return price, count, radius_used, part_appart


def park_points(green_xy, green_owner, green_names):
    """Un point représentatif par espace vert : le centre de son contour échantillonné."""
    sortie = []
    for i, nom in enumerate(green_names):
        m = green_owner == i
        if not m.any():
            sortie.append([nom, None, None])
            continue
        lat, lon = to_latlon(green_xy[m].mean(axis=0)[None, :])
        sortie.append([nom, round(float(lat[0]), 5), round(float(lon[0]), 5)])
    return sortie


def r1(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 1)


def main():
    use_dvf = "--no-dvf" not in sys.argv
    t0 = time.time()

    log("OSM (Overpass)…")
    elements = fetch_osm()
    pois = parse_pois(elements)
    green_xy, green_owner, green_names = parse_green(elements)
    log(f"  supérettes {len(pois['s'])}, salles de sport {len(pois['g'])}, boulangeries {len(pois['b'])}, "
        f"espaces verts ≥ seuil {len(green_names)}")

    log("GTFS Divia…")
    stops = load_gtfs()

    sales = pd.DataFrame(columns=["lat", "lon", "ppm2", "appart"])
    if use_dvf:
        log("DVF…")
        sales = load_dvf()

    log("Grille…")
    grid_xy = build_grid()
    log(f"  {len(grid_xy)} cases de {GRID_STEP_M} m")

    tw, tidx = best_stop(grid_xy, stops)
    sm, sidx = nearest_minutes(grid_xy, to_xy(pois["s"]["lat"], pois["s"]["lon"]))
    gm, gidx = nearest_minutes(grid_xy, to_xy(pois["g"]["lat"], pois["g"]["lon"]))
    bm, bidx = nearest_minutes(grid_xy, to_xy(pois["b"]["lat"], pois["b"]["lon"]))
    pm, pidx = nearest_minutes(grid_xy, green_xy)
    pidx = np.where(pidx >= 0, green_owner[np.maximum(pidx, 0)], -1) if len(green_owner) else pidx
    price, nsales, prad, papp = price_per_cell(grid_xy, sales)

    # Filtrage des cases sans intérêt (loin de tout)
    stack = np.column_stack((np.nan_to_num(tw, nan=1e9), sm, gm, bm, pm))
    keep = np.nanmin(stack, axis=1) <= KEEP_CELL_IF_ANY_WITHIN_MIN
    log(f"  cases conservées : {int(keep.sum())}")

    lat, lon = to_latlon(grid_xy)
    cells = []
    for k in np.where(keep)[0]:
        cells.append([
            round(float(lat[k]), 5), round(float(lon[k]), 5),
            r1(tw[k]), int(tidx[k]),
            r1(sm[k]), int(sidx[k]),
            r1(gm[k]), int(gidx[k]),
            r1(bm[k]), int(bidx[k]),
            r1(pm[k]), int(pidx[k]),
            None if math.isnan(price[k]) else int(price[k]), int(nsales[k]), int(prad[k]), int(papp[k]),
        ])

    valid_prices = price[~np.isnan(price)]
    meta = {
        "city": "Dijon Métropole",
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "step_m": GRID_STEP_M,
        "lat0": LAT0,
        "max_ride_min": MAX_RIDE_MIN,
        "full_freq_per_h": FULL_FREQ_PER_H,
        "appart_vers_maison": APPART_VERS_MAISON,
        "price_p10": int(np.percentile(valid_prices, 10)) if len(valid_prices) else None,
        "price_p90": int(np.percentile(valid_prices, 90)) if len(valid_prices) else None,
        "centre": list(CENTRE_POINTS.keys()),
        "fields": ["lat", "lon", "t_walk", "t_idx", "s_min", "s_idx", "g_min", "g_idx",
                   "b_min", "b_idx", "p_min", "p_idx", "price", "n_sales", "p_rad", "p_app"],
    }
    data = {
        "meta": meta,
        "cells": cells,
        "stops": [[r.stop_name, r.lines, round(float(r.ride_med), 1), round(float(r.dph), 1),
                   round(float(r.stop_lat), 5), round(float(r.stop_lon), 5)]
                  for r in stops.itertuples()],
        "pois": {k: [[n, round(float(la), 5), round(float(lo), 5)]
                     for n, la, lo in zip(v["name"], v["lat"], v["lon"])]
                 for k, v in pois.items()},
        "parks": park_points(green_xy, green_owner, green_names),
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("window.DATA = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    log(f"OK → {OUTPUT} ({os.path.getsize(OUTPUT) / 1e6:.1f} Mo) en {time.time() - t0:.0f} s. Ouvrir index.html.")


if __name__ == "__main__":
    main()
