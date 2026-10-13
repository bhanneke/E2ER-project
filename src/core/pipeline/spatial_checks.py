"""The checks of a spatial analysis, before and after the analysis.

A spatial study stands on its geometry and its neighbours: which boundaries
the units are drawn with (and under what terms), in which coordinate reference
system, which units of the data have no geometry, how neighbours are defined,
and whether the spatial statistics follow from the data and that definition.
Two checks hold a study of the ``spatial-analysis`` template to it.

``spatial_design`` (before the analysis) reads ``spatial_design.json``, which
the data architect writes (schema: skills/files/data/spatial-statistics.md),
the units in ``data.db`` and the boundaries (a ``data.db`` table loaded with
``e2er-data gisco`` or ``e2er-data naturalearth``, or a GeoJSON file under
``data/``). It fails when

  (a) the boundaries' source is not recorded: neither a load in
      data_sources.json nor, for boundaries the researcher brought (a GeoJSON
      file, or a table loaded from their file), their source, licence and
      attribution in the design;
  (b) no coordinate reference system is stated, or the stated one does not fit
      the coordinates (longitudes and latitudes for EPSG:4326, metres beyond
      them for a projected one);
  (c) a unit of the data has no geometry and is not listed under
      ``units_without_geometry`` with a reason (by its id, or by a pattern
      such as ``"CH*"`` that names a group of ids);
  (d) the spatial weights are not documented: their type, k for nearest
      neighbours, the distance for a distance band, whether rows are
      standardised, and how units without neighbours are handled.

It writes the match (units with and without geometry) to ``spatial_design_check.json``.

``spatial_results`` (after the analysis, before drafting) reads
``estimation_results.json`` (the spatial results contract), the units and
values the analysis used (``spatial_units.csv``) and the weights it used
(``spatial_weights.csv``: from, to, weight), and fails when

  (e) the weights file is missing, names units the analysis has not, links a
      unit to itself, or (row-standardised) has rows that do not sum to 1;
  (f) no Moran's I is reported with permutation inference (``p_value_method``
      naming a permutation test, ``n_permutations`` of at least
      ``min_permutations``, a p-value no smaller than 1 / (permutations + 1));
  (g) a Moran's I does not follow from the units, values and weights (e2er
      recomputes I = n / S0 * sum_ij w_ij z_i z_j / sum_i z_i^2);
  (h) a map the results name has no map figure, and none can be built from the
      design's boundaries and the units file.

Local clusters (LISA, Anselin 1995) are optional; when reported, their counts
must be whole and add up to at most the number of units. The check writes its
findings to ``spatial_check.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .checks_common import Verdict, close, lst, names, num, obj, read_columns, read_csv, read_json, to_float, write_json

DESIGN_FILE = "spatial_design.json"
DESIGN_CHECK_FILE = "spatial_design_check.json"
RESULTS_CHECK_FILE = "spatial_check.json"
UNITS_FILE = "spatial_units.csv"
WEIGHTS_FILE = "spatial_weights.csv"
#: Marks a map figure this module built, so a later run of the check builds it again.
_DRAWN_BY = "drawn by e2er's spatial_results check"

DEFAULTS: dict[str, float] = {"min_permutations": 99, "max_unmatched_share": 0.2}

#: Weights types and what each must state besides row standardisation and islands.
WEIGHT_TYPES: dict[str, tuple[str, ...]] = {
    "queen": (),
    "rook": (),
    "knn": ("k",),
    "distance_band": ("threshold",),
    "inverse_distance": (),
    "kernel": ("bandwidth",),
}
_WEIGHT_ALIASES = {
    "queencontiguity": "queen",
    "queen": "queen",
    "rookcontiguity": "rook",
    "rook": "rook",
    "knn": "knn",
    "knearestneighbours": "knn",
    "knearestneighbors": "knn",
    "nearestneighbours": "knn",
    "nearestneighbors": "knn",
    "distanceband": "distance_band",
    "distance": "distance_band",
    "inversedistance": "inverse_distance",
    "idw": "inverse_distance",
    "kernel": "kernel",
}
#: Sources e2er loads boundaries from (connector names in data_sources.json).
BOUNDARY_SOURCES = ("gisco", "naturalearth")
_EPSG = re.compile(r"^(epsg|urn:ogc:def:crs:epsg:[^:]*):?:?(\d{4,5})$", re.I)
_GEOGRAPHIC = {"4326", "4258", "4269", "4979"}


def weights_type(value: Any) -> str | None:
    key = re.sub(r"[^a-z]", "", str(value or "").lower())
    return _WEIGHT_ALIASES.get(key)


def crs_code(value: Any) -> str | None:
    """The EPSG code of a stated CRS ('EPSG:4326', 'urn:ogc:def:crs:EPSG::3035', 'WGS84'), else None."""
    s = str(value or "").strip().replace(" ", "")
    if s.lower() in ("wgs84", "wgs1984", "crs84", "urn:ogc:def:crs:ogc:1.3:crs84", "lonlat"):
        return "4326"
    if s.lower() in ("etrs89-laea", "etrs89laea", "laea-europe"):
        return "3035"
    m = _EPSG.match(s)
    return m.group(2) if m else None


# ── geometry ────────────────────────────────────────────────────────────────


def parse_geometry(value: Any) -> dict[str, Any] | None:
    """A GeoJSON geometry from a dict or JSON text, else None."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict) and value.get("type") == "Feature":
        value = value.get("geometry")
    if not isinstance(value, dict) or value.get("type") not in (
        "Polygon",
        "MultiPolygon",
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
    ):
        return None
    if not isinstance(value.get("coordinates"), list):
        return None
    return value


