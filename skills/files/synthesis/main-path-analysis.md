# Main Path Analysis for Mapping a Research Field

How to map a research field from its citation network: choose the boundary of
the field, build the network of citations inside it, weight each citation by
how many citation chains run through it, follow the heaviest chain (the main
path) and its neighbours (key routes), test the result on other boundaries,
and draw it by year in lanes named as questions. In e2er the counting is done
by code (`e2er-fieldmap`, the `field-map` template); this file is for the
parts that need judgement and for reading the result.

---

## The method, step by step

### 1. The boundary

The boundary decides which papers exist for the analysis. Everything after it
is computed, so most of the judgement goes here.

- **Search terms.** Write the terms researchers in the field use in titles and
  abstracts, and the older names the topic went by. A field renamed in the
  1990s keeps its early papers under the old name; a boundary that searches
  only the current name starts the field too late, and the main path then
  begins at whoever first used the new word. Quote phrases (`"main path
  analysis"`) and join terms with OR; OpenAlex searches titles and abstracts
  (`search_in = "title_abstract"`), titles only (`"title"`) or full text where
  it has it (`"all"`).
- **Journals.** A journal set (OpenAlex source ids, `e2er-fieldmap sources
  "<journal>"`) restricts the boundary to the outlets where the field
  publishes. Journals change names, and an index may list each name as a
  source of its own (JASIST has appeared under three names); include every
  name the journal had in the years of the boundary.
- **Years.** Set a first year only if the field cannot predate it. Leave the
  last year open unless there is a reason; the robustness step tests the
  recent end separately.
- **Size.** Aim at 300 to 2,000 papers. Below that the network is too sparse
  for a path to mean much; above it the boundary usually catches neighbouring
  fields, and the main path runs through whichever neighbour is largest.
  `e2er-fieldmap count` reads the size with one request.
- **Alternatives.** Propose 2 to 6 alternative boundaries, each changing one
  choice: another journal set, the older names left out, a year range that ends
  a few years back, a title-only search. They are what the robustness step
  compares against.

### 2. The citation network and its completeness

Each paper's reference list is reduced to the references that are themselves in
the boundary. An arc runs from the cited to the citing paper, the direction in
which knowledge moves. Then check what is missing before trusting any path:

- **Papers without internal links** neither cite nor are cited by another paper
  of the set. They cannot be on the main path. A large share (e2er stops above
  60%) means the terms catch papers from other fields, or the field is
  fragmented.
