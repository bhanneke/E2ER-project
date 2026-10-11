"""Maps from saved data and boundaries: the ``map`` figure type of ``figure_spec.json``.

A map figure names its boundaries and its values; nothing is drawn from
numbers the specification itself makes up:

```json
{"filename": "fig_map_unemployment.pdf", "figure_type": "map", "map_type": "choropleth",
 "boundaries": {"table": "nuts2_boundaries", "id_column": "nuts_id", "geometry_column": "geometry"},
 "data": {"file": "spatial_units.csv", "id_column": "id", "value_column": "unemployment_rate"},
 "classification": "quantiles", "classes": 5, "crs": "EPSG:4326", "projection": "auto",
 "legend_label": "Unemployment rate (%)", "attribution": "© EuroGeographics for the administrative boundaries"}
```

- ``boundaries``: a ``data.db`` table with GeoJSON geometries (as ``e2er-data
  gisco`` and ``e2er-data naturalearth`` load them) or a GeoJSON file in the
  study folder (``file``, ``id_property``).
- ``data``: the values by unit, from a CSV file in the study folder or a
  ``data.db`` table (``table``, ``id_column``, ``value_column``), or inline
  ``values`` ({id: value}). For ``map_type: "points"``: ``lon_column`` and
  ``lat_column`` (and an optional ``value_column``), drawn over the
  boundaries when the figure names any.
- ``map_type``: ``choropleth`` (classed values), ``categories`` (a category
  per unit, e.g. LISA clusters; ``categories`` maps each value to a label and
  an optional colour) or ``points``.
- ``classification``: ``quantiles`` (default), ``equal_interval`` or
  ``breaks`` (the upper bounds of the classes, ascending).
- ``projection``: ``auto`` (Lambert azimuthal equal-area centred on Europe for
  coordinates inside Europe, Equal Earth otherwise), ``laea_europe``,
  ``equal_earth``, ``plate_carree``, or ``none`` for coordinates that are
  already projected (``crs`` other than EPSG:4326). Spherical formulas: maps
  for reading, not for measuring.
- ``extent``: [west, south, east, north] in degrees, the part of the world
  shown (e.g. leave out overseas regions); units outside it are still drawn
  where they overlap.

Units with data but no geometry cannot be drawn and are named in the
figure's note; units with geometry but no data are drawn as "No data". Only
matplotlib is needed (no GeoPandas): GeoJSON polygons become matplotlib paths.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..pipeline.checks_common import obj

#: Colours of a categories map when the specification gives none (LISA's usual reds and blues first).
_CATEGORY_COLOURS = ("#b2182b", "#2166ac", "#f4a582", "#92c5de", "#bdbdbd", "#1b7837", "#762a83", "#e08214")
_NO_DATA = "#e6e6e6"
_EUROPE = (-25.0, 34.0, 45.0, 72.0)


# ── projections (spherical; inputs in degrees) ──────────────────────────────


def _laea_europe(lon: float, lat: float) -> tuple[float, float]:
    """Lambert azimuthal equal-area centred at 52N 10E (the centre of EPSG:3035), on a sphere, in km."""
    r = 6371.0
    lam, phi = math.radians(lon - 10.0), math.radians(lat)
    phi1 = math.radians(52.0)
    denom = 1 + math.sin(phi1) * math.sin(phi) + math.cos(phi1) * math.cos(phi) * math.cos(lam)
    k = math.sqrt(2 / denom) if denom > 1e-12 else 0.0
    x = r * k * math.cos(phi) * math.sin(lam)
    y = r * k * (math.cos(phi1) * math.sin(phi) - math.sin(phi1) * math.cos(phi) * math.cos(lam))
    return x, y


def _equal_earth(lon: float, lat: float) -> tuple[float, float]:
    """Equal Earth (Šavrič, Patterson and Jenny 2018), unit sphere."""
    a1, a2, a3, a4 = 1.340264, -0.081106, 0.000893, 0.003796
    m = math.sqrt(3) / 2
    lam, phi = math.radians(lon), math.radians(lat)
    th = math.asin(m * math.sin(phi))
    t2 = th * th
    t6 = t2 * t2 * t2
    x = 2 * math.sqrt(3) * lam * math.cos(th) / (3 * (9 * a4 * t6 * t2 + 7 * a3 * t6 + 3 * a2 * t2 + a1))
    y = th * (a1 + a2 * t2 + t6 * (a3 + a4 * t2))
    return x, y


def _identity(x: float, y: float) -> tuple[float, float]:
    return x, y


def _etrs89_laea(lon: float, lat: float) -> tuple[float, float]:
    """EPSG:3035 in metres, on a sphere (within a few km of the ellipsoidal projection): for framing maps."""
    x, y = _laea_europe(lon, lat)
    return 4321000.0 + 1000.0 * x, 3210000.0 + 1000.0 * y


def _web_mercator(lon: float, lat: float) -> tuple[float, float]:
    """EPSG:3857 in metres."""
    r = 6378137.0
    lat = max(-85.0, min(85.0, lat))
    return r * math.radians(lon), r * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _extent_projection(proj_name: str, crs: str, proj: Any) -> Any:
    """How an extent in degrees maps onto the drawn coordinates; None when it cannot."""
    from ..pipeline.spatial_checks import crs_code

    if proj_name != "none":
        return proj
    return {"3035": _etrs89_laea, "3857": _web_mercator}.get(crs_code(crs) or "")


def _to_coords_or_same(proj_name: str, to_coords: Any, p: Any) -> tuple[float, float]:
    """A vertex in the extent's drawn coordinates: projected from degrees, or as stored when already projected."""
    if proj_name == "none":
        return float(p[0]), float(p[1])
    return to_coords(float(p[0]), float(p[1]))


