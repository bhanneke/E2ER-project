# Publishing a study

`e2er publish <folder>` describes an exported study, writes its dossier and, with `--to https://e2er.org`, publishes the description. The files stay on your computer or in your repository; e2er.org receives the description, the dossier and a fingerprint (SHA-256) of every file.

## Data and code: public or private

You state separately whether the study's data and its code are public:

```
e2er publish ./my-study --owner you --project my-study --data private --code public \
  --repo https://github.com/you/my-study --commit 3b91f0e
```

Both are private unless you say otherwise; run in a terminal without the two flags, `e2er publish` asks. For private material, only fingerprints are published, never contents or an address. For public material, give its address with `--data-url` or `--code-url`; public code defaults to your repository at the pinned commit.

The study page and the dossier show what you chose, for instance "data private · code public". A dossier lists availability only when something is public, so a private study's dossier address does not change.

## A DOI for public data and code in one step

`--zenodo` deposits the public data and code on Zenodo with your own account and records the DOIs:

```
export ZENODO_TOKEN=…   # a personal token from zenodo.org, scope deposit:write
e2er publish ./my-study … --data public --code public --zenodo
```

The data files are deposited one by one, the code (`code/` and `replication/`) as one zip. Each deposit names the study's authors with their ORCID iDs, its licence, and links back to the study page and the dossier; the DOIs go into the dossier and the study page. The files go from your computer straight to Zenodo; the token is never sent to e2er.org. Private material is never deposited.

To try it first, use Zenodo's sandbox (`--zenodo-sandbox`, token in `ZENODO_SANDBOX_TOKEN`), or add `--dry-run` to see what would be deposited without depositing anything.