- **Papers without references, or with unusually short reference lists** (under
  a quarter of the set's median). The database did not record their references.
  Their missing arcs are real citations the network does not have, and an
  important paper can fall off the main path for this reason alone. Check the
  listed papers you know matter; if many have no references, the coverage of
  this field is too thin.
- **Duplicates and notices.** A paper indexed twice (preprint and journal
  version, reprint) splits its citations; errata, corrigenda and retraction
  notices are not papers. Exclude them by id (`exclude` in the boundary).
- **Cycles.** Citation networks are almost acyclic. A cycle (two papers citing
  each other, usually working-paper versions, or a database error) makes path
  counts infinite. e2er drops, inside each cycle only, the arcs from a later to
  an earlier paper (ordered by year, date, id) and lists every arc it dropped.

### 3. Weights: search path count (SPC)

Add a source linked to every paper that cites nothing in the set and a sink
linked from every paper nothing in the set cites. The SPC weight of an arc is
the number of source-to-sink paths that run through it (Batagelj 2003): the
number of paths into the cited paper times the number of paths out of the
citing paper. An arc with a large SPC connects much of the earlier literature to
much of the later. Two consequences:

- Weights are counts in one network. They grow with the network's size and
  depth, so compare them only within one boundary. The share of all
  source-to-sink paths (SPC divided by the total) is easier to read.
- SPC rewards arcs that sit between many origins and many end points, which
  favours the middle of the field's history over its ends.

Hummon and Doreian (1989) introduced three weights (NPPC, SPLC, SPNP);
Batagelj (2003) showed how to compute them in linear time and proposed SPC,
the weight most later studies use.

### 4. The main path and key routes

- **Global main path** (Liu and Lu 2012): the source-to-sink chain whose arcs
  have the largest total SPC. This is what e2er calls the main path. When
  several chains tie, all of them are kept, and the count of tied chains is
  reported.
- **Local (forward) main path** (Hummon and Doreian 1989): from the start, take
  the heaviest next arc at every step. It can miss the heaviest chain overall
  because each step looks one arc ahead; e2er reports it next to the global one.
- **Key routes** (Liu and Lu 2012): take the k heaviest arcs (e2er: 10, and every
  arc tied with the tenth) and extend each backward and forward along the
  heaviest chain. The union shows branches the single main path hides. A larger
  k shows more of the field and less of its spine.

### 5. Robustness

Run the same analysis on each alternative boundary. A paper on the main path of
every boundary is robust: the field's spine runs through it whatever reasonable
choice was made. A paper on the main path of one boundary only depends on that
boundary. Report both, with the count of boundaries for each paper. Expect the
recent end to move most.

### 6. The map

Draw the papers of the main path and the key routes by publication year (x) in
lanes (y). A lane is a strand of the field, named as the question its papers
answer ("How should a main path be computed?"), so the map reads as a sequence
of questions the field worked on. The lane mapper proposes lanes from titles and
abstracts only; the researcher checks them, because a lane is an interpretation
and the citation network does not contain it.

Outputs of the e2er template: the map (PNG and PDF), the reading list (authors,
year, title, journal, DOI, whether on the main path or a key route, on how many
boundaries' main paths), the heaviest links, and the network for other tools
(Pajek `.net`, Gephi GEXF, VOSviewer map and network files, CSV edge list).

---

## Reading the map

- The main path shows how citations flow through the field: which papers
  connect earlier work to later work. It does not show what the field believes,
  which papers are right, or which are cited most. A heavily cited paper off the
  main path is usually cited from one branch only.
- The end of the path is unsettled. Recent papers have had little time to be
  cited, so the last few papers on the path are those that cite the right
  predecessors, and the path's end will move as citations arrive.
- A run of papers by one group citing each other (a self-citing chain) can carry
  the path. Look at the authors of consecutive papers before reading a chain as
  the field's direction.
- The boundary decides the result. Say which boundary the map is drawn from and
  what the alternatives changed.

## Pitfalls

1. **Short or missing reference lists** drop arcs and with them papers; check
   the completeness report before the path.
2. **Recent papers are under-cited**; treat the last years of the path as
   provisional.
3. **Database coverage** differs by field and period; books, conference papers
   and non-English work are less complete in every index, OpenAlex included.
4. **Title and abstract matching is rough**: terms catch neighbouring fields and
   miss papers that use other words; the alternative boundaries test this.
5. **The path shows citation flow**, not the field's beliefs or its quality.
6. **Results depend on the boundary**; report the robustness across boundaries
   with the map.

## Writing the field review

State every number from `field_map_results.json`. Organise the review by lane,
in the order the main path moves through them, and cite each main-path paper.
Name the boundary and the alternatives, report the completeness figures, and
state the pitfalls above that apply. Do not explain why a paper is on the path
beyond what the citations show; whether it changed the field is a claim the
network cannot support.

---

## Sources and credit

The workflow follows Michal Hron's article
"Map a research field with Claude: main path analysis, step by step"
(LinkedIn Pulse, 8 October 2026,
https://www.linkedin.com/pulse/map-research-field-claude-main-path-analysis-step-michal-hron-jm2ge/,
read on 2026-10-08; shared by Björn Hanneke); this implementation is
independent and uses OpenAlex. Taken from the article: the six-step workflow
(boundary, internal citation network with completeness checks, SPC weights,
main path and key routes, robustness across journal sets, lanes named as
questions) and the pitfalls it lists. Hron's own implementation, on Scopus, is
at https://github.com/michalhron/scopus-plus-mcp (MIT); nothing of it is used
here. This text and e2er's code were written from the methods literature below.

- Hummon, N. P., and Doreian, P. (1989). Connectivity in a citation network:
  The development of DNA theory. *Social Networks*, 11(1), 39-63.
  https://doi.org/10.1016/0378-8733(89)90017-8
- Batagelj, V. (2003). Efficient algorithms for citation network analysis.
  arXiv preprint cs/0309023. https://doi.org/10.48550/arXiv.cs/0309023
- Liu, J. S., and Lu, L. Y. Y. (2012). An integrated approach for main path
  analysis: Development of the Hirsch index as an example. *Journal of the
  American Society for Information Science and Technology*, 63(3), 528-542.
  https://doi.org/10.1002/asi.21692
- Priem, J., Piwowar, H., and Orr, R. (2022). OpenAlex: A fully-open index of
  scholarly works, authors, venues, institutions, and concepts. arXiv preprint
  2205.01833. (The data source; CC0.)
