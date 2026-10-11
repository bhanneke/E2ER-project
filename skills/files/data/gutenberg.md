# Project Gutenberg via `e2er-data gutenberg`

Project Gutenberg offers about 75,000 books whose U.S. copyright has expired,
most in English, also French, German, Finnish, Dutch, Portuguese, Spanish and
others: novels, poetry, drama, essays, history, philosophy, early science.
e2er reads the catalogue through Gutendex (https://gutendex.com/, a JSON API
over Project Gutenberg's catalogue) and the plain texts from Project
Gutenberg's own mirror (gutenberg.pglaf.org). Project Gutenberg's website
itself allows no automated access, so e2er never reads from it. No key is
needed.

Use it for text-as-data: stylometry, word frequencies and sentiment over
time, topic models of a genre, readability, the vocabulary of an author or a
period. `books` gives the corpus's metadata (authors' years, subjects,
languages, downloads); `text` the texts themselves.

## Terms of use

- The books are not restricted by copyright in the United States; outside the
  U.S., check the copyright law of the researcher's country.
- Project Gutenberg's licence and trademark cover its edition, not the book
  text: "If you strip the Project Gutenberg license and all references to
  Project Gutenberg from the text, you are left with a text unrestricted by
  U.S. intellectual property law." e2er stores the book text only: it cuts
  Project Gutenberg's header and footer at the `*** START OF` / `*** END OF`
  lines and drops any other line naming Project Gutenberg; the load record
  says what was cut.
- Books still under copyright (a few on Project Gutenberg) are not loaded.
- Project Gutenberg asks automated users to take few books, from its mirrors:
  `text` loads at most 20 books at a time, two seconds apart, and keeps each
  file for the day.
- Full terms: https://www.gutenberg.org/policy/license.html

Cite each book in Project Gutenberg's format, e.g. "Austen, Jane. (n.d.).
Pride and Prejudice. Urbana, Illinois: Project Gutenberg. Retrieved October
11, 2026, from www.gutenberg.org/ebooks/1342." (each `text` load writes these
citations). The first load adds the BibTeX entry `ProjectGutenberg`.

## Subcommands

```
e2er-data gutenberg books --search "austen" --languages en --limit 50 --table austen_books
e2er-data gutenberg books --topic "detective" --author-year-start 1800 --author-year-end 1900 \
    --limit 200 --table detective_fiction
e2er-data gutenberg text --ids 1342,161,158 --table austen_texts
```

`books` options: `--search` (words of title or author), `--topic` (a word of
the subjects or bookshelves), `--languages` (two-letter codes, e.g. `en,fr`),
`--author-year-start` / `--author-year-end` (authors alive in that span),
`--ids`, `--sort` (`popular`, the default, or `ascending`/`descending` by
number), `--limit` (default 100, at most 320). One row per book: `id`,
`title`, `authors`, `author_birth_year`, `author_death_year`, `languages`,
`subjects`, `bookshelves`, `copyright`, `media_type`, `download_count`,
`has_plain_text`.

`text` options: `--ids` (required, at most 20). One row per book with the
catalogue fields and `text` (the book text without Project Gutenberg's
header, footer and licence), `characters` and `words`.

## Pitfalls

- A search returns several editions of one work (different ids, translations,
  illustrated editions); deduplicate by title and author before counting
  works.
- Publication years are not in the catalogue; the authors' birth and death
  years are. Do not treat the release on Project Gutenberg as the publication
  date.
- `download_count` is Project Gutenberg's recent download count: a popularity
  measure of today, not of the book's own time.
- Texts include front matter (title pages, tables of contents, transcriber's
  notes); remove it in the analysis where it matters.
- Project Gutenberg corrects books and rebuilds these files; the load records
  the SHA-256 of each file as downloaded.

## What a load records

Every load that returns rows is recorded in `data_sources.json`: the terms,
the citation, the request, the files read (mirror URL, SHA-256, size, time),
what was removed from each text (header and footer found, lines naming
Project Gutenberg dropped, characters removed), and when it ran. A table also
gets its entry in `data_dictionary.json`. An unknown id, a book under
copyright, a text without Project Gutenberg's START/END lines, or more than 20
books exit non-zero and leave data.db unchanged. Report the error; do not
build the table another way.
