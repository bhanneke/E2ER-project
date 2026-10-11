# Figure Specification Format

When producing figures, output a `figure_spec.json` file with actual data values.
The pipeline renders these specs into publication-quality PDFs deterministically.
Do NOT write matplotlib/seaborn code or attempt to generate figures yourself.

## Structure

```json
{
  "figures": [
    {
      "filename": "fig_coefficient_main.pdf",
      "figure_type": "coefficient",
      "label": "fig:main_coefficients",
      "caption_hint": "Main regression coefficients with 95% confidence intervals",
      ...type-specific fields...
    }
  ]
}
```

## Supported Figure Types

### coefficient — Horizontal coefficient plot with CIs
```json
{
  "figure_type": "coefficient",
  "coefficients": [
    {"name": "Treatment", "estimate": 0.15, "ci_lower": 0.08, "ci_upper": 0.22},
    {"name": "Post x Treat", "estimate": -0.03, "ci_lower": -0.10, "ci_upper": 0.04}
  ],
  "reference_line": 0,
  "x_label": "Effect size (percentage points)"
}
```

### event_study — Dynamic treatment effects
```json
{
  "figure_type": "event_study",
  "periods": [-4, -3, -2, -1, 0, 1, 2, 3, 4],
  "estimates": [0.01, -0.02, 0.00, 0.01, 0.15, 0.18, 0.20, 0.19, 0.17],
  "ci_lower": [-0.05, -0.08, -0.06, -0.05, 0.09, 0.12, 0.14, 0.13, 0.11],
  "ci_upper": [0.07, 0.04, 0.06, 0.07, 0.21, 0.24, 0.26, 0.25, 0.23],
  "treatment_period": 0,
  "x_label": "Periods relative to treatment",
  "y_label": "Coefficient estimate"
}
```

### time_series — Multi-series line plot
```json
{
  "figure_type": "time_series",
  "series": [
    {"label": "Treatment", "x": [1, 2, 3, 4, 5], "y": [10, 15, 22, 28, 35]},
    {"label": "Control", "x": [1, 2, 3, 4, 5], "y": [10, 12, 14, 16, 18]}
  ],
  "shaded_regions": [{"x_start": 3, "x_end": 5, "label": "Post-treatment"}],
  "x_label": "Month",
  "y_label": "Outcome variable"
}
```

A series may carry `lower` and `upper` (one value per point): the renderer
shades the band between them, e.g. a forecast's prediction interval. Periods
as text (`"2021-01"`) are drawn in the order given, with at most about
twelve labels on the axis.

### bar — Categorical comparison
```json
{
  "figure_type": "bar",
  "categories": ["Q1", "Q2", "Q3", "Q4"],
  "values": [12.5, 18.3, 15.7, 22.1],
  "errors": [2.1, 3.0, 2.5, 3.8],
  "y_label": "Returns (%)"
}
```

### binscatter — Binned scatter plot
```json
{
  "figure_type": "binscatter",
  "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
  "y": [2.1, 3.8, 5.2, 7.1, 8.9, 10.5, 12.3, 14.0, 15.8, 17.5],
  "fit_line": {"slope": 1.72, "intercept": 0.35},
  "x_label": "Log market cap",
  "y_label": "Average daily volume"
}
```

### distribution — Histogram with optional KDE
```json
{
  "figure_type": "distribution",
  "values": [0.1, 0.5, 0.8, 1.2, ...],
  "bins": 30,
  "kde_overlay": true,
  "vertical_lines": [{"x": 0.5, "label": "Median"}],
  "x_label": "Returns",
  "y_label": "Count"
}
```

### scatter — Two variables, point by point
```json
{
  "figure_type": "scatter",
  "x": [3.2, 11.8, 54.1],
  "y": [1.4, 2.6, 11.2],
  "groups": ["Transit", "Transit", "Radial velocity"],
  "log_x": true,
  "x_label": "Orbital period (days)",
  "y_label": "Radius (Earth radii)"
}
```
`groups` (optional, one label per point) colours the points; `log_x` /
`log_y` put an axis on a log scale.

