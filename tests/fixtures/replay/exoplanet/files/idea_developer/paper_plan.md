# Research plan: the radius–period distribution of a planet sample

**Question.** How are planet radii distributed in the sample, and how does radius vary with orbital period?

**Kind of study.** Descriptive. The study describes the sample (summary statistics, the radius distribution, the radius–period plane) and makes no causal claim. It does not estimate a regression.

**Data.** The researcher's file `data/exoplanets.csv`: one row per planet with orbital period (days), radius (Earth radii), discovery method and discovery year. The rows are synthetic test data, generated for e2er's tests; they describe no real planet.

**Results to report.**
1. Summary statistics of radius and period (n, mean, standard deviation, quartiles, range).
2. The radius distribution in bins (0.5 to 16 Earth radii), and the count between 1.5 and 2 Earth radii.
3. The discovery methods by count.
4. The rank correlation (Spearman) of radius and period, described as an association.
5. Two figures: radius against period on log axes, and the radius histogram.

**Limits to state.** A synthetic sample; detection methods favour some planets over others, so a sample's distribution is not the population's.