def _coords(geom: dict[str, Any]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []

    def walk(c: Any) -> None:
        if isinstance(c, list) and len(c) >= 2 and all(isinstance(x, int | float) for x in c[:2]):
            out.append((float(c[0]), float(c[1])))
        elif isinstance(c, list):
            for x in c:
                walk(x)

    walk(geom.get("coordinates"))
    return out


def load_boundaries(workspace: Path, spec: Any) -> tuple[dict[str, dict[str, Any]] | None, str, dict[str, Any]]:
    """{unit id: geometry} from the design's boundaries; (None, why, {}) when unreadable.

    ``spec``: ``{table, id_column, geometry_column}`` (data.db) or ``{file, id_property}``
    (a GeoJSON FeatureCollection under the workspace). The third value holds the
    file's own ``crs`` member, when it has one.
    """
    ws = Path(workspace)
    if not isinstance(spec, dict):
        return None, "boundaries must name a data.db table (table, id_column, geometry_column) or a GeoJSON file", {}
    if spec.get("file"):
        rel = str(spec["file"])
        path = (ws / rel).resolve()
        if not path.is_relative_to(ws.resolve()):
            return None, f"boundaries.file {rel} lies outside the study folder", {}
        doc, err = read_json(path)
        if err:
            return None, f"boundaries.file: {err}", {}
        if not isinstance(doc, dict) or not isinstance(doc.get("features"), list):
            return None, f"boundaries.file {rel} is not a GeoJSON FeatureCollection", {}
        prop = str(spec.get("id_property") or spec.get("id_column") or "")
        if not prop:
            return None, "boundaries.id_property must name the feature property that holds the unit id", {}
        out: dict[str, dict[str, Any]] = {}
        for f in doc["features"]:
            if not isinstance(f, dict):
                continue
            uid = (f.get("properties") or {}).get(prop)
            geom = parse_geometry(f.get("geometry"))
            if uid is not None and geom is not None:
                out[str(uid)] = geom
        meta = {"crs": ((doc.get("crs") or {}).get("properties") or {}).get("name")} if doc.get("crs") else {}
        if not out:
            return None, f"boundaries.file {rel}: no feature has the property {prop} and a geometry", meta
        return out, "", meta
    table, idc, geoc = spec.get("table"), spec.get("id_column"), spec.get("geometry_column") or "geometry"
    rows, why = read_columns(ws, table, [idc, geoc])
    if rows is None:
        return None, f"boundaries: {why}", {}
    out = {}
    for uid, g in rows:
        geom = parse_geometry(g)
        if uid is not None and geom is not None:
            out[str(uid)] = geom
    if not out:
        return None, f"boundaries: {table}.{geoc} holds no GeoJSON geometry", {}
    return out, "", {}


def _recorded_loads(workspace: Path) -> list[dict[str, Any]]:
    doc, _ = read_json(Path(workspace) / "data_sources.json")
    if isinstance(doc, dict):
        doc = doc.get("sources") or doc.get("loads") or []
    return [d for d in doc if isinstance(d, dict)] if isinstance(doc, list) else []


def _listed_reasons(entries: Any, without: list[str]) -> dict[str, str]:
    """{unit id: reason} for the units ``units_without_geometry`` lists.

    An entry names one id, or a pattern with ``*`` or ``?`` (``"CH*"``: every
    Swiss region; ``"*ZZ"``: the extra-regio codes) that covers every unit it
    matches; an exact id wins over a pattern. The ids a pattern covered are
    written out in spatial_design_check.json.
    """
    from fnmatch import fnmatchcase

    exact: dict[str, str] = {}
    patterns: list[tuple[str, str]] = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or e.get("id") is None:
            continue
        uid, reason = str(e["id"]).strip(), str(e.get("reason") or "").strip()
        if any(c in uid for c in "*?"):
            patterns.append((uid, reason))
        else:
            exact[uid] = reason
    out = {}
    for u in without:
        if u in exact:
            out[u] = exact[u]
            continue
        hit = next((reason for pat, reason in patterns if fnmatchcase(u, pat)), None)
        if hit is not None:
            out[u] = hit
    return out


# ── before the analysis ─────────────────────────────────────────────────────


def check_spatial_design(workspace: Path, *, max_unmatched_share: float = DEFAULTS["max_unmatched_share"]) -> Verdict:
    """Check ``spatial_design.json`` against the data and the boundaries: rules (a) to (d)."""
    ws = Path(workspace)
    design, err = read_json(ws / DESIGN_FILE)
    if err:
        return Verdict(False, (f"(a) {err}: the data architect declares units, boundaries, CRS and weights there",))
    if not isinstance(design, dict):
        return Verdict(False, (f"(a) {DESIGN_FILE} must be a JSON object",))
    reasons: list[str] = []
    notes: list[str] = []
    stats: dict[str, Any] = {}

    units = obj(design.get("units"))
    bounds = obj(design.get("boundaries"))

    # (a) the boundaries' source
    source = str(bounds.get("source") or "").strip().lower()
    loads = _recorded_loads(ws)
    connectors = {str(d.get("connector") or d.get("source") or "").lower() for d in loads}
    if source in BOUNDARY_SOURCES:
        if source not in connectors:
            reasons.append(
                f"(a) the boundaries come from {source}, but data_sources.json records no load from it; "
                f"load them with `e2er-data {source} …  --table <name>`"
            )
    elif bounds.get("file") or bounds.get("table"):
        # Boundaries the researcher brought (a GeoJSON file, or a table loaded from their file).
        missing = [k for k in ("source", "licence", "attribution") if not str(bounds.get(k) or "").strip()]
        if missing:
            where = bounds.get("file") or bounds.get("table")
            reasons.append(
                f"(a) the boundaries {where} need {', '.join(missing)}: where the geometry comes "
                "from and under what terms (or load them with e2er-data " + " or ".join(BOUNDARY_SOURCES) + ")"
            )
    else:
        reasons.append(
            "(a) boundaries must name the table a load from "
            + " or ".join(BOUNDARY_SOURCES)
            + " wrote (source, table, id_column, geometry_column), or the researcher's own boundaries "
            "(a GeoJSON file under data/ or a table) with their source, licence and attribution"
        )
    stats["boundary_source"] = source or str(bounds.get("file") or "")

    geoms, why, meta = load_boundaries(ws, bounds)
    if geoms is None:
        reasons.append(f"(a) {why}")

    # (b) the CRS
    crs = crs_code(design.get("crs"))
    if crs is None:
        reasons.append(
            "(b) crs must state the coordinate reference system of the boundaries' coordinates, "
            "e.g. 'EPSG:4326' (longitude, latitude) or 'EPSG:3035' (ETRS89-LAEA, metres)"
        )
    elif geoms:
        stats["crs"] = f"EPSG:{crs}"
        pts = [p for g in geoms.values() for p in _coords(g)]
        lonlat = all(-180.5 <= x <= 180.5 and -90.5 <= y <= 90.5 for x, y in pts)
        if crs in _GEOGRAPHIC and not lonlat:
            reasons.append(f"(b) crs EPSG:{crs} is geographic, but the coordinates are not longitudes and latitudes")
        if crs not in _GEOGRAPHIC and lonlat:
            reasons.append(
                f"(b) crs EPSG:{crs} is projected (metres), but every coordinate lies within longitude and "
                "latitude ranges; the boundaries are probably EPSG:4326"
            )
        stated = crs_code(meta.get("crs")) if meta.get("crs") else None
        if stated and stated != crs:
            reasons.append(f"(b) the GeoJSON file declares EPSG:{stated}, the design EPSG:{crs}")

    # (c) data units without geometry
    t, idc = units.get("table"), units.get("id_column")
    if not t or not idc:
        reasons.append("(c) units needs table and id_column: where the data's unit ids are in data.db")
    elif geoms is not None:
        rows, why = read_columns(ws, t, [idc])
        if rows is None:
            reasons.append(f"(c) units: {why}")
        else:
            ids = sorted({str(r[0]) for r in rows if r[0] is not None})
            without = [u for u in ids if u not in geoms]
            listed = _listed_reasons(design.get("units_without_geometry"), without)
            unlisted = [u for u in without if u not in listed]
            no_reason = [u for u in without if u in listed and not listed[u]]
            stats.update({"data_units": len(ids), "with_geometry": len(ids) - len(without), "without": len(without)})
            if unlisted:
                reasons.append(
                    f"(c) {len(unlisted)} unit(s) of {t}.{idc} have no geometry in the boundaries and are not "
                    f"listed under units_without_geometry: {names(unlisted)}"
                )
            if no_reason:
                reasons.append(f"(c) units_without_geometry needs a reason for {names(no_reason)}")
            if ids and len(without) / len(ids) > max_unmatched_share:
                reasons.append(
                    f"(c) {len(without)} of {len(ids)} units ({len(without) / len(ids):.0%}) have no geometry, more "
                    f"than {max_unmatched_share:.0%}: the boundaries do not fit the data (level, year or id scheme)"
                )
            extra = [u for u in geoms if u not in set(ids)]
            if extra:
                notes.append(f"{len(extra)} boundary unit(s) have no data (drawn as no data on maps)")
            if without and not unlisted:
                notes.append(f"units without geometry, listed with reasons: {names(without)}")
            write_json(
                ws / DESIGN_CHECK_FILE,
                {
                    "data_units": len(ids),
                    "with_geometry": len(ids) - len(without),
                    "without_geometry": without,
                    "reasons": {u: listed.get(u, "") for u in without},
                    "boundary_units_without_data": extra,
                    "crs": f"EPSG:{crs}" if crs else None,
                },
            )

    # (d) the weights
    w = obj(design.get("weights")) or None
    if w is None:
        reasons.append("(d) weights must document the spatial weights: type, row_standardised, islands")
    else:
        wt = weights_type(w.get("type"))
        if wt is None:
            reasons.append(f"(d) weights.type {w.get('type')!r} is not one e2er knows: " + ", ".join(WEIGHT_TYPES))
        else:
            stats["weights"] = wt
            for k in WEIGHT_TYPES[wt]:
                if num(w.get(k)) is None:
                    reasons.append(f"(d) weights of type {wt} need a numeric '{k}'")
        if not isinstance(w.get("row_standardised"), bool):
            reasons.append("(d) weights.row_standardised must be true or false")
        if not str(w.get("islands") or "").strip():
            reasons.append(
                "(d) weights.islands must say how units without neighbours are handled (dropped, linked to the "
                "nearest unit, kept with no neighbours)"
            )
    return Verdict(not reasons, tuple(reasons), tuple(notes), stats)


# ── after the analysis ──────────────────────────────────────────────────────


def _read_weights(path: Path) -> tuple[list[tuple[str, str, float]] | None, str]:
    rows, why = read_csv(path)
    if rows is None:
        return None, why
    out: list[tuple[str, str, float]] = []
    for i, r in enumerate(rows):
        a, b, wv = r.get("from"), r.get("to"), to_float(r.get("weight"))
        if a is None or b is None or wv is None:
            return None, f"{path.name} row {i + 2} needs from, to and a numeric weight"
        out.append((str(a), str(b), wv))
    return out, ""


def morans_i(values: dict[str, float], links: list[tuple[str, str, float]]) -> float | None:
    """Moran's I of ``values`` under the weights ``links`` (from, to, weight)."""
    ids = [u for u in values]
    n = len(ids)
    if n < 2:
        return None
    mean = sum(values.values()) / n
    z = {u: values[u] - mean for u in ids}
    denom = sum(v * v for v in z.values())
    s0 = sum(w for a, b, w in links if a in z and b in z)
    if denom == 0 or s0 == 0:
        return None
    num_ = sum(w * z[a] * z[b] for a, b, w in links if a in z and b in z)
    return (n / s0) * num_ / denom


def check_spatial_results(workspace: Path, *, min_permutations: int = int(DEFAULTS["min_permutations"])) -> Verdict:
    """Check the spatial results: rules (e) to (h); add map figures built from the design."""
    ws = Path(workspace)
    results, err = read_json(ws / "estimation_results.json")
    if err:
        return Verdict(False, (f"(f) {err}",))
    if not isinstance(results, dict) or not results:
        return Verdict(False, ("(f) estimation_results.json is empty",))
    design, _ = read_json(ws / DESIGN_FILE)
    design = design if isinstance(design, dict) else {}
    reasons: list[str] = []
    notes: list[str] = []
    stats: dict[str, Any] = {}

    units = obj(results.get("units"))
    units_file = str(units.get("file") or UNITS_FILE)
    urows, why = read_csv(ws / units_file)
    # The units file's id column: `id` (the schema's), else the one units.id_column or units.id_field names
    # (id_field often names the data's own column, e.g. Eurostat's `geo`).
    named = [str(units[k]) for k in ("id_column", "id_field") if units.get(k)]
    header = list(urows[0]) if urows else []
    id_col = next((c for c in ["id", *named] if c in header), "id")
    if urows is None:
        reasons.append(
            f"(e) {why}: the analysis writes the units and values it used there (id, one column per variable)"
        )
        urows = []
    elif urows and id_col not in urows[0]:
        reasons.append(f"(e) {units_file} has no id column: name it 'id' (or name it in units.id_column)")
        urows = []
    unit_ids = [str(r[id_col]) for r in urows]
    stats["units"] = len(unit_ids)
    n_units = num(units.get("n_units"))
    if urows and n_units is not None and int(n_units) != len(unit_ids):
        reasons.append(f"(e) units.n_units is {int(n_units)}, but {units_file} has {len(unit_ids)} units")

    w_design = obj(design.get("weights"))
    row_std = w_design.get("row_standardised")
    weight_files: dict[str, list[tuple[str, str, float]]] = {}

    def weights(name: str) -> list[tuple[str, str, float]] | None:
        if name in weight_files:
            return weight_files[name]
        links, why = _read_weights(ws / name)
        if links is None:
            reasons.append(f"(e) {why}: the analysis writes the weights it used there (from, to, weight)")
            weight_files[name] = []
            return None
        known = set(unit_ids)
        strangers = sorted({u for a, b, _w in links for u in (a, b) if u not in known})
        if known and strangers:
            reasons.append(f"(e) {name} names units {units_file} has not: {names(strangers)}")
        selfs = sorted({a for a, b, _w in links if a == b})
        if selfs:
            reasons.append(f"(e) {name} links units to themselves: {names(selfs)}")
        if row_std is True and name == WEIGHTS_FILE:
            sums: dict[str, float] = {}
            for a, _b, wv in links:
                sums[a] = sums.get(a, 0.0) + wv
            off = sorted(u for u, s in sums.items() if abs(s - 1) > 1e-6)
            if off:
                reasons.append(f"(e) {name} is declared row-standardised, but rows do not sum to 1: {names(off)}")
        with_nb = {a for a, _b, _w in links}
        islands = [u for u in unit_ids if u not in with_nb]
        if islands:
            notes.append(f"{len(islands)} unit(s) have no neighbours in {name}: {names(islands)}")
        weight_files[name] = links
        return links

    # (f), (g) Moran's I
    stats_block = obj(results.get("spatial_statistics"))
    morans = {
        k: s for k, s in stats_block.items() if isinstance(s, dict) and "moran" in str(s.get("statistic") or "").lower()
    }
    permuted = []
    for key, s in morans.items():
        method = str(s.get("p_value_method") or "")
        n_perm = num(s.get("n_permutations"))
        p = num(s.get("p_value"))
        if "permut" in method.lower():
            if n_perm is None or n_perm < min_permutations:
                reasons.append(f"(f) spatial_statistics.{key}: n_permutations must be at least {min_permutations}")
            elif p is not None and p < 1 / (n_perm + 1) - 1e-9:
                reasons.append(
                    f"(f) spatial_statistics.{key}: p = {p} is below 1 / (permutations + 1) = {1 / (n_perm + 1):.4g}, "
                    "the smallest p-value a permutation test can give"
                )
            else:
                permuted.append(key)
        variable = str(s.get("variable") or "")
        wfile = str(s.get("weights_file") or WEIGHTS_FILE)
        links = weights(wfile)
        est = num(s.get("estimate"))
        if links and urows and variable and est is not None:
            if variable not in urows[0]:
                reasons.append(f"(g) spatial_statistics.{key}: {units_file} has no column {variable}")
                continue
            values = {str(r[id_col]): v for r in urows if (v := to_float(r.get(variable))) is not None}
            got = morans_i(values, links)
            if got is None:
                reasons.append(
                    f"(g) spatial_statistics.{key}: Moran's I cannot be computed from {units_file} and {wfile}"
                )
            elif not close(got, est, rel=0.01, abs_=1e-3):
                reasons.append(
                    f"(g) spatial_statistics.{key}: the reported Moran's I {est} does not follow from {units_file} "
                    f"and {wfile} (e2er computes {got:.4f})"
                )
            else:
                stats[key] = round(got, 4)
    if not morans:
        reasons.append("(f) spatial_statistics reports no Moran's I (statistic 'morans_i')")
    elif not permuted:
        reasons.append(
            "(f) no Moran's I has permutation inference: set p_value_method to 'permutation' and report "
            f"n_permutations (at least {min_permutations}) with the pseudo p-value"
        )
    if not morans:
        weights(WEIGHTS_FILE)

    # LISA clusters (optional)
    clusters = results.get("clusters")
    if isinstance(clusters, dict) and clusters:
        total = 0
        for k, c in clusters.items():
            cnt = num((c or {}).get("count")) if isinstance(c, dict) else None
            if cnt is None or cnt < 0 or cnt != int(cnt):
                reasons.append(f"clusters.{k} needs a whole count")
                break
            total += int(cnt)
        else:
            if unit_ids and total > len(unit_ids):
                reasons.append(f"clusters add up to {total}, more than the {len(unit_ids)} units")
        stats["lisa"] = True

    # (h) maps
    problem = _ensure_maps(ws, results, design, units_file, id_col, notes)
    if problem:
        reasons.append(problem)

    write_json(ws / RESULTS_CHECK_FILE, {"passed": not reasons, "reasons": reasons, "notes": notes, "stats": stats})
    return Verdict(not reasons, tuple(reasons), tuple(notes), stats)


def _ensure_maps(
    ws: Path, results: dict[str, Any], design: dict[str, Any], units_file: str, id_col: str, notes: list[str]
) -> str | None:
    maps = [m for m in results.get("maps") or [] if isinstance(m, dict) and m.get("id")]
    if not maps:
        return None  # the results contract asks for maps
    spec_path = ws / "figure_spec.json"
    spec, err = read_json(spec_path)
    if spec is None and spec_path.is_file():
        return f"(h) {err}"
    spec = spec if isinstance(spec, dict) else {}
    figures = lst(spec.get("figures"))
    by_name = {str(f.get("filename")): f for f in figures if isinstance(f, dict)}
    bounds = obj(design.get("boundaries")) or None
    added = []
    for m in maps:
        filename = str(m.get("figure") or f"fig_{m['id']}.pdf")
        fig = by_name.get(filename)
        if fig is not None and _DRAWN_BY in str(fig.get("source") or ""):
            figures = [f for f in figures if f is not fig]  # drawn again from the results as they are now
            fig = None
        if fig is not None:
            if fig.get("figure_type") != "map":
                return f"(h) maps.{m['id']}: figure {filename} in figure_spec.json is not a map"
            continue
        if bounds is None:
            return (
                f"(h) maps.{m['id']}: no map figure {filename}, and spatial_design.json names no boundaries to draw it"
            )
        b = {k: v for k, v in bounds.items() if k in ("table", "id_column", "geometry_column", "file", "id_property")}
        fig = {
            "filename": filename,
            "figure_type": "map",
            "map_type": "categories" if m.get("classification") == "categories" else "choropleth",
            "title": str(m.get("title") or ""),
            "boundaries": b,
            "data": {"file": units_file, "id_column": id_col, "value_column": str(m["variable"])},
            "classification": str(m.get("classification") or "quantiles"),
            "classes": int(num(m.get("classes")) or 5),
            "crs": str(design.get("crs") or "EPSG:4326"),
            "projection": str(m.get("projection") or design.get("map_projection") or "auto"),
            "legend_label": str(m.get("legend_label") or m["variable"]),
            "attribution": str(bounds.get("attribution") or ""),
            "source": f"estimation_results.json#maps.{m['id']} ({_DRAWN_BY})",
        }
        for k in ("extent", "categories", "breaks", "colormap"):
            if m.get(k) is not None:
                fig[k] = m[k]
        figures.append(fig)
        added.append(filename)
    if added:
        spec["figures"] = figures
        write_json(spec_path, spec)
        notes.append(f"map figure(s) added to figure_spec.json from the results: {', '.join(added)}")
    return None
