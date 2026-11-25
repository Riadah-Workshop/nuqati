## What and why

<!-- One or two sentences. Link the issue or audit item if there is one. -->

## How it was tested

- [ ] `make test` passes locally (or CI is green)
- [ ] Tried it by hand: <!-- what you clicked / which endpoint you called -->

## Risk checklist

- [ ] **Database:** no new tables/columns, or they are in an Alembic revision (`python -m app.migrate new "..."`), additive, and described below
- [ ] **Driver/Manager app:** if `driver_app/` or `manager_app/` changed, it was tried on a real phone (GPS, offline queue, camera as relevant)
- [ ] **Secrets:** no keys, passwords, keystores or `.env` files in the diff
- [ ] **Deployment:** backend and web are deployed from the **same commit**; mobile changes need a new signed build
- [ ] **Docs:** `README.md` / `docs/` / `CHANGELOG.md` updated if behaviour or setup changed

## Notes for the reviewer

<!-- Anything surprising: trade-offs, follow-ups, things you did not touch on purpose. -->
