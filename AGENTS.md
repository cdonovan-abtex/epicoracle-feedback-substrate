**Why this exists:** see [CAPTAINS-INTENT.md](CAPTAINS-INTENT.md).

## Validation

The authoritative all-PR validation contract and local command sequence live in
[`.github/workflows/test.yml`](.github/workflows/test.yml). Keep `uv.lock` committed and in sync
with `pyproject.toml`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
