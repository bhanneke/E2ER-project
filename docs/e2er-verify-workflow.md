# Checking a study in GitHub Actions and reporting to e2er.org

A published study shows who ran each check: the author (`e2er verify` at
publish), e2er.org (its own check of every file at the pinned commit), and
GitHub Actions. Only the last two ran outside the author's control.

The workflow [`examples/github-actions/e2er-verify.yml`](../examples/github-actions/e2er-verify.yml)
runs `e2er verify <folder> --json` on every push and posts the result to
`https://e2er.org/api/v1/actions/results`. It stores no secret. GitHub gives the
job an OIDC token (`permissions: id-token: write`) whose audience is the
platform; the token says which repository, workflow file and commit produced
the result, and e2er.org checks its signature against GitHub's published keys.

## Set it up

1. Copy the file to `.github/workflows/e2er-verify.yml` in the repository that
   holds the study folder, and set `BUNDLE` to the folder's path.
2. On e2er.org, open your account, section **GitHub Actions**, and add the
   study, the repository (`owner/name`) and the workflow file
   (`.github/workflows/e2er-verify.yml`). Optionally name a GitHub environment;
   then only jobs running in that environment are accepted.
3. Push. The study page lists the run under "Checked in GitHub Actions".

A result is accepted only for the commit the published version pins, and only
when the checked folder's content id (the SHA-256 of `provenance.json`) is the
published one. A run reports once per attempt.

For the staging platform, set `E2ER_URL: https://preview.e2er.org`.
