# GitHub via `e2er-data github`

The GitHub REST API (https://api.github.com) describes public repositories:
their stars, forks, open issues, watchers, main language and bytes per
language, licence, topics, creation and last-push dates, number of
contributors, and releases. e2er loads metadata only, never repository
contents, and no personal fields beyond the owner's account name (no e-mail
addresses, no contributor identities).

Use it for studies of open-source software: adoption and popularity of
libraries, the growth of a topic (e.g. `machine-learning`, `econometrics`),
licence choice, release cadence, research software.

A key is optional. Without one GitHub allows 60 requests an hour and 10
searches a minute from one IP address; a personal access token (no scopes
needed for public data) raises this to 5,000 an hour and 30 searches a
minute. Set it as `GITHUB_TOKEN` (the setting e2er reads; e2er never uses the
machine's `gh` login).

## Terms of use

- "Researchers may use public, non-personal information from the Service for
  research purposes, only if any publications resulting from that research are
  open access." The paper must be open access.
- Personal information may be used only for the purpose its user authorized.
  Do not study individual developers.
- Repository contents belong to their owners under their own licences (the
  `license` column); e2er loads metadata only.
- GitHub grants no licence to pass the metadata on. A published study does not
  ship them: publishing asks the researcher to confirm
  (`--accept-data-terms github`), and the replication package loads them again
  (get_data.py). Stars and counts change daily, so a reload differs: report
  the load's date.
- Full terms: https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies
  and https://docs.github.com/en/site-policy/github-terms/github-terms-of-service (section H)

GitHub publishes no citation for its API; e2er cites "GitHub, Inc. GitHub REST
API (version 2022-11-28). https://docs.github.com/en/rest. Accessed <date>."
(BibTeX key `GitHub_RESTAPI`, added on the first load).

## Subcommands

```
e2er-data github repos --topic econometrics --language Python --min-stars 50 --sort stars \
    --limit 200 --table econ_repos
e2er-data github repos --query "difference-in-differences in:description,readme" \
    --created-after 2018-01-01 --created-before 2018-12-31 --limit 1000 --table did_2018
e2er-data github repo --repos statsmodels/statsmodels,pandas-dev/pandas --table libs
e2er-data github releases --repo statsmodels/statsmodels --table sm_releases
```

`repos` (search) options: `--query` (GitHub search syntax allowed),
`--topic` (comma-separated; all must match), `--language`, `--min-stars`,
`--created-after` / `--created-before` (YYYY-MM-DD), `--sort` (`stars`,
`forks`, `updated`, `help-wanted-issues`; default best match), `--limit`
(default 100, at most 1,000). One row per repository: `full_name`, `owner`,
`owner_type` (User or Organization), `name`, `description`, `url`,
`language`, `topics`, `license` (SPDX id), `stars`, `forks`, `open_issues`,
`watchers`, `size_kb`, `fork`, `archived`, `is_template`, `default_branch`,
`created_at`, `updated_at`, `pushed_at`.

`repo` options: `--repos` (owner/name, comma-separated; at most 15 without a
token, 100 with one). The same columns plus `languages` (bytes per language)
and `contributors` (a count).

`releases` options: `--repo` (owner/name). One row per release (at most
1,000, newest first): `tag`, `name`, `published_at`, `created_at`,
`prerelease`, `draft`, `assets`, `downloads` (the assets' download counts).

## Pitfalls

- A search returns at most 1,000 repositories however many match (the load
  note gives the total). For a complete population split the creation period
  into slices that each match fewer than 1,000.
- Search counts can be incomplete when GitHub's search times out; the load
  records `incomplete_results`.
- Stars measure attention, not use; forks include personal copies. Say which
  the study means.
- `contributors` counts at most 500 by e-mail address and includes anonymous
  contributors.
- Without a token the 60 requests an hour run out fast (`repo` costs three per
  repository): plan the loads, or set `GITHUB_TOKEN`.

## What a load records

Every load that returns rows is recorded in `data_sources.json`: the terms,
the citation, the request, the first query URL, the search string and total
count, the date of the load (version), and when it ran. A table also gets its
entry in `data_dictionary.json`. A bad repository name, an unknown repository
or GitHub's rate limit exits non-zero and leaves data.db unchanged. Report the
error; do not build the table another way.
