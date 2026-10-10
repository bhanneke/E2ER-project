# Polish of the numbers

Read every number in the text against `estimation_results.json` and
`summary_statistics.json`. The tables come from the renderer and are not
touched here.

| Where | Text says | Source says | Note |
|---|---|---|---|
| Abstract, Introduction, Results | hikes $-1.06\%$, $p = 0.0603$ | `h1_hikes_m1p1`: $-1.0588$, $p = 0.0603$ | agrees |
| Abstract, Introduction, Results | cuts $-0.08\%$, $p = 0.9295$ | `h1_cuts_m1p1`: $-0.0781$, $p = 0.9295$ | agrees |
| Abstract, Introduction | $[0,+5]$ pooled $-1.47\%$, $p = 0.022$ | `h1_pooled_0p5`: $-1.4740$, $p = 0.0222$ | agrees |
| Introduction, Discussion | H2 $-0.0208$, $p = 0.6368$ | `H2`: $-0.0208$, $p = 0.6368$ | agrees |
| Discussion, "Interpretation of Results" | SD of CARs "about 2.5\% to 3.0\%" | `sd_car`: 2.55 (pooled), 2.37 (hikes), 2.85 (cuts) | the range starts below 2.5; write "2.4\% to 2.9\%" or give the three values |

One wording change suggested (the last row, raised by the self-critique as a
minor finding). No number in the draft differs from its source.
