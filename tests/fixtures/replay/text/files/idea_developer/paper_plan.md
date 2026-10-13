# Research plan: the vocabulary of fear in six works of short fiction, 1820-1892

**Question.** Do three works of 1820-1853 and three of 1886-1892 differ in how often they use the vocabulary of fear, and which words are key in the later works?

**Kind of study.** Text analysis, descriptive. The study counts words; it makes no claim about authors' intentions, readers or the literature of either period.

**Corpus.** Six works from Project Gutenberg, loaded with `e2er-data gutenberg text`: The Legend of Sleepy Hollow (1820), The Fall of the House of Usher (1839), Bartleby, the Scrivener (1853), The Strange Case of Dr. Jekyll and Mr. Hyde (1886), An Occurrence at Owl Creek Bridge (1890), The Yellow Wallpaper (1892).

**Results to report.**
1. Corpus statistics (documents, tokens, types, lengths).
2. Frequencies of fear words per 10,000 tokens, by period, with the number of works each occurs in.
3. Key terms of the later works (log-likelihood G2 with the log ratio), counting only words in at least two of the three later works.
4. A fear dictionary per period and per work, with the precision of a hand-checked sample of its hits.
5. An NMF topic model of 1,000-token segments, its stability across seeds, and topic shares by period.

**Limits to state.** Six hand-picked works; one work per year; the later period's counts lean on the longest work (Jekyll and Hyde).
