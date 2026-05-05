# Contributing Skill Files

Skill files are plain markdown documents injected into specialist system prompts at runtime. They are the primary mechanism for adding domain expertise to the pipeline — no code changes required.

This document explains how to add new skills and how the skill system works.

---

## How it works

When a specialist runs (e.g., `identification_strategist`), the pipeline:

1. Looks up the specialist's skill list in `src/skills/loader.py` → `_SPECIALIST_SKILLS`
2. Searches `skills/files/**/*.md` for each skill name (filename stem, not full path)
3. Concatenates all found skill files into the specialist's system prompt

The LLM receives the concatenated skills under a `## Your Expertise` heading. Skills are written in prose; they are LLM-consumable instructions, not code.

---

## File format

Each skill file must have:

```markdown
# Skill Title

Brief one-paragraph description of what domain expertise this file provides.

---

## Section One

Content with rules, guidelines, examples, or checklists.

## Section Two

...
```

No YAML front matter. No special metadata. Just readable markdown.

---

## Naming conventions

| Convention | Example | Notes |
|-----------|---------|-------|
| Lowercase with hyphens | `iv-estimation.md` | No spaces, no underscores |
| Descriptive, not generic | `natural-experiments.md` not `causal.md` | Names appear in the specialist registry |
| Category subdirectory | `causal-inference/sensitivity.md` | Subdirectory for organisation only — the loader finds files by stem, ignoring directory |

The loader finds a skill by stem name (`sensitivity`) using `rglob("sensitivity.md")`. Directory structure is for humans, not for the loader.

**Consequence**: two files with the same stem in different directories will conflict — the loader returns whichever it finds first. Keep stems globally unique.

---

## Adding a new skill

### Step 1: Create the skill file

Place the file in the appropriate category directory:

```
skills/files/
  causal-inference/   — IV, DiD, RDD, natural experiments, sensitivity
  data/               — data sourcing, cleaning, DeFi, visualisation
  econometrics/       — specific methods (panel-data, time-series, rdd...)
  latex/              — LaTeX conventions for formulas, tables, bibliography
  math/               — proofs, optimisation, verification
  modeling/           — market microstructure, game theory, asset pricing
  reasoning/          — creative ideation, argument audit, novelty, anti-slop
  review/             — referee simulation, technical review, writing quality
  synthesis/          — context building, deliverables
  writing/            — paper structure, abstract, discussion, personal style
```

If your skill spans categories, put it in the closest match. Add a new category directory only if there is no reasonable fit.

### Step 2: Register the skill with the relevant specialist(s)

Edit `src/skills/loader.py` — the `_SPECIALIST_SKILLS` dictionary:

```python
_SPECIALIST_SKILLS: dict[str, list[str]] = {
    ...
    "identification_strategist": [
        "judge-designs",
        "natural-experiments",
        "identification",
        "your-new-skill",   # ← add here
    ],
    ...
}
```

Use the stem name only (no `.md`, no directory path).

### Step 3: Optionally update the documentation registry

`src/core/specialists/registry.py` → `SPECIALIST_SKILLS` is a documentation-only copy of the skill assignments (with full paths for readability). Update it to match:

```python
SPECIALIST_SKILLS: dict[str, list[str]] = {
    ...
    "identification_strategist": [
        "causal-inference/judge-designs",
        "causal-inference/natural-experiments",
        "reasoning/identification",
        "causal-inference/your-new-skill",   # ← add here
    ],
    ...
}
```

### Step 4: Run the tests

```bash
pytest tests/test_pipeline.py::test_skills_loaded_for_all_specialists -v
pytest tests/test_pipeline.py::test_skills_directory_has_expected_files -v
```

The first test verifies every specialist resolves to at least one skill. The second spot-checks that specific expected files are present and non-empty.

---

## Adding a new specialist type

If you are adding a new specialist (not just a new skill for an existing one):

1. Add the specialist to `src/core/specialists/registry.py` → `SPECIALIST_ARTIFACTS` (maps specialist name to output filename)
2. Add the specialist's skills list to `src/skills/loader.py` → `_SPECIALIST_SKILLS`
3. Add the specialist to the appropriate phase list in `src/core/strategist/runner.py` (initial phase, polish stack, reviewer list, etc.)
4. Create any required skill files
5. Add test coverage in `tests/test_pipeline.py`

---

## What makes a good skill file

**Do:**
- Write in second person ("You are reviewing...", "When you see...", "Always verify...")
- Include concrete checklists for common tasks
- Provide worked examples where useful (short ones — the LLM is not reading a textbook)
- State failure modes explicitly ("Watch out for...", "Do NOT...")
- Keep each file focused on one domain — resist the urge to merge multiple topics

**Do not:**
- Describe what the pipeline does (the specialist already knows its role)
- Include Python code or SQL unless specifically a code-writing skill
- Exceed ~1000 lines — longer files dilute the signal
- Duplicate content across files — prefer short cross-references

---

## Testing your skill file

The fastest way to verify a skill is injected correctly:

```python
from src.skills.loader import load_skills_for_specialist, _load_skill

# Check a specific skill loads
print(repr(_load_skill("your-new-skill")[:200]))

# Check a specialist's full skill block
print(load_skills_for_specialist("identification_strategist")[:500])
```

Then run the integration tests to confirm the specialist call succeeds end-to-end with the mock LLM:

```bash
pytest tests/test_pipeline.py -v -k "skills"
```

---

## Existing skills catalogue

Run `python3 -c "from src.skills.loader import list_available_skills; print('\n'.join(list_available_skills()))"` for the current list.

At the time of writing (v0.1), the following skills are included:

**reasoning**: anti-slop, argument-audit, creative-ideation, identification, novelty

**causal-inference**: judge-designs, natural-experiments, sensitivity, shift-share, weak-instruments

**econometrics**: did, event-study, iv-estimation, panel-data, rdd, time-series

**data**: blockchain, cleaning, crypto-defi, figure-spec, visualization

**writing**: abstract, discussion, paper-structure, personal-style, revision

**latex**: bibtex, econ-model, tables

**modeling**: asset-pricing, game-theory, market-microstructure

**math**: optimization-verification, proof-strategies

**synthesis**: context-builder, deliverables

**review**: consistency-check, constructive-feedback, data-quality, referee-simulation, reference-check, technical-review, writing-quality

**base**: economist, researcher