PROJECTIONS = {"laea_europe": _laea_europe, "equal_earth": _equal_earth, "plate_carree": _identity, "none": _identity}


def _rings(geom: dict[str, Any]) -> list[list[list[list[float]]]]:
    """Polygons as lists of rings (exterior first), for Polygon and MultiPolygon."""
    t = geom.get("type")
    c: Any = geom.get("coordinates") or []
    if t == "Polygon":
        return [c]
    if t == "MultiPolygon":
        return list(c)
    return []


def _choose_projection(name: str, crs: str, geoms: dict[str, dict[str, Any]], extent: Any) -> str:
    from ..pipeline.spatial_checks import crs_code

    code = crs_code(crs) or "4326"
    if code != "4326":
        return "none"
    if name and name != "auto":
        if name not in PROJECTIONS:
            raise ValueError(f"unknown projection {name!r}; use one of auto, {', '.join(PROJECTIONS)}")
        return name
    if isinstance(extent, list) and len(extent) == 4:
        w, s, e, n = (float(v) for v in extent)
        return "laea_europe" if w >= -35 and e <= 60 and s >= 25 else "equal_earth"
    lons = [p[0] for g in geoms.values() for poly in _rings(g) for p in poly[0][:: max(1, len(poly[0]) // 8)]]
    lats = [p[1] for g in geoms.values() for poly in _rings(g) for p in poly[0][:: max(1, len(poly[0]) // 8)]]
    if lons and _EUROPE[0] - 10 <= _median(lons) <= _EUROPE[2] and _EUROPE[1] <= _median(lats) <= _EUROPE[3]:
        return "laea_europe"
    return "equal_earth"


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2]


# ── reading what the figure names ───────────────────────────────────────────


def _read_values(workspace: Path, data: dict[str, Any], columns: list[str]) -> list[dict[str, Any]]:
    """Rows (dicts of the named columns) from a CSV in the study folder or a data.db table."""
    from ..pipeline.checks_common import read_columns, read_csv

    if data.get("file"):
        path = (workspace / str(data["file"])).resolve()
        if not path.is_relative_to(workspace.resolve()):
            raise ValueError(f"data.file {data['file']} lies outside the study folder")
        rows, why = read_csv(path)
        if rows is None:
            raise ValueError(f"data.file: {why}")
        if rows and any(c not in rows[0] for c in columns):
            raise ValueError(f"data.file {data['file']} lacks a column of {', '.join(columns)}")
        return [{c: r.get(c) for c in columns} for r in rows]
    if data.get("table"):
        got, why = read_columns(workspace, data["table"], columns)
        if got is None:
            raise ValueError(f"data.table: {why}")
        return [dict(zip(columns, r, strict=True)) for r in got]
    raise ValueError("map data needs 'file' (CSV in the study folder), 'table' (data.db) or 'values'")


def _num(v: Any) -> float | None:
    from ..pipeline.checks_common import to_float

    return to_float(v)


def _classes(values: list[float], spec: dict[str, Any]) -> list[float]:
    """Upper bounds of the classes (the last is the maximum)."""
    method = str(spec.get("classification") or "quantiles")
    k = max(2, min(9, int(spec.get("classes") or 5)))
    lo, hi = min(values), max(values)
    if method == "breaks":
        breaks = [float(b) for b in spec.get("breaks") or []]
        if not breaks or breaks != sorted(breaks):
            raise ValueError("classification 'breaks' needs ascending 'breaks'")
        return [*[b for b in breaks if b < hi], hi]
    if method == "equal_interval":
        return [lo + (hi - lo) * (i + 1) / k for i in range(k)]
    if method != "quantiles":
        raise ValueError(f"unknown classification {method!r} (quantiles, equal_interval, breaks, categories)")
    s = sorted(values)
    bounds = []
    for i in range(1, k + 1):
        q = i / k
        pos = q * (len(s) - 1)
        a, b = int(math.floor(pos)), int(math.ceil(pos))
        bounds.append(s[a] + (s[b] - s[a]) * (pos - a))
    return sorted(set(bounds))


def _fmt(x: float, span: float) -> str:
    digits = 0 if span >= 50 else 1 if span >= 5 else 2 if span >= 0.5 else 3
    return f"{x:,.{digits}f}"


# ── drawing ─────────────────────────────────────────────────────────────────


def _path(polys: list[list[list[list[float]]]], proj: Any) -> Any:
    from matplotlib.path import Path as MPath

    verts: list[tuple[float, float]] = []
    codes: list[int] = []
    for poly in polys:
        for ring in poly:
            pts = [proj(float(p[0]), float(p[1])) for p in ring if len(p) >= 2]
            if len(pts) < 3:
                continue
            verts += pts + [pts[0]]
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 1) + [MPath.CLOSEPOLY]
    return MPath(verts, codes) if verts else None


def render_map(plt: Any, fig_spec: dict[str, Any], workspace: Path) -> tuple[Any, list[str]]:
    """The matplotlib Figure of a map specification, and notes for the render report. Raises ValueError."""
    from matplotlib.colors import to_hex
    from matplotlib.patches import Patch, PathPatch

    from ..pipeline.spatial_checks import load_boundaries

    workspace = Path(workspace)
    notes: list[str] = []
    map_type = str(fig_spec.get("map_type") or "choropleth")
    if map_type not in ("choropleth", "categories", "points"):
        raise ValueError(f"unknown map_type {map_type!r} (choropleth, categories, points)")
    if fig_spec.get("classification") == "categories":
        map_type = "categories" if map_type == "choropleth" else map_type
    geoms: dict[str, dict[str, Any]] = {}
    if fig_spec.get("boundaries"):
        got, why, _meta = load_boundaries(workspace, fig_spec["boundaries"])
        if got is None:
            raise ValueError(why)
        geoms = got
    elif map_type != "points":
        raise ValueError("a choropleth or categories map needs 'boundaries'")

    data = obj(fig_spec.get("data"))
    extent = fig_spec.get("extent")
    proj_name = _choose_projection(
        str(fig_spec.get("projection") or "auto"), str(fig_spec.get("crs") or ""), geoms, extent
    )
    proj = PROJECTIONS[proj_name]

    fig, ax = plt.subplots(figsize=(6.4, 6.0))
    ax.set_aspect("equal")
    ax.axis("off")
    handles: list[Any] = []

    if map_type in ("choropleth", "categories"):
        if isinstance(fig_spec.get("values"), dict):
            values_raw = {str(k): v for k, v in fig_spec["values"].items()}
        else:
            idc, vc = str(data.get("id_column") or "id"), str(data.get("value_column") or "")
            if not vc:
                raise ValueError("map data needs value_column")
            values_raw = {str(r[idc]): r[vc] for r in _read_values(workspace, data, [idc, vc]) if r[idc] is not None}
        no_geom = sorted(u for u in values_raw if u not in geoms)
        if no_geom:
            notes.append(
                f"{len(no_geom)} unit(s) with data have no geometry and are not drawn: {', '.join(no_geom[:10])}"
            )
        colour: dict[str, str] = {}
        if map_type == "choropleth":
            vals = {u: x for u, v in values_raw.items() if (x := _num(v)) is not None}
            if not vals:
                raise ValueError("the map's values hold no numbers")
            bounds = _classes(list(vals.values()), fig_spec)
            cmap = plt.get_cmap(str(fig_spec.get("colormap") or "YlGnBu"))
            shades = [to_hex(cmap(0.15 + 0.8 * i / max(1, len(bounds) - 1))) for i in range(len(bounds))]
            span = max(vals.values()) - min(vals.values())
            lower = min(vals.values())
            counts = [0] * len(bounds)
            for u, x in vals.items():
                i = next((j for j, b in enumerate(bounds) if x <= b + 1e-12), len(bounds) - 1)
                colour[u] = shades[i]
                counts[i] += 1 if u in geoms else 0
            for i, b in enumerate(bounds):
                a = lower if i == 0 else bounds[i - 1]
                handles.append(
                    Patch(
                        facecolor=shades[i], edgecolor="0.4", label=f"{_fmt(a, span)} – {_fmt(b, span)} ({counts[i]})"
                    )
                )
        else:
            cats = obj(fig_spec.get("categories"))
            seen = list(dict.fromkeys(str(v) for v in values_raw.values() if v is not None and str(v) != ""))
            order = [c for c in cats if c in seen] + [c for c in seen if c not in cats]
            palette = {}
            for i, c in enumerate(order):
                entry = obj(cats.get(c))
                palette[c] = str(entry.get("color") or _CATEGORY_COLOURS[i % len(_CATEGORY_COLOURS)])
                n = sum(1 for u, v in values_raw.items() if str(v) == c and u in geoms)
                label = str(entry.get("label") or (cats.get(c) if isinstance(cats.get(c), str) else c))
                handles.append(Patch(facecolor=palette[c], edgecolor="0.4", label=f"{label} ({n})"))
            for u, v in values_raw.items():
                if v is not None and str(v) in palette:
                    colour[u] = palette[str(v)]
        missing = 0
        for u, g in geoms.items():
            p = _path(_rings(g), proj)
            if p is None:
                continue
            face = colour.get(u)
            if face is None:
                missing += 1
            ax.add_patch(
                PathPatch(
                    p,
                    facecolor=face or _NO_DATA,
                    edgecolor="white" if face else "0.75",
                    linewidth=0.25,
                    hatch=None if face else "////",
                )
            )
        if missing:
            handles.append(Patch(facecolor=_NO_DATA, edgecolor="0.75", hatch="////", label=f"No data ({missing})"))
    else:
        for g in geoms.values():
            p = _path(_rings(g), proj)
            if p is not None:
                ax.add_patch(PathPatch(p, facecolor="#f2f2f2", edgecolor="0.6", linewidth=0.3))
        lon_c, lat_c = str(data.get("lon_column") or "lon"), str(data.get("lat_column") or "lat")
        vc = str(data.get("value_column") or "")
        rows = _read_values(workspace, data, [lon_c, lat_c, *([vc] if vc else [])])
        xs, ys, cs = [], [], []
        for r in rows:
            lon, lat = _num(r[lon_c]), _num(r[lat_c])
            if lon is None or lat is None:
                continue
            x, y = proj(lon, lat)
            xs.append(x)
            ys.append(y)
            cs.append(_num(r[vc]) if vc else None)
        if not xs:
            raise ValueError("the point map has no point with numeric longitude and latitude")
        if vc and all(c is not None for c in cs):
            sc = ax.scatter(xs, ys, c=cs, s=10, cmap=str(fig_spec.get("colormap") or "viridis"), zorder=3)
            fig.colorbar(sc, ax=ax, shrink=0.6, label=str(fig_spec.get("legend_label") or vc))
        else:
            ax.scatter(xs, ys, s=8, color="#1f4e79", zorder=3)

    # The part of the world shown: the drawn vertices that lie inside the extent (given in degrees), with a
    # margin. For coordinates already projected (EPSG:3035, EPSG:3857) the extent is projected the same way.
    to_coords = _extent_projection(proj_name, str(fig_spec.get("crs") or ""), proj)
    if isinstance(extent, list) and len(extent) == 4 and to_coords is not None:
        west, south, east, north = (float(v) for v in extent)
        edge = [to_coords(west + (east - west) * i / 20, y) for i in range(21) for y in (south, north)]
        edge += [to_coords(x, south + (north - south) * i / 20) for i in range(21) for x in (west, east)]
        x0, x1 = min(p[0] for p in edge), max(p[0] for p in edge)
        y0, y1 = min(p[1] for p in edge), max(p[1] for p in edge)
        inside = [
            proj(float(p[0]), float(p[1]))
            for g in geoms.values()
            for poly in _rings(g)
            for ring in poly
            for p in ring
            if len(p) >= 2 and x0 <= (q := _to_coords_or_same(proj_name, to_coords, p))[0] <= x1 and y0 <= q[1] <= y1
        ]
        if not inside:
            inside = edge if proj_name == "none" else [proj(x, y) for x in (west, east) for y in (south, north)]
        xs_, ys_ = [p[0] for p in inside], [p[1] for p in inside]
        mx, my = 0.02 * (max(xs_) - min(xs_) or 1), 0.02 * (max(ys_) - min(ys_) or 1)
        ax.set_xlim(min(xs_) - mx, max(xs_) + mx)
        ax.set_ylim(min(ys_) - my, max(ys_) + my)
    else:
        ax.autoscale_view()
    if handles:
        ax.legend(
            handles=handles,
            title=str(fig_spec.get("legend_label") or ""),
            loc="upper left",
            fontsize=7,
            title_fontsize=8,
            frameon=False,
            bbox_to_anchor=(1.0, 1.0),
        )
    if fig_spec.get("title"):
        ax.set_title(str(fig_spec["title"]), fontsize=10)
    attribution = str(fig_spec.get("attribution") or "").strip()
    if attribution:
        fig.text(0.99, 0.01, attribution, ha="right", va="bottom", fontsize=6, color="0.35")
    notes.append(f"projection: {proj_name}")
    return fig, notes


def map_spec_problems(fig_spec: dict[str, Any]) -> list[str]:
    """Structural problems of a map specification, without reading any file."""
    problems = []
    if fig_spec.get("map_type", "choropleth") != "points" and not fig_spec.get("boundaries"):
        problems.append("needs 'boundaries'")
    if not isinstance(fig_spec.get("values"), dict) and not isinstance(fig_spec.get("data"), dict):
        problems.append("needs 'data' (file or table) or 'values'")
    return problems
