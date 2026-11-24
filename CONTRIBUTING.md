# Contributing

Short version: **branch → small pull request → green CI → review → squash merge.**
Never put ZIP contents over `main`, and never edit `main` directly.

## Workflow

1. Update and branch from `main`:
   `git switch main && git pull && git switch -c fix/short-description`
2. Branch names: `feat/…`, `fix/…`, `chore/…`, `docs/…`, `ci/…`, `hotfix/…`.
3. Make one logical change per pull request. If a PR needs a long description of unrelated
   things, split it.
4. Run `make test` (and `make test-pg` if you touched the API or the schema) before pushing.
5. Open a pull request; the template lists what reviewers look for. CI must be green.
6. A teammate reviews. Authors do not approve their own pull requests.
7. Merge with **Squash and merge**. The squash commit message is the permanent history, so write
   it well.

## Commit and PR titles

Imperative mood, with a type prefix: `feat: …`, `fix: …`, `refactor: …`, `docs: …`, `test: …`,
`ci: …`, `chore: …`. Explain *why* in the body when it is not obvious.
Example: `fix: reject GPS samples older than the latest accepted one`.

## Rules that protect production

- **Secrets never enter git.** No `.env` files, keystores, passwords or API keys in commits,
  issues, screenshots or logs. `.gitignore` and `test_repo_hygiene.py` catch common cases, not
  all. If one slips in, rotate it: removing it from a later commit does not remove it from history.
- **Database changes are additive and idempotent** (section 6 of `docs/DEVELOPMENT.md`).
- **Backend and web ship together** from the same commit.
- **Driver / Manager app changes need a real-phone test** before a release build (GPS in the
  background, offline queue, camera, battery saver). Note what you tested in the PR.
- **Do not rename paths pinned by contract tests** (Kotlin ↔ Dart ↔ Python strings) without
  updating the test and explaining why.
- **Patch notes do not belong in the repository root.** Write release notes in `CHANGELOG.md`
  and design notes in `docs/`; `docs/history/` is read-only history.

## Hotfixes

Production broken and the normal route too slow? Branch `hotfix/…` from `main`, keep the change
minimal, open the PR, get one review, merge, deploy, and write the post-incident note in
`CHANGELOG.md`. Skipping review is a last resort that someone other than the author must
agree to.

## Reviewing

Ask: does it do what the description says, does CI cover it, could it break existing data or
installed apps, and is anything sensitive in the diff? Small, specific comments are better than
rewrites. Approve only what you would be comfortable deploying.

## Branch protection (maintainers, once)

See section 5 of [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
