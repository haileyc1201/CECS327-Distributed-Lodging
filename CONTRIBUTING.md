# Working on the Repo

Try to work on your own branch instead of editing `main` directly.

## Start

```bash
git pull
git checkout -b yourname-task
```

Example:

```bash
git checkout -b hailey-report
```

## Save your work

```bash
git status
git add .
git commit -m "Update Milestone 1 report"
git push -u origin yourname-task
```

After that, open a pull request on GitHub.

A few things that will save us headaches:

- Pull before starting new work.
- Let the group know before editing the same file as someone else.
- Do not commit passwords, API keys, or access tokens.
- Put logs in `logs/`.
- Put screenshots in `screenshots/`.
- Put the architecture diagram in `docs/diagrams/`.