### histogram — Counts in bins the analysis computed
```json
{
  "figure_type": "histogram",
  "bins": [{"lower": 0.5, "upper": 1.0, "count": 6}, {"lower": 1.0, "upper": 2.0, "count": 19}],
  "x_label": "Radius (Earth radii)",
  "y_label": "Planets"
}
```
Use the bins of the results file (`distributions.<name>.bins`) so the figure
shows the counts the paper reports.

### map — Choropleth, categories or points, from saved data and boundaries
```json
{
  "filename": "fig_map_unemployment.pdf",
  "figure_type": "map",
  "map_type": "choropleth",
  "boundaries": {"table": "nuts2_boundaries", "id_column": "nuts_id", "geometry_column": "geometry"},
  "data": {"file": "spatial_units.csv", "id_column": "id", "value_column": "unemployment_rate"},
  "classification": "quantiles",
  "classes": 5,
  "crs": "EPSG:4326",
  "projection": "auto",
  "extent": [-25, 34, 45, 72],
  "legend_label": "Unemployment rate 2023 (%)",
  "attribution": "© EuroGeographics for the administrative boundaries"
}
```
A map is the one figure that reads files: `boundaries` is a data.db table of
GeoJSON geometries (as `e2er-data gisco` and `e2er-data naturalearth` load
them) or a GeoJSON file in the study folder (`file`, `id_property`); `data` is
a CSV in the study folder or a data.db table (`table`, `id_column`,
`value_column`), so the map shows the saved values, never typed-in ones.
`map_type`: `choropleth` (classed by `classification`: `quantiles`,
`equal_interval`, or `breaks` with ascending `breaks`), `categories` (one
category per unit, e.g. LISA clusters; `categories` maps each value to
`{"label", "color"}`) or `points` (`lon_column`, `lat_column`, optional
`value_column`, over the boundaries when given). `projection`: `auto`
(equal-area for Europe, Equal Earth for the world), `laea_europe`,
`equal_earth`, `plate_carree`, or `none` for projected coordinates. Units with
geometry but no value are drawn as "No data"; the legend counts each class.
Put the boundaries' required credit in `attribution`.

### multi_panel — Grid of sub-figures
```json
{
  "figure_type": "multi_panel",
  "ncols": 2,
  "panels": [
    {"figure_type": "time_series", "title": "Panel A", ...},
    {"figure_type": "bar", "title": "Panel B", ...}
  ]
}
```

## Where the values come from (`source`)

A template with a figure check (`figure_data`: the descriptive and the
time-series templates) re-reads every figure from the data it names and
stops the run when the values differ. Give each figure (each series of a
`time_series`, each panel of a `multi_panel`) a `source`:

```json
{"figure_type": "scatter", "x": [...], "y": [...], "groups": [...],
 "source": {"table": "planets", "columns": {"x": "pl_orbper", "y": "pl_rade", "groups": "discoverymethod"},
            "where": "pl_rade IS NOT NULL AND pl_orbper > 0"}}
{"figure_type": "histogram", "bins": [...], "source": {"results": "distributions.radius.bins"}}
{"label": "Forecast", "x": [...], "y": [...], "lower": [...], "upper": [...],
 "source": {"results": "forecasts.trend_2024.points",
            "fields": {"x": "period", "y": "forecast", "lower": "lower", "upper": "upper"}}}
```

- `table` + `columns`: the figure's lists are those columns of the data.db
  table, row for row (any order; rows with an empty value in a named column
  are left out). `where` is a simple condition on the table's columns
  (comparisons, AND, OR, NOT, IN, BETWEEN, LIKE, IS NULL).
- `results` (+ `fields`, + `file`, default `estimation_results.json`): the
  figure's lists are the keys of a list of objects in a results file. A
  histogram's `bins` match the list at `results` without `fields`.
- Numbers are compared at the precision the figure writes them.

## Rules

1. Embed ACTUAL numeric values from estimation results. Never use placeholders.
2. Maximum ~10,000 data points per figure. Pre-bin distributions if needed.
3. Use descriptive filenames: `fig_coefficient_main.pdf`, `fig_event_study.pdf`.
4. Provide a `label` for LaTeX `\ref{}` and a `caption_hint` for the drafter.
5. Skip figure types that don't fit the methodology.
6. All axis labels should include units where applicable.
