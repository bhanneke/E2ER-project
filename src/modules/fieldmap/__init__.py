"""Field map: main path analysis of a research field's citation network.

Deterministic code only. A boundary (search terms, journals, years) is
retrieved from OpenAlex; the citations inside the retrieved set form a
network; search path count (SPC) weights, the main path and key routes are
computed on it; the same is repeated for alternative boundaries to see which
papers hold; the results are exported and drawn.

Modules:

- ``openalex``: retrieval of a boundary from OpenAlex (paged, cached, counted).
- ``network``: the internal citation network, its completeness report and the
  deterministic handling of citation cycles.
- ``mainpath``: SPC weights (Batagelj 2003), the global and local main paths
  (Hummon and Doreian 1989; Liu and Lu 2012) and key routes (Liu and Lu 2012).
- ``robustness``: main paths across alternative boundaries.
- ``exports``: Pajek, GEXF, VOSviewer, CSV edge list, reading list, tables.
- ``figure``: the map (year by lane, main path and key routes).
- ``workflow``: the steps the field-map template runs, on a study's workspace.
- ``cli``: ``e2er-fieldmap``, the command the template's specialists use.

The workflow follows Michal Hron's article "Map a research field with Claude:
main path analysis, step by step" (LinkedIn, 8 October 2026); this
implementation is independent and uses OpenAlex. See ``credit.py``.
"""
