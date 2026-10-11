"""The checks of a text analysis: the corpus design, the corpus as built, the results and their validation.

Counting words looks mechanical, and that is where text studies go wrong
without anyone noticing: a corpus whose documents nobody can trace, a token
count that depends on a tokeniser nobody wrote down, stop words removed in one
table and kept in the next, a dictionary adjusted after its results were seen,
a topic model that gives different topics with the next seed, a keyness score
typed in rather than computed, and a dictionary measure nobody read a single
hit of. Four checks hold a study of the ``text-analysis`` template
(``pipelines/text-analysis.toml``) to its corpus. The schema of every file is
in the skill ``methods/text-analysis``.

``corpus_design`` (inside the dispatch, after the data architect) reads
``corpus_design.json`` and fails when

  (a) the question, the corpus definition (what a document is, how documents
      were selected and sampled) or the statement of sampling bias is missing;
  (b) the corpus table is not named (table, id and text columns);
  (c) a metadata field (year, author, genre, ...) does not say where its
      values come from;
  (d) the preprocessing is incomplete or unusable: the token pattern must be a
      regular expression without capturing groups that matches no empty
      string; lower-casing true or false; stop words ``"none"`` or a word list
      in the study folder with its source; lemmatisation ``"none"`` or a
      word,lemma table in the study folder with its source; n-grams up to 3;
  (e) a group (e.g. a period) is not defined by a metadata column and value
      or by a list of documents;
  (f) an analysis lacks what makes it checkable: keyness its two groups,
      a dictionary or sentiment measure its word list (in the design, frozen
      before the analysis) and source, a topic model its algorithm (LDA or
      NMF), at least two candidate numbers of topics and at least
      ``min_seeds`` seeds.

``corpus`` (inside the dispatch, after the data analyst) reads the corpus
table in ``data.db`` and ``corpus_manifest.json`` and fails when

  (g) a document has no source or licence, ids repeat, or two documents have
      the same text (SHA-256);
  (h) a document's SHA-256 or token count in the manifest is not the one e2er
      computes from its text with the recorded preprocessing;
  (i) the corpus statistics (documents, tokens, types, the distribution of
      document lengths) are not the ones e2er computes;
  (j) a declared metadata field is not a column of the corpus table, or a
      document has no value for it without a stated reason.

It writes ``corpus_check.json`` (the recomputed statistics, a source of the
number check).

``text_results`` (inside the dispatch, after the analysis) reads
``estimation_results.json`` and the corpus, and fails when

  (k) the preprocessing the results state is not the design's, or the
      corpus figures differ from the corpus as built;
  (l) a term count, a group's token count or a frequency per 10,000 tokens
      differs from e2er's count; a term is not a possible token (upper case in
      a lower-cased study, longer n-grams than declared); a stop word appears
      in a term list of a study that removes them;
  (m) a keyness score (log-likelihood G2, Dunning 1993; Rayson and Garside
      2000), its effect size (log ratio, Hardie 2014) or its direction does
      not follow from the counts;
  (n) a collocation's count or PMI does not follow from the corpus;
  (o) a dictionary or sentiment measure uses a word list other than the
      design's, or its hits differ from e2er's count;
  (p) a topic model has no recorded seed, no evidence for its number of
      topics, fewer than ``min_seeds`` runs with different seeds, a stability
      figure that does not follow from those runs' top terms (mean best-match
      Jaccard overlap), a topic without top terms or without
      ``min_examples`` example documents of the corpus, or prevalence shares
      that do not add up to 1 in a group;
  (q) the results do not state the corpus's sampling bias;
  (v) a diachronic, keyness or topic model has no figure in
      ``figure_spec.json`` drawn from its results (frequency over time, key
      terms, topic shares).

It writes ``text_check.json``.

``text_validation`` (inside the dispatch, after the text validator) holds
every dictionary and sentiment measure to a hand-checked sample: the analysis
draws ``validation_sample.json`` with a recorded seed (document, term, the
passage around the hit), and the text validator judges every item in
``text_validation.json``. It fails when

  (r) a measure has no sample, the sample is smaller than
      ``min_validation_items`` (or than all hits, when there are fewer), or
      has no seed;
  (s) a quoted passage is not in the document's text, or does not contain the
      term it is quoted for;
  (t) an item of the sample is not judged, a judgement names an item that is
      not in the sample, or an item judged wrong carries no reason;
  (u) the precision the validation (or the results) states is not the share
      of items judged right.

It writes ``text_validation_check.json``. A study without a dictionary or
sentiment measure passes it with nothing to validate.

The preprocessing every check applies (and the analysis must apply the same
way): Unicode NFC, lower-casing when declared, the tokens are every match of
the token pattern, then each token is replaced by its lemma when a lemma table
is declared. Token counts and the denominators of frequencies count every
token; stop words only leave the term lists and the models.
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .checks_common import Verdict, close, lst, names, num, obj, plain_name, read_csv, read_json, write_json

DESIGN_FILE = "corpus_design.json"
MANIFEST_FILE = "corpus_manifest.json"
CORPUS_CHECK_FILE = "corpus_check.json"
RESULTS_FILE = "estimation_results.json"
RESULTS_CHECK_FILE = "text_check.json"
SAMPLE_FILE = "validation_sample.json"
VALIDATION_FILE = "text_validation.json"
VALIDATION_CHECK_FILE = "text_validation_check.json"

DEFAULTS: dict[str, float] = {"min_seeds": 3, "min_examples": 2, "min_validation_items": 20}

TOPIC_ALGORITHMS = ("lda", "nmf")
#: The analyses the template knows, by the `method` an analysis (and its model in the results) names.
METHODS = ("term_frequency", "keyness", "collocation", "dictionary", "sentiment", "topic_model", "diachronic")
_METHOD_ALIASES = {
    "termfrequency": "term_frequency",
    "termfrequencies": "term_frequency",
    "frequency": "term_frequency",
    "frequencies": "term_frequency",
    "keyness": "keyness",
    "loglikelihoodkeyness": "keyness",
    "keywords": "keyness",
    "collocation": "collocation",
    "collocations": "collocation",
    "dictionary": "dictionary",
    "dictionarybased": "dictionary",
    "dictionarymeasure": "dictionary",
    "sentiment": "sentiment",
    "sentimentlexicon": "sentiment",
    "lexiconsentiment": "sentiment",
    "topicmodel": "topic_model",
    "topics": "topic_model",
    "topicmodelling": "topic_model",
    "topicmodeling": "topic_model",
    "diachronic": "diachronic",
    "diachronicchange": "diachronic",
}
#: Tolerances: a statistic within 0.5% (or 0.01 absolute) of e2er's value is the same number.
_REL = 0.005
_ABS = 0.01


def method_name(value: Any) -> str | None:
    return _METHOD_ALIASES.get(re.sub(r"[^a-z]", "", str(value or "").lower()))


# ── preprocessing ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Preprocessing:
    """The recorded preprocessing, as e2er applies it."""

    token_pattern: str
    lowercase: bool
    stopwords: frozenset[str] = frozenset()
    lemmas: tuple[tuple[str, str], ...] = ()
    max_ngram: int = 1
    #: SHA-256 of the stop-word and lemma files, for the record.
    files: dict[str, str] = field(default_factory=dict, hash=False, compare=False)

    @property
    def pattern(self) -> re.Pattern[str]:
        return _compiled(self.token_pattern)

    def tokens(self, text: str) -> list[str]:
        t = unicodedata.normalize("NFC", text or "")
        if self.lowercase:
            t = t.lower()
        toks = self.pattern.findall(t)
        if self.lemmas:
            table = dict(self.lemmas)
            toks = [table.get(w, w) for w in toks]
        return toks

    def is_token(self, term: str) -> bool:
        """Whether every word of ``term`` (an n-gram: words separated by single spaces) is a possible token."""
        words = term.split(" ")
        if not words or len(words) > self.max_ngram:
            return False
        for w in words:
            if not w or self.pattern.fullmatch(w) is None:
                return False
            if self.lowercase and w != w.lower():
                return False
        return True


@lru_cache(maxsize=32)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _missing(ws: Path, rel: str) -> str:
    """Why a file the design names is not found, with the likely mix-up of folders spelled out."""
    near = [p.relative_to(ws).as_posix() for p in sorted(ws.glob(f"*/{Path(rel).name}")) if p.is_file()]
    hint = (
        f" (there is {', '.join(near)}: paths in corpus_design.json are relative to the study folder; name "
        "that path in the design or write the file where the design says)"
        if near
        else ""
    )
    return f"{rel} is missing{hint}"


def _word_file(ws: Path, rel: str) -> tuple[list[str] | None, str]:
    path = (ws / rel).resolve()
    if not path.is_relative_to(ws.resolve()):
        return None, f"{rel} lies outside the study folder"
    if not path.is_file():
        return None, _missing(ws, rel)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return None, f"{rel} cannot be read: {e}"
    return [w.strip() for w in lines if w.strip() and not w.strip().startswith("#")], ""


def _inside(ws: Path, rel: str) -> bool:
    return bool(rel) and not rel.startswith("/") and (ws / rel).resolve().is_relative_to(ws.resolve())


def parse_preprocessing(ws: Path, pre: Any, *, need_files: bool = True) -> tuple[Preprocessing | None, list[str]]:
    """The design's preprocessing, or the problems that make it unusable (rule d).

    ``need_files=False`` (the design check, before the corpus is built): the
    stop-word and lemma files may not exist yet; their names and sources are
    checked, and the result carries no word lists.
    """
    problems: list[str] = []
    if not isinstance(pre, dict):
        return None, ["(d) preprocessing must state token_pattern, lowercase, stopwords, lemmatisation and ngrams"]
    pattern = pre.get("token_pattern")
    compiled = None
    if not isinstance(pattern, str) or not pattern:
        problems.append("(d) preprocessing.token_pattern must be the regular expression that defines a token")
    else:
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            problems.append(f"(d) preprocessing.token_pattern is not a valid regular expression: {e}")
        else:
            if compiled.groups:
                problems.append(
                    "(d) preprocessing.token_pattern has capturing groups; write (?:...) so a match is the whole token"
                )
            if compiled.fullmatch(""):
                problems.append("(d) preprocessing.token_pattern matches the empty string")
    lowercase = pre.get("lowercase")
    if not isinstance(lowercase, bool):
        problems.append("(d) preprocessing.lowercase must be true or false")
    files: dict[str, str] = {}
    stop: set[str] = set()
    sw = pre.get("stopwords")
    if isinstance(sw, dict) and sw.get("file"):
        words, why = _word_file(ws, str(sw["file"]))
        if not need_files and _inside(ws, str(sw["file"])):
            pass
        elif words is None:
            problems.append(f"(d) preprocessing.stopwords: {why}")
        else:
            stop = {w.lower() if lowercase else w for w in words}
            files[str(sw["file"])] = _sha256_file(ws / str(sw["file"]))
        if not str(sw.get("source") or "").strip():
            problems.append("(d) preprocessing.stopwords needs its source (whose list, which version)")
    elif sw != "none":
        problems.append(
            '(d) preprocessing.stopwords must be "none" or {"file": "<word list in the study folder>", "source": ...}'
        )
    lemmas: list[tuple[str, str]] = []
    lem = pre.get("lemmatisation", pre.get("lemmatization"))
    if isinstance(lem, dict) and lem.get("file"):
        rel = str(lem["file"])
        rows, why = read_csv((ws / rel).resolve()) if _inside(ws, rel) else (None, "")
        if not need_files and _inside(ws, rel):
            pass
        elif rows is None:
            why = _missing(ws, rel) if _inside(ws, rel) and not (ws / rel).is_file() else why
            problems.append(f"(d) preprocessing.lemmatisation: {why or rel + ' lies outside the study folder'}")
        elif rows and not {"word", "lemma"} <= set(rows[0]):
            problems.append(f"(d) preprocessing.lemmatisation: {rel} needs the columns word and lemma")
        else:
            lemmas = [(r["word"], r["lemma"]) for r in rows if r.get("word") and r.get("lemma")]
            files[rel] = _sha256_file(ws / rel)
        if not str(lem.get("source") or "").strip():
            problems.append("(d) preprocessing.lemmatisation needs its source (the tool or list and its version)")
    elif lem != "none":
        problems.append(
            '(d) preprocessing.lemmatisation must be "none" or {"file": "<word,lemma table>", "source": ...}; '
            "e2er applies the table, so a lemmatiser's output is recorded as one"
        )
    ngrams = pre.get("ngrams", [1, 1])
    max_n = None
    if isinstance(ngrams, list) and len(ngrams) == 2 and all(isinstance(n, int) for n in ngrams):
        if ngrams[0] == 1 and 1 <= ngrams[1] <= 3:
            max_n = ngrams[1]
    if max_n is None:
        problems.append("(d) preprocessing.ngrams must be [1, n] with n from 1 to 3 (e.g. [1, 2] for words and pairs)")
    if problems or compiled is None or not isinstance(lowercase, bool) or max_n is None:
        return None, problems
    return (
        Preprocessing(
            token_pattern=str(pattern),
            lowercase=lowercase,
            stopwords=frozenset(stop),
            lemmas=tuple(lemmas),
            max_ngram=max_n,
            files=files,
        ),
        [],
    )


def _pre_key(pre: Any) -> dict[str, Any]:
    """The parts of a preprocessing record that must agree between the design and the results."""
    p = obj(pre)

    def part(v: Any) -> Any:
        return {"file": str(v.get("file"))} if isinstance(v, dict) else v

    return {
        "token_pattern": p.get("token_pattern"),
        "lowercase": p.get("lowercase"),
        "stopwords": part(p.get("stopwords")),
        "lemmatisation": part(p.get("lemmatisation", p.get("lemmatization"))),
        "ngrams": p.get("ngrams", [1, 1]),
    }


def referenced_files(design: dict[str, Any]) -> list[str]:
    """The study-folder files the design names: stop words, lemmas, dictionaries, lexicons."""
    out: list[str] = []
    pre = obj(design.get("preprocessing"))
    for key in ("stopwords", "lemmatisation", "lemmatization"):
        v = pre.get(key)
        if isinstance(v, dict) and v.get("file"):
            out.append(str(v["file"]))
    for a in lst(design.get("analyses")):
        for key in ("dictionary", "lexicon"):
            v = obj(obj(a).get(key))
            if v.get("file"):
                out.append(str(v["file"]))
    return sorted(set(out))


# ── the corpus ──────────────────────────────────────────────────────────────


@dataclass
class Document:
    doc_id: str
    text: str
    meta: dict[str, Any]
    tokens: list[str]


@dataclass
class Corpus:
    docs: dict[str, Document]
    pre: Preprocessing
    _counts: dict[tuple[str, int], Counter[str]] = field(default_factory=dict)

    def counts(self, doc_id: str, n: int = 1) -> Counter[str]:
        key = (doc_id, n)
        if key not in self._counts:
            toks = self.docs[doc_id].tokens
            if n == 1:
                self._counts[key] = Counter(toks)
            else:
                self._counts[key] = Counter(" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1))
        return self._counts[key]

    def count(self, term: str, doc_ids: list[str]) -> int:
        n = len(term.split(" "))
        return sum(self.counts(d, n)[term] for d in doc_ids)

    def spread(self, term: str, doc_ids: list[str]) -> int:
        """The number of documents the term occurs in (its dispersion)."""
        n = len(term.split(" "))
        return sum(1 for d in doc_ids if self.counts(d, n)[term] > 0)

    def n_tokens(self, doc_ids: list[str]) -> int:
        return sum(len(self.docs[d].tokens) for d in doc_ids)

    def hits(self, entries: list[str], doc_ids: list[str]) -> int:
        """Tokens matched by a word list (an entry ending in * matches every token it begins)."""
        exact = {e for e in entries if not e.endswith("*")}
        prefixes = tuple(e[:-1] for e in entries if e.endswith("*") and len(e) > 1)
        total = 0
        for d in doc_ids:
            for term, c in self.counts(d, 1).items():
                if term in exact or (prefixes and term.startswith(prefixes)):
                    total += c
        return total


def _corpus_spec(design: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    c = obj(design.get("corpus"))
    return plain_name(c.get("table")), plain_name(c.get("id_column")), plain_name(c.get("text_column"))


def load_corpus(ws: Path, design: dict[str, Any], pre: Preprocessing) -> tuple[Corpus | None, str]:
    """The corpus table of data.db, tokenised with the recorded preprocessing; (None, why) when unreadable."""
    from ...db.paper_data_db import data_db_path

    table, idc, textc = _corpus_spec(design)
    if not (table and idc and textc):
        return None, "corpus_design.json names no corpus table (corpus.table, id_column, text_column)"
    db = data_db_path(ws)
    if not db.is_file():
        return None, "there is no data.db with the corpus"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            con.row_factory = sqlite3.Row
            have = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
            if not have:
                return None, f"data.db has no table {table}"
            missing = [c for c in (idc, textc) if c not in have]
            if missing:
                return None, f"table {table} has no column {', '.join(missing)} (it has: {', '.join(have)})"
            rows = con.execute(f'SELECT * FROM "{table}"').fetchall()  # noqa: S608 — identifiers checked
        finally:
            con.close()
    except sqlite3.Error as e:
        return None, f"{table} cannot be read from data.db: {e}"
    docs: dict[str, Document] = {}
    for r in rows:
        d = dict(r)
        doc_id = str(d.pop(idc))
        text = d.pop(textc)
        text = text if isinstance(text, str) else ""
        docs.setdefault(doc_id, Document(doc_id, text, d, pre.tokens(text)))
    return Corpus(docs, pre), ""


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """The q-quantile by linear interpolation between order statistics (numpy's default)."""
    n = len(sorted_values)
    pos = (n - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def corpus_statistics(corpus: Corpus) -> dict[str, Any]:
    lengths = sorted(len(d.tokens) for d in corpus.docs.values())
    types: set[str] = set()
    for d in corpus.docs.values():
        types.update(d.tokens)
    n = len(lengths)
    return {
        "n_documents": n,
        "n_tokens": sum(lengths),
        "n_types": len(types),
        "length": {
            "min": lengths[0] if n else 0,
            "p25": round(quantile(lengths, 0.25), 2) if n else 0,
            "median": round(quantile(lengths, 0.5), 2) if n else 0,
            "p75": round(quantile(lengths, 0.75), 2) if n else 0,
            "max": lengths[-1] if n else 0,
            "mean": round(sum(lengths) / n, 2) if n else 0,
        },
    }


def group_documents(corpus: Corpus, design: dict[str, Any], group: str) -> tuple[list[str] | None, str]:
    """The documents of a group the design defines ("all": every document)."""
    if group == "all":
        return sorted(corpus.docs), ""
    spec = obj(obj(design.get("groups")).get(group))
    if not spec:
        return None, f"group {group!r} is not defined in corpus_design.json (groups)"
    if isinstance(spec.get("documents"), list):
        ids = [str(d) for d in spec["documents"]]
        unknown = [d for d in ids if d not in corpus.docs]
        if unknown:
            return None, f"group {group} names documents the corpus has not: {names(unknown)}"
        return sorted(ids), ""
    col = spec.get("column")
    if not col:
        return None, f"group {group} needs a metadata column and value, or a list of documents"
    values = spec.get("values", [spec.get("value")])
    wanted = {str(v) for v in values if v is not None}
    lo, hi = num(spec.get("from")), num(spec.get("to"))
    out = []
    for d in corpus.docs.values():
        if col not in d.meta:
            return None, f"group {group}: the corpus table has no column {col}"
        v = d.meta[col]
        if lo is not None or hi is not None:
            x = num(v) if not isinstance(v, str) else (float(v) if re.fullmatch(r"-?\d+(\.\d+)?", v) else None)
            if x is not None and (lo is None or x >= lo) and (hi is None or x <= hi):
                out.append(d.doc_id)
        elif v is not None and str(v) in wanted:
            out.append(d.doc_id)
    if not out:
        return None, f"group {group} ({col}) contains no document of the corpus"
    return sorted(out), ""


# ── statistics ──────────────────────────────────────────────────────────────


def log_likelihood(a: float, b: float, c: float, d: float) -> float:
    """Dunning's G2 for a term with a occurrences in c target tokens and b in d reference tokens
    (the two-cell form of Rayson and Garside 2000)."""
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    g = 0.0
    if a > 0:
        g += a * math.log(a / e1)
    if b > 0:
        g += b * math.log(b / e2)
    return 2 * g


def log_ratio(a: float, b: float, c: float, d: float) -> float:
    """Hardie's log ratio: log2 of the ratio of relative frequencies, a zero count taken as 0.5."""
    return math.log2(((a or 0.5) / c) / ((b or 0.5) / d))


def chi2_1_p(g2: float) -> float:
    """The p-value of G2 under a chi-squared distribution with one degree of freedom."""
    return math.erfc(math.sqrt(max(g2, 0.0) / 2))


def pmi(joint: float, c1: float, c2: float, n: float) -> float | None:
    if joint <= 0 or c1 <= 0 or c2 <= 0 or n <= 0:
        return None
    return math.log2(joint * n / (c1 * c2))


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


def topic_stability(runs: list[list[list[str]]]) -> float | None:
    """Mean best-match Jaccard overlap of the top terms between every pair of runs (symmetric).

    For runs i and j: the mean over i's topics of the best overlap with any of
    j's topics, and the same from j to i; their average is the pair's
    stability, and the figure is the mean over all pairs (Greene et al. 2014
    use the same idea with ranked lists).
    """
    if len(runs) < 2 or any(not r for r in runs):
        return None
    pairs = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            a, b = runs[i], runs[j]
            ab = sum(max(jaccard(t, u) for u in b) for t in a) / len(a)
            ba = sum(max(jaccard(u, t) for t in a) for u in b) / len(b)
            pairs.append((ab + ba) / 2)
    return sum(pairs) / len(pairs)


def _norm_ws(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").split())


# ── before the corpus is built ──────────────────────────────────────────────


def _analyses(design: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in lst(design.get("analyses")) if isinstance(a, dict)]


def _word_list(ws: Path, spec: Any, what: str, problems: list[str]) -> list[str] | None:
    """The entries of a dictionary or lexicon: inline ``terms`` or a ``file`` in the study folder."""
    s = obj(spec)
    if isinstance(s.get("terms"), list) and s["terms"]:
        return [str(t) for t in s["terms"] if str(t).strip()]
    if s.get("file"):
        rel = str(s["file"])
        if rel.endswith(".csv"):
            rows, why = read_csv(ws / rel)
            if rows is None:
                problems.append(f"{what}: {why}")
                return None
            if rows and "term" not in rows[0]:
                problems.append(f"{what}: {rel} needs a column term")
                return None
            return [r["term"] for r in rows if r.get("term")]
        words, why = _word_file(ws, rel)
        if words is None:
            problems.append(f"{what}: {why}")
        return words
    problems.append(f"{what} must list its entries (terms) or name its file in the study folder")
    return None


def _lexicon_categories(ws: Path, spec: Any) -> dict[str, list[str]]:
    """{category: entries} of a sentiment lexicon (inline ``categories`` or a term,category CSV)."""
    s = obj(spec)
    if isinstance(s.get("categories"), dict):
        return {str(k): [str(t) for t in lst(v)] for k, v in s["categories"].items()}
    if s.get("file") and str(s["file"]).endswith(".csv"):
        rows, _ = read_csv(ws / str(s["file"]))
        out: dict[str, list[str]] = {}
        for r in rows or []:
            if r.get("term") and r.get("category"):
                out.setdefault(r["category"], []).append(r["term"])
        return out
    return {}


def check_corpus_design(workspace: Path, *, min_seeds: int = int(DEFAULTS["min_seeds"])) -> Verdict:
    """Check ``corpus_design.json``: rules (a) to (f)."""
    ws = Path(workspace)
    design, err = read_json(ws / DESIGN_FILE)
    if err:
        return Verdict(False, (f"(a) {err}: the data architect declares the corpus and its preprocessing there",))
    if not isinstance(design, dict):
        return Verdict(False, (f"(a) {DESIGN_FILE} must be a JSON object",))
    reasons: list[str] = []
    stats: dict[str, Any] = {}

    # (a) question, corpus definition, sampling, bias
    if not str(design.get("question") or "").strip():
        reasons.append("(a) question must state the research question the corpus is built for")
    corpus = obj(design.get("corpus"))
    for key, what in (
        ("description", "what the corpus is and what one document is"),
        ("selection", "how documents were chosen (the rule, the catalogue query or the list)"),
        ("sampling", "the kind of sample (complete population, random with a seed, purposive, convenience)"),
    ):
        if not str(corpus.get(key) or "").strip():
            reasons.append(f"(a) corpus.{key} must state {what}")
    limits = obj(design.get("limits"))
    if not str(limits.get("sampling_bias") or "").strip():
        reasons.append(
            "(a) limits.sampling_bias must say whom and what the corpus over- and under-represents, so no claim "
            "goes beyond it (e.g. books that survived, were digitised and are out of copyright)"
        )

    # (b) where the corpus will be
    table, idc, textc = _corpus_spec(design)
    if not (table and idc and textc):
        reasons.append("(b) corpus.table, corpus.id_column and corpus.text_column must name the corpus in data.db")

    # (c) metadata with sources
    meta = obj(design.get("metadata"))
    for name, spec in meta.items():
        if not isinstance(spec, dict) or not str(spec.get("source") or "").strip():
            reasons.append(
                f"(c) metadata.{name} must say where its values come from (source), e.g. the catalogue, the "
                "title page, or a reference work"
            )
    stats["metadata"] = sorted(meta)

    # (d) preprocessing (the word lists may be written by the corpus build; the corpus check freezes them)
    pre, problems = parse_preprocessing(ws, design.get("preprocessing"), need_files=False)
    reasons += problems
    if pre is not None:
        stats["token_pattern"] = pre.token_pattern

    # (e) groups
    for g, spec in obj(design.get("groups")).items():
        s = obj(spec)
        if g == "all":
            reasons.append('(e) "all" is every document; give the group another name')
        elif not (
            isinstance(s.get("documents"), list)
            or (s.get("column") and (s.get("value") is not None or s.get("values") or "from" in s or "to" in s))
        ):
            reasons.append(f"(e) groups.{g} needs a metadata column with value(s) or from/to, or a list of documents")
        elif s.get("column") and str(s["column"]) not in meta and s["column"] != idc:
            reasons.append(f"(e) groups.{g} uses column {s['column']}, which metadata does not declare")

    # (f) analyses
    analyses = _analyses(design)
    if not analyses:
        reasons.append("(f) analyses must list the analyses the question needs (method and settings)")
    ids = [str(a.get("id") or "") for a in analyses]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        reasons.append("(f) every analysis needs its own id")
    groups = set(obj(design.get("groups"))) | {"all"}
    for a in analyses:
        aid = str(a.get("id") or "?")
        m = method_name(a.get("method"))
        if m is None:
            reasons.append(
                f"(f) analyses.{aid}: method {a.get('method')!r} is not one e2er checks: {', '.join(METHODS)}"
            )
            continue
        if m == "keyness":
            for side in ("target", "reference"):
                if str(a.get(side) or "") not in groups:
                    reasons.append(f"(f) analyses.{aid}: keyness needs {side}, a group of corpus_design.json")
            if a.get("target") and a.get("target") == a.get("reference"):
                reasons.append(f"(f) analyses.{aid}: target and reference are the same group")
        if m in ("dictionary", "sentiment"):
            key = "dictionary" if m == "dictionary" else "lexicon"
            spec = obj(a.get(key))
            if not spec:
                reasons.append(
                    f"(f) analyses.{aid}: a {m} measure needs its {key} in the design (frozen before the analysis)"
                )
            else:
                if spec.get("file") and not spec.get("terms") and not spec.get("categories"):
                    if not _inside(ws, str(spec["file"])):
                        reasons.append(f"(f) analyses.{aid}.{key}.file must be a file in the study folder")
                elif m == "dictionary":
                    _word_list(ws, spec, f"(f) analyses.{aid}.dictionary", reasons)
                elif not _lexicon_categories(ws, spec):
                    reasons.append(
                        f"(f) analyses.{aid}.lexicon must give its entries by category (categories, or a "
                        "term,category CSV in the study folder)"
                    )
                src = "source" if m == "dictionary" else "citation"
                if not str(spec.get(src) or spec.get("source") or "").strip():
                    reasons.append(f"(f) analyses.{aid}.{key} needs its {src} (who made it, where it is published)")
        if m == "topic_model":
            alg = str(a.get("algorithm") or "").lower()
            if alg not in TOPIC_ALGORITHMS:
                reasons.append(f"(f) analyses.{aid}: algorithm must be lda or nmf")
            ks = [k for k in lst(a.get("k_candidates")) if isinstance(k, int) and k >= 2]
            if len(set(ks)) < 2:
                reasons.append(f"(f) analyses.{aid}: k_candidates must list at least two numbers of topics (2 or more)")
            seeds = [s for s in lst(a.get("seeds")) if isinstance(s, int)]
            if len(set(seeds)) < min_seeds:
                reasons.append(f"(f) analyses.{aid}: seeds must list at least {min_seeds} different whole numbers")
        if m == "collocation" and not str(a.get("node") or a.get("measure") or "").strip():
            reasons.append(f"(f) analyses.{aid}: a collocation analysis needs its measure (pmi or log-likelihood)")
    stats["analyses"] = len(analyses)
    return Verdict(not reasons, tuple(reasons), (), stats)


# ── the corpus as built ─────────────────────────────────────────────────────


def changed_files(ws: Path, design: dict[str, Any]) -> list[str]:
    """Word lists the design names whose SHA-256 differs from the one the corpus check froze."""
    record, _ = read_json(ws / CORPUS_CHECK_FILE)
    frozen = obj(obj(record).get("files_sha256"))
    out = []
    for rel in referenced_files(design):
        want = frozen.get(rel)
        if want is None:
            continue
        if not (ws / rel).is_file() or _sha256_file(ws / rel) != want:
            out.append(rel)
    return out


def _load(ws: Path) -> tuple[dict[str, Any] | None, Preprocessing | None, Corpus | None, list[str]]:
    design, err = read_json(ws / DESIGN_FILE)
    if err or not isinstance(design, dict):
        return None, None, None, [f"{err or DESIGN_FILE + ' must be a JSON object'}"]
    pre, problems = parse_preprocessing(ws, design.get("preprocessing"))
    if pre is None:
        return design, None, None, problems
    corpus, why = load_corpus(ws, design, pre)
    if corpus is None:
        return design, pre, None, [why]
    return design, pre, corpus, []


def check_corpus(workspace: Path) -> Verdict:
    """Check the corpus table and ``corpus_manifest.json`` against the recorded preprocessing: rules (g) to (j)."""
    ws = Path(workspace)
    design, pre, corpus, problems = _load(ws)
    if corpus is None or pre is None or design is None:
        return Verdict(False, tuple(f"(h) {p}" for p in problems))
    reasons: list[str] = []
    notes: list[str] = []
    manifest, err = read_json(ws / MANIFEST_FILE)
    if err or not isinstance(manifest, dict):
        return Verdict(
            False,
            (
                f"(g) {err or MANIFEST_FILE + ' must be a JSON object'}: the corpus build writes one entry per "
                "document (doc_id, source, licence, sha256, n_tokens) and the corpus statistics",
            ),
        )
    entries = [e for e in lst(manifest.get("documents")) if isinstance(e, dict)]
    by_id: dict[str, dict[str, Any]] = {}
    dup_ids = []
    for e in entries:
        did = str(e.get("doc_id") or "")
        if did in by_id:
            dup_ids.append(did)
        by_id[did] = e
    if dup_ids:
        reasons.append(f"(g) document ids repeat in {MANIFEST_FILE}: {names(sorted(set(dup_ids)))}")
    not_listed = sorted(set(corpus.docs) - set(by_id))
    extra = sorted(set(by_id) - set(corpus.docs))
    if not_listed:
        reasons.append(f"(g) documents of the corpus table missing from {MANIFEST_FILE}: {names(not_listed)}")
    if extra:
        reasons.append(f"(g) {MANIFEST_FILE} lists documents the corpus table has not: {names(extra)}")
    no_source = sorted(d for d, e in by_id.items() if not str(e.get("source") or "").strip())
    no_licence = sorted(d for d, e in by_id.items() if not str(e.get("licence") or e.get("license") or "").strip())
    if no_source:
        reasons.append(f"(g) documents without a source (where the text comes from): {names(no_source)}")
    if no_licence:
        reasons.append(f"(g) documents without a licence (the terms the text is used under): {names(no_licence)}")

    hashes: dict[str, list[str]] = {}
    wrong_hash, wrong_tokens = [], []
    for did, doc in corpus.docs.items():
        sha = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
        hashes.setdefault(sha, []).append(did)
        entry = by_id.get(did)
        if entry is None:
            continue
        if str(entry.get("sha256") or "") != sha:
            wrong_hash.append(did)
        n = num(entry.get("n_tokens"))
        if n is None or int(n) != len(doc.tokens):
            wrong_tokens.append(f"{did} ({entry.get('n_tokens')} stated, {len(doc.tokens)} counted)")
    same = [ids for ids in hashes.values() if len(ids) > 1]
    if same:
        reasons.append("(g) documents with the same text: " + "; ".join(", ".join(sorted(s)) for s in same[:5]))
    if wrong_hash:
        reasons.append(
            f"(h) the SHA-256 in {MANIFEST_FILE} is not that of the text in the corpus table (UTF-8) for "
            f"{names(sorted(wrong_hash))}"
        )
    if wrong_tokens:
        reasons.append(
            f"(h) token counts differ from e2er's count with the recorded preprocessing: {names(wrong_tokens)}"
        )

    computed = corpus_statistics(corpus)
    stated = obj(manifest.get("corpus"))
    for key in ("n_documents", "n_tokens", "n_types"):
        v = num(stated.get(key))
        if v is None or int(v) != computed[key]:
            reasons.append(f"(i) corpus.{key}: {stated.get(key)} stated, {computed[key]} computed")
    length = obj(stated.get("length"))
    for key, want in computed["length"].items():
        v = num(length.get(key))
        if v is None or not close(v, float(want), rel=0.001, abs_=0.01):
            reasons.append(f"(i) corpus.length.{key}: {length.get(key)} stated, {want} computed")
            break
    planned = num(obj(design.get("corpus")).get("n_documents_planned"))
    if planned is not None and int(planned) != computed["n_documents"]:
        notes.append(f"the design planned {int(planned)} documents; the corpus has {computed['n_documents']}")

    # The word lists the design names exist now, and are frozen with their SHA-256.
    frozen: dict[str, str] = {}
    for rel in referenced_files(design):
        if not _inside(ws, rel) or not (ws / rel).is_file():
            reasons.append(
                f"(h) {rel}, which corpus_design.json names, is not in the study folder: {_missing(ws, rel)}"
            )
        else:
            frozen[rel] = _sha256_file(ws / rel)

    # (j) metadata
    meta = obj(design.get("metadata"))
    any_doc = next(iter(corpus.docs.values()), None)
    for name, spec in meta.items():
        if any_doc is not None and name not in any_doc.meta:
            reasons.append(f"(j) metadata.{name} is not a column of the corpus table")
            continue
        empty = sorted(d.doc_id for d in corpus.docs.values() if d.meta.get(name) in (None, ""))
        reason = str(obj(spec).get("missing") or "").strip()
        if empty and not reason:
            reasons.append(f"(j) documents without {name}: {names(empty)} (fill it, or say why it is missing)")
        elif empty:
            notes.append(f"{len(empty)} document(s) without {name}: {reason}")

    report = {
        "passed": not reasons,
        **computed,
        "preprocessing": {
            "token_pattern": pre.token_pattern,
            "lowercase": pre.lowercase,
            "stopwords": len(pre.stopwords),
            "lemmas": len(pre.lemmas),
            "ngrams": [1, pre.max_ngram],
        },
        "files_sha256": frozen,
        "documents": {
            did: {"n_tokens": len(d.tokens), "sha256": hashlib.sha256(d.text.encode("utf-8")).hexdigest()}
            for did, d in sorted(corpus.docs.items())
        },
        "reasons": reasons,
        "notes": notes,
    }
    write_json(ws / CORPUS_CHECK_FILE, report)
    stats = {k: computed[k] for k in ("n_documents", "n_tokens", "n_types")}
    return Verdict(not reasons, tuple(reasons), tuple(notes), stats)


# ── the results ─────────────────────────────────────────────────────────────


@dataclass
class _Ctx:
    ws: Path
    design: dict[str, Any]
    corpus: Corpus
    reasons: list[str]
    notes: list[str]
    stats: dict[str, Any]
    _groups: dict[str, tuple[list[str], int]] = field(default_factory=dict)

    def group(self, name: str, where: str) -> tuple[list[str], int] | None:
        if name not in self._groups:
            ids, why = group_documents(self.corpus, self.design, name)
            if ids is None:
                self.reasons.append(f"{where}: {why}")
                return None
            self._groups[name] = (ids, self.corpus.n_tokens(ids))
        return self._groups[name]

    def term_ok(self, term: str, where: str, *, stop_listed: bool = True) -> bool:
        pre = self.corpus.pre
        if not pre.is_token(term):
            why = (
                f"has more than {pre.max_ngram} word(s)"
                if len(term.split(" ")) > pre.max_ngram
                else "is not a token of the recorded preprocessing (token pattern, lower-casing)"
            )
            self.reasons.append(f"(l) {where}: {term!r} {why}")
            return False
        if stop_listed and pre.stopwords and any(w in pre.stopwords for w in term.split(" ")):
            self.reasons.append(f"(l) {where}: {term!r} is a stop word, which the recorded preprocessing removes")
            return False
        return True


def _check_frequencies(ctx: _Ctx, results: dict[str, Any]) -> None:
    for group, entry in obj(results.get("term_frequencies")).items():
        if not isinstance(entry, dict):
            continue
        g = ctx.group(group, f"(l) term_frequencies.{group}")
        if g is None:
            continue
        ids, n_tok = g
        stated = num(entry.get("n_tokens"))
        if stated is not None and int(stated) != n_tok:
            ctx.reasons.append(f"(l) term_frequencies.{group}.n_tokens: {int(stated)} stated, {n_tok} counted")
        bad = []
        for t in lst(entry.get("terms")):
            term = str(obj(t).get("term") or "")
            if not term or not ctx.term_ok(term, f"term_frequencies.{group}", stop_listed=False):
                continue
            got = ctx.corpus.count(term, ids)
            c = num(obj(t).get("count"))
            if c is None or int(c) != got:
                bad.append(f"{term} ({obj(t).get('count')} stated, {got} counted)")
            per = num(obj(t).get("per_10k"))
            if per is not None and n_tok and not close(per, got / n_tok * 10_000, rel=_REL, abs_=0.006):
                bad.append(f"{term} per_10k ({per} stated, {got / n_tok * 10_000:.4f} computed)")
            spread = num(obj(t).get("documents"))
            if spread is not None and int(spread) != ctx.corpus.spread(term, ids):
                bad.append(f"{term} in {int(spread)} documents stated, {ctx.corpus.spread(term, ids)} counted")
        if bad:
            ctx.reasons.append(f"(l) term_frequencies.{group}: counts differ from e2er's count: {names(bad)}")
        else:
            ctx.stats[f"terms_{group}"] = len(lst(entry.get("terms")))


def _check_keyness(ctx: _Ctx, key: str, m: dict[str, Any], analysis: dict[str, Any]) -> None:
    target, reference = str(m.get("target") or ""), str(m.get("reference") or "")
    if analysis and (target, reference) != (str(analysis.get("target")), str(analysis.get("reference"))):
        ctx.reasons.append(
            f"(m) models.{key}: target/reference {target}/{reference} are not the design's "
            f"{analysis.get('target')}/{analysis.get('reference')}"
        )
    gt, gr = ctx.group(target, f"(m) models.{key}.target"), ctx.group(reference, f"(m) models.{key}.reference")
    if gt is None or gr is None:
        return
    (tid, c), (rid, d) = gt, gr
    terms = [t for t in lst(obj(m.get("outputs")).get("terms")) if isinstance(t, dict)]
    if not terms:
        ctx.reasons.append(f"(m) models.{key}.outputs.terms must list the key terms with their counts and G2")
        return
    bad = []
    for t in terms:
        term = str(t.get("term") or "")
        if not term or not ctx.term_ok(term, f"models.{key}"):
            continue
        a, b = ctx.corpus.count(term, tid), ctx.corpus.count(term, rid)
        sa, sb = num(t.get("count_target")), num(t.get("count_reference"))
        if sa is None or sb is None or int(sa) != a or int(sb) != b:
            bad.append(f"{term}: counts {t.get('count_target')}/{t.get('count_reference')} stated, {a}/{b} counted")
            continue
        g2 = log_likelihood(a, b, c, d)
        sg = num(t.get("g2"))
        if sg is None or not close(sg, g2, rel=_REL, abs_=_ABS):
            bad.append(f"{term}: G2 {t.get('g2')} stated, {g2:.3f} computed")
        lr = num(t.get("log_ratio"))
        if lr is not None and not close(lr, log_ratio(a, b, c, d), rel=_REL, abs_=_ABS):
            bad.append(f"{term}: log ratio {lr} stated, {log_ratio(a, b, c, d):.3f} computed")
        p = num(t.get("p_value"))
        if p is not None and not close(p, chi2_1_p(g2), rel=0.01, abs_=1e-6):
            bad.append(f"{term}: p {p} stated, {chi2_1_p(g2):.3g} computed (chi-squared, 1 df)")
        spread = num(t.get("documents_target"))
        if spread is not None and int(spread) != ctx.corpus.spread(term, tid):
            bad.append(f"{term}: in {int(spread)} target documents stated, {ctx.corpus.spread(term, tid)} counted")
        more = str(t.get("more_in") or "")
        want = target if a / c > b / d else reference
        if more and more != want:
            bad.append(f"{term}: more_in {more}, but its relative frequency is higher in {want}")
    if bad:
        ctx.reasons.append(f"(m) models.{key}: {names(bad)}")
    elif not any(num(t.get("log_ratio")) is not None for t in terms):
        ctx.reasons.append(f"(m) models.{key}: report an effect size with G2 (log_ratio, Hardie 2014)")
    else:
        ctx.stats[key] = len(terms)


def _check_collocations(ctx: _Ctx, key: str, m: dict[str, Any]) -> None:
    group = str(m.get("group") or "all")
    g = ctx.group(group, f"(n) models.{key}")
    if g is None:
        return
    ids, n_tok = g
    window = num(m.get("window"))
    pairs = [p for p in lst(obj(m.get("outputs")).get("pairs")) if isinstance(p, dict)]
    if not pairs:
        ctx.reasons.append(f"(n) models.{key}.outputs.pairs must list the word pairs with their counts")
        return
    if window not in (None, 1):
        ctx.notes.append(f"models.{key}: window {window}; only adjacent pairs (window 1) are recounted")
        return
    bad = []
    for p in pairs:
        w1, w2 = str(p.get("w1") or ""), str(p.get("w2") or "")
        if not (w1 and w2):
            bad.append(f"{p}: needs w1 and w2")
            continue
        joint = sum(ctx.corpus.counts(d, 2)[f"{w1} {w2}"] for d in ids)
        c = num(p.get("count"))
        if c is None or int(c) != joint:
            bad.append(f"{w1} {w2}: count {p.get('count')} stated, {joint} counted")
            continue
        sp = num(p.get("pmi"))
        if sp is not None:
            want = pmi(joint, ctx.corpus.count(w1, ids), ctx.corpus.count(w2, ids), n_tok)
            if want is None or not close(sp, want, rel=_REL, abs_=_ABS):
                bad.append(f"{w1} {w2}: PMI {sp} stated, {want if want is None else round(want, 3)} computed")
    if bad:
        ctx.reasons.append(f"(n) models.{key}: {names(bad)}")


def _same_entries(a: list[str] | None, b: list[str] | None) -> bool:
    return a is not None and b is not None and sorted(set(a)) == sorted(set(b))


def _check_dictionary(ctx: _Ctx, key: str, m: dict[str, Any], analysis: dict[str, Any], method: str) -> None:
    spec_key = "dictionary" if method == "dictionary" else "lexicon"
    design_spec = obj(analysis.get(spec_key))
    result_spec = obj(m.get(spec_key)) or design_spec
    scratch: list[str] = []
    if method == "dictionary":
        design_terms = _word_list(ctx.ws, design_spec, "", scratch)
        result_terms = _word_list(ctx.ws, result_spec, "", scratch)
        if not _same_entries(design_terms, result_terms):
            ctx.reasons.append(
                f"(o) models.{key}: the dictionary is not the one corpus_design.json froze before the analysis"
            )
            return
        cats = {"hits": design_terms or []}
    else:
        cats = _lexicon_categories(ctx.ws, design_spec)
        if cats != _lexicon_categories(ctx.ws, result_spec):
            ctx.reasons.append(f"(o) models.{key}: the lexicon is not the one corpus_design.json froze")
            return
    rows = [r for r in lst(obj(m.get("outputs")).get("by_group")) if isinstance(r, dict)]
    if not rows:
        ctx.reasons.append(f"(o) models.{key}.outputs.by_group must give the hits per group (group, hits, n_tokens)")
        return
    bad = []
    for r in rows:
        group = str(r.get("group") or "")
        g = ctx.group(group, f"(o) models.{key}.by_group")
        if g is None:
            continue
        ids, n_tok = g
        category = str(r.get("category") or "hits")
        entries = cats.get(category)
        if entries is None:
            bad.append(f"{group}: category {category} is not in the lexicon ({', '.join(cats)})")
            continue
        got = ctx.corpus.hits(entries, ids)
        h = num(r.get("hits"))
        if h is None or int(h) != got:
            bad.append(f"{group}/{category}: {r.get('hits')} hits stated, {got} counted")
        nt = num(r.get("n_tokens"))
        if nt is not None and int(nt) != n_tok:
            bad.append(f"{group}: n_tokens {int(nt)} stated, {n_tok} counted")
        per = num(r.get("per_10k"))
        if per is not None and n_tok and not close(per, got / n_tok * 10_000, rel=_REL, abs_=0.006):
            bad.append(f"{group}/{category}: per_10k {per} stated, {got / n_tok * 10_000:.4f} computed")
    if bad:
        ctx.reasons.append(
            f"(o) models.{key}: {names(bad)} (e2er counts tokens equal to an entry, or beginning with an entry "
            "that ends in *: 'felt' matches felt only, 'feel*' feel, feels, feeling)"
        )


def _check_topics(
    ctx: _Ctx, key: str, m: dict[str, Any], analysis: dict[str, Any], min_seeds: int, min_examples: int
) -> None:
    alg = str(m.get("algorithm") or "").lower()
    if alg not in TOPIC_ALGORITHMS:
        ctx.reasons.append(f"(p) models.{key}.algorithm must be lda or nmf")
    seed = m.get("seed")
    if not isinstance(seed, int):
        ctx.reasons.append(f"(p) models.{key}.seed must record the seed of the reported model")
    k = m.get("k")
    sel = [s for s in lst(m.get("k_selection")) if isinstance(s, dict)]
    ks: set[int] = {int(s["k"]) for s in sel if isinstance(s.get("k"), int) and num(s.get("value")) is not None}
    if len(ks) < 2 or k not in ks or not all(str(s.get("metric") or "").strip() for s in sel):
        ctx.reasons.append(
            f"(p) models.{key}.k_selection must give a metric and its value for at least two numbers of topics, "
            "the chosen k among them"
        )
    planned = {x for x in lst(analysis.get("k_candidates")) if isinstance(x, int)}
    if planned and ks and not ks <= planned:
        ctx.reasons.append(f"(p) models.{key}: k_selection tries {sorted(ks)}, the design planned {sorted(planned)}")
    stab = obj(m.get("stability"))
    runs = [r for r in lst(stab.get("runs")) if isinstance(r, dict)]
    seeds = [r.get("seed") for r in runs]
    if len(set(s for s in seeds if isinstance(s, int))) < min_seeds:
        ctx.reasons.append(
            f"(p) models.{key}.stability.runs must give the top terms of the chosen model under at least {min_seeds} "
            "different seeds"
        )
    else:
        planned_seeds = {x for x in lst(analysis.get("seeds")) if isinstance(x, int)}
        if planned_seeds and not set(seeds) <= planned_seeds:
            ctx.reasons.append(f"(p) models.{key}: runs use seeds {seeds}, the design planned {sorted(planned_seeds)}")
        topic_lists = [[[str(w) for w in lst(t)] for t in lst(r.get("topics"))] for r in runs]
        if any(len(t) != k for t in topic_lists):
            ctx.reasons.append(f"(p) models.{key}.stability.runs: every run must list k = {k} topics of top terms")
        else:
            got = topic_stability(topic_lists)
            stated = num(stab.get("mean_best_match_jaccard"))
            if got is None or stated is None or not close(stated, got, rel=0.001, abs_=0.001):
                ctx.reasons.append(
                    f"(p) models.{key}.stability.mean_best_match_jaccard: {stab.get('mean_best_match_jaccard')} "
                    f"stated, {got if got is None else round(got, 4)} computed from the runs' top terms"
                )
            else:
                ctx.stats[f"{key}_stability"] = round(got, 3)
                init = str(m.get("init") or "").lower()
                if got >= 0.999 and (alg == "nmf" and (not init or init.startswith("nndsvd"))):
                    ctx.notes.append(
                        f"models.{key}: every seed gives the same top terms; NMF started from nndsvd or nndsvda "
                        "ignores the seed, so this shows the fit is deterministic, not that the topics are stable "
                        '(record "init" and use init="random" to test the seeds)'
                    )
                if got < 0.5:
                    ctx.notes.append(
                        f"models.{key}: the topics change much between seeds (stability {got:.2f}); report them "
                        "as unstable"
                    )
    outputs = obj(m.get("outputs"))
    topics = [t for t in lst(outputs.get("topics")) if isinstance(t, dict)]
    if isinstance(k, int) and len(topics) != k:
        ctx.reasons.append(f"(p) models.{key}.outputs.topics lists {len(topics)} topics, k is {k}")
    main_run = next((r for r in runs if r.get("seed") == seed), None)
    seg = num(m.get("segment_tokens"))
    for t in topics:
        tid = t.get("id")
        terms = [str(w) for w in lst(t.get("top_terms"))]
        if len(terms) < 5:
            ctx.reasons.append(f"(p) models.{key}: topic {tid} needs at least 5 top terms")
        for w in terms:
            ctx.term_ok(w, f"models.{key} topic {tid}")
        ex = [e for e in lst(t.get("example_documents")) if isinstance(e, dict)]
        if len(ex) < min_examples:
            ctx.reasons.append(f"(p) models.{key}: topic {tid} needs at least {min_examples} example documents")
        for e in ex:
            did = str(e.get("doc_id") or "")
            if did not in ctx.corpus.docs:
                ctx.reasons.append(f"(p) models.{key}: topic {tid} names example document {did!r}, not in the corpus")
                continue
            s = e.get("segment")
            if s is not None and seg:
                n_seg = math.ceil(len(ctx.corpus.docs[did].tokens) / seg)
                if not isinstance(s, int) or not 0 <= s < n_seg:
                    ctx.reasons.append(
                        f"(p) models.{key}: topic {tid} names segment {s} of {did}, which has {n_seg} segments "
                        f"of {int(seg)} tokens"
                    )
    if main_run is not None and topics:
        main_terms = [[str(w) for w in lst(t)] for t in lst(main_run.get("topics"))]
        reported = [
            [str(w) for w in lst(t.get("top_terms"))][: len(main_terms[0]) if main_terms else 0] for t in topics
        ]
        if sorted(map(tuple, reported)) != sorted(map(tuple, main_terms)):
            ctx.reasons.append(
                f"(p) models.{key}: the topics' top terms are not those of the stability run with the model's seed"
            )
    shares: dict[str, float] = {}
    for p in lst(outputs.get("prevalence")):
        if isinstance(p, dict) and num(p.get("share")) is not None:
            shares[str(p.get("group") or "all")] = shares.get(str(p.get("group") or "all"), 0.0) + float(p["share"])
    for g, total in shares.items():
        if abs(total - 1) > 0.01:
            ctx.reasons.append(f"(p) models.{key}.outputs.prevalence: the shares of group {g} add up to {total:.3f}")


def _check_diachronic(ctx: _Ctx, key: str, m: dict[str, Any]) -> None:
    bad = []
    for r in lst(obj(m.get("outputs")).get("series")):
        if not isinstance(r, dict):
            continue
        group, term = str(r.get("group") or ""), str(r.get("term") or "")
        g = ctx.group(group, f"(l) models.{key}.series")
        if g is None or not term or not ctx.term_ok(term, f"models.{key}", stop_listed=False):
            continue
        ids, n_tok = g
        got = ctx.corpus.count(term, ids)
        c = num(r.get("count"))
        if c is None or int(c) != got:
            bad.append(f"{group}/{term}: {r.get('count')} stated, {got} counted")
        per = num(r.get("per_10k"))
        if per is not None and n_tok and not close(per, got / n_tok * 10_000, rel=_REL, abs_=0.006):
            bad.append(f"{group}/{term}: per_10k {per} stated, {got / n_tok * 10_000:.4f} computed")
    if bad:
        ctx.reasons.append(f"(l) models.{key}: {names(bad)}")


#: The methods whose results the paper shows as a figure (frequency over time, key terms, topic shares).
FIGURE_METHODS = {"diachronic": "frequency over time", "keyness": "key terms", "topic_model": "topic shares"}


def _figure_sources(spec: Any) -> list[str]:
    """The results paths every figure part of figure_spec.json reads (series, panels, the figure itself)."""
    out: list[str] = []

    def walk(part: Any) -> None:
        if not isinstance(part, dict):
            return
        src = obj(part.get("source"))
        if src.get("results") and str(src.get("file") or RESULTS_FILE) == RESULTS_FILE:
            out.append(str(src["results"]))
        for key in ("series", "panels"):
            for sub in lst(part.get(key)):
                walk(sub)

    for fig in lst(obj(spec).get("figures")):
        walk(fig)
    return out


def _check_figures(ctx: _Ctx, results: dict[str, Any]) -> None:
    """(v) A figure drawn from the results of every diachronic, keyness and topic model."""
    spec, _ = read_json(ctx.ws / "figure_spec.json")
    sources = _figure_sources(spec)
    for key, m in obj(results.get("models")).items():
        method = method_name(obj(m).get("method"))
        if method not in FIGURE_METHODS:
            continue
        if not any(src == f"models.{key}" or src.startswith(f"models.{key}.") for src in sources):
            ctx.reasons.append(
                f"(v) no figure shows models.{key} ({FIGURE_METHODS[method]}): add one to figure_spec.json with "
                f'"source": {{"results": "models.{key}.outputs...", "fields": {{...}}}}, and name it in '
                "the results' 'figures'"
            )


def check_text_results(
    workspace: Path,
    *,
    min_seeds: int = int(DEFAULTS["min_seeds"]),
    min_examples: int = int(DEFAULTS["min_examples"]),
) -> Verdict:
    """Check the results against the corpus and the design: rules (k) to (q)."""
    ws = Path(workspace)
    results, err = read_json(ws / RESULTS_FILE)
    if err or not isinstance(results, dict) or not results:
        return Verdict(False, (f"(k) {err or RESULTS_FILE + ' is empty'}",))
    design, pre, corpus, problems = _load(ws)
    if corpus is None or pre is None or design is None:
        return Verdict(False, tuple(f"(k) {p}" for p in problems))
    ctx = _Ctx(ws, design, corpus, [], [], {})
    changed = changed_files(ws, design)
    if changed:
        ctx.reasons.append(
            f"(k) {', '.join(changed)} changed after the corpus check froze it: word lists are fixed before the "
            "analysis"
        )

    # (k) preprocessing and corpus
    stated_pre = obj(results.get("corpus")).get("preprocessing", results.get("preprocessing"))
    if _pre_key(stated_pre) != _pre_key(design.get("preprocessing")):
        ctx.reasons.append(
            "(k) the preprocessing the results state (corpus.preprocessing) is not the design's: "
            f"{_pre_key(stated_pre)} vs {_pre_key(design.get('preprocessing'))}"
        )
    computed = corpus_statistics(corpus)
    stated = obj(results.get("corpus"))
    for k in ("n_documents", "n_tokens", "n_types"):
        v = num(stated.get(k))
        if v is None or int(v) != computed[k]:
            ctx.reasons.append(f"(k) corpus.{k}: {stated.get(k)} in the results, {computed[k]} in the corpus")

    # (l) term frequencies
    _check_frequencies(ctx, results)

    # (m) to (p) the models
    analyses = {str(a.get("id")): a for a in _analyses(design)}
    for key, m in obj(results.get("models")).items():
        if not isinstance(m, dict):
            continue
        method = method_name(m.get("method"))
        analysis = obj(analyses.get(str(m.get("analysis") or key)))
        if method is None:
            ctx.notes.append(f"models.{key}: method {m.get('method')!r} is not one e2er recomputes")
            continue
        if method == "keyness":
            _check_keyness(ctx, key, m, analysis)
        elif method == "collocation":
            _check_collocations(ctx, key, m)
        elif method in ("dictionary", "sentiment"):
            if not analysis:
                ctx.reasons.append(
                    f"(o) models.{key}: no analysis of corpus_design.json declares this {method} measure "
                    "(name it in 'analysis')"
                )
            else:
                _check_dictionary(ctx, key, m, analysis, method)
        elif method == "topic_model":
            _check_topics(ctx, key, m, analysis, min_seeds, min_examples)
        elif method == "diachronic":
            _check_diachronic(ctx, key, m)
    declared = {method_name(a.get("method")) for a in analyses.values()} - {None, "term_frequency"}
    done = {method_name(obj(m).get("method")) for m in obj(results.get("models")).values()}
    missing = sorted(str(x) for x in declared - done)
    if missing:
        ctx.reasons.append(f"(f) the design declares {', '.join(missing)}, which the results do not report")

    # (v) the figures the template asks for, drawn from the results
    _check_figures(ctx, results)

    # (q) limits
    if not str(obj(results.get("limits")).get("sampling_bias") or "").strip():
        ctx.reasons.append("(q) limits.sampling_bias must say what the corpus does not represent")

    ctx.stats.update({k: computed[k] for k in ("n_documents", "n_tokens")})
    write_json(
        ws / RESULTS_CHECK_FILE,
        {"passed": not ctx.reasons, "reasons": ctx.reasons, "notes": ctx.notes, "stats": ctx.stats},
    )
    return Verdict(not ctx.reasons, tuple(ctx.reasons), tuple(ctx.notes), ctx.stats)


# ── the validation of dictionary and sentiment measures ────────────────────


def _measures(results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        k: m
        for k, m in obj(results.get("models")).items()
        if isinstance(m, dict) and method_name(m.get("method")) in ("dictionary", "sentiment")
    }


def check_text_validation(
    workspace: Path, *, min_validation_items: int = int(DEFAULTS["min_validation_items"])
) -> Verdict:
    """Check the hand-checked samples of every dictionary and sentiment measure: rules (r) to (u)."""
    ws = Path(workspace)
    results, err = read_json(ws / RESULTS_FILE)
    if err or not isinstance(results, dict):
        return Verdict(False, (f"(r) {err or RESULTS_FILE + ' must be a JSON object'}",))
    measures = _measures(results)
    if not measures:
        write_json(ws / VALIDATION_CHECK_FILE, {"passed": True, "measures": {}, "notes": ["nothing to validate"]})
        return Verdict(True, (), ("no dictionary or sentiment measure: nothing to validate",), {"measures": 0})
    design, pre, corpus, problems = _load(ws)
    if corpus is None or pre is None or design is None:
        return Verdict(False, tuple(f"(r) {p}" for p in problems))
    changed = changed_files(ws, design)
    if changed:
        return Verdict(False, (f"(r) {', '.join(changed)} changed after the corpus check froze it",))
    sample, err = read_json(ws / SAMPLE_FILE)
    sample = sample if isinstance(sample, dict) else {}
    judged, jerr = read_json(ws / VALIDATION_FILE)
    judged = judged if isinstance(judged, dict) else {}
    reasons: list[str] = []
    notes: list[str] = []
    report: dict[str, Any] = {}
    analyses = {str(a.get("id")): a for a in _analyses(design)}
    for key, m in measures.items():
        s = obj(sample.get(key))
        items = [i for i in lst(s.get("items")) if isinstance(i, dict)]
        if not items:
            reasons.append(
                f"(r) {SAMPLE_FILE} has no sample for {key}"
                + (f" ({err})" if err else "")
                + ": the analysis draws one with a recorded seed (doc_id, term, quote)"
            )
            continue
        if not isinstance(s.get("seed"), int):
            reasons.append(f"(r) {SAMPLE_FILE}.{key}.seed must record the seed the sample was drawn with")
        total = num(s.get("n_hits_total"))
        need = min(min_validation_items, int(total)) if total is not None else min_validation_items
        if len(items) < need:
            reasons.append(f"(r) the sample of {key} has {len(items)} items; it needs at least {need}")
        method = method_name(m.get("method")) or "dictionary"
        a = obj(analyses.get(str(m.get("analysis") or key)))
        if method == "dictionary":
            scratch: list[str] = []
            entries = _word_list(ws, obj(a.get("dictionary")), "", scratch) or []
        else:
            entries = [e for v in _lexicon_categories(ws, obj(a.get("lexicon"))).values() for e in v]
        exact = {e for e in entries if not e.endswith("*")}
        prefixes = tuple(e[:-1] for e in entries if e.endswith("*") and len(e) > 1)
        not_found, no_term = [], []
        for i, it in enumerate(items):
            did, quote, term = str(it.get("doc_id") or ""), str(it.get("quote") or ""), str(it.get("term") or "")
            doc = corpus.docs.get(did)
            if doc is None or not quote or _norm_ws(quote) not in _norm_ws(doc.text):
                not_found.append(f"item {i} ({did})")
                continue
            toks = pre.tokens(quote)
            if term not in toks or not (term in exact or (prefixes and term.startswith(prefixes))):
                no_term.append(f"item {i} ({term!r})")
        if not_found:
            reasons.append(f"(s) {key}: passages not found verbatim in their document: {names(not_found)}")
        if no_term:
            reasons.append(f"(s) {key}: passages without a hit of the measure's word list: {names(no_term)}")

        v = obj(judged.get(key))
        jitems = [j for j in lst(v.get("items")) if isinstance(j, dict)]
        if not jitems:
            reasons.append(
                f"(t) {VALIDATION_FILE} has no judgements for {key}"
                + (f" ({jerr})" if jerr else "")
                + ": the text validator judges every item of the sample"
            )
            continue
        sample_keys = {(str(i.get("doc_id")), _norm_ws(str(i.get("quote") or ""))) for i in items}
        judged_keys: dict[tuple[str, str], dict[str, Any]] = {}
        strangers = []
        for j in jitems:
            k2 = (str(j.get("doc_id")), _norm_ws(str(j.get("quote") or "")))
            if k2 not in sample_keys:
                strangers.append(str(j.get("doc_id")))
            judged_keys[k2] = j
        unjudged = [k2[0] for k2 in sample_keys if k2 not in judged_keys]
        if strangers:
            reasons.append(f"(t) {key}: judgements of passages that are not in the sample: {names(strangers)}")
        if unjudged:
            reasons.append(f"(t) {key}: {len(unjudged)} item(s) of the sample are not judged")
        verdicts = [
            j.get("correct")
            for j in judged_keys.values()
            if (j.get("doc_id"), _norm_ws(str(j.get("quote") or ""))) in sample_keys
        ]
        if any(not isinstance(x, bool) for x in verdicts):
            reasons.append(f"(t) {key}: every judgement needs correct: true or false")
            continue
        no_reason = [
            str(j.get("doc_id"))
            for j in judged_keys.values()
            if j.get("correct") is False and not str(j.get("reason") or "").strip()
        ]
        if no_reason:
            reasons.append(f"(t) {key}: items judged wrong need a reason: {names(no_reason)}")
        n = len(verdicts)
        right = sum(1 for x in verdicts if x)
        precision = right / n if n else None
        for where, stated in (
            (f"{VALIDATION_FILE}.{key}.precision", num(v.get("precision"))),
            (f"models.{key}.validation.precision", num(obj(m.get("validation")).get("precision"))),
        ):
            if stated is not None and precision is not None and not close(stated, precision, rel=0.001, abs_=0.001):
                reasons.append(f"(u) {where}: {stated} stated; {right} of {n} judged right is {precision:.4f}")
        if num(v.get("precision")) is None:
            reasons.append(f"(u) {VALIDATION_FILE}.{key}.precision must state the share judged right")
        report[key] = {
            "n_items": n,
            "n_correct": right,
            "precision": round(precision, 4) if precision is not None else None,
        }
        if precision is not None and precision < 0.7:
            notes.append(f"{key}: precision {precision:.2f}; most hits may not mean what the measure assumes")
    write_json(
        ws / VALIDATION_CHECK_FILE, {"passed": not reasons, "measures": report, "reasons": reasons, "notes": notes}
    )
    stats = {f"{k}_precision": r["precision"] for k, r in report.items()}
    return Verdict(not reasons, tuple(reasons), tuple(notes), stats)
