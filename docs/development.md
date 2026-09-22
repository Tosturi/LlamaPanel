# Development and releases

[Documentation](README.md) · [Architecture](HLD.md)

## Local development

Start the backend from the repository root:

```bash
python run.py --reload
```

Start the frontend in another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite serves the UI at `http://localhost:5173` and proxies `/api`, including
the logs WebSocket, to `http://localhost:8000`.

Run checks from the repository root:

```bash
python -m pip install -r backend/requirements-dev.txt
cd backend
python -m pytest -q
cd ../frontend
npm ci
npm run build
npm run gen:api
```

Review generated changes in `frontend/src/api-types.ts` and commit them when
the API contract changes.

## Frontend API types

`frontend/src/api-types.ts` is generated from the backend OpenAPI schema and
tracked in Git:

```bash
cd frontend && npm run gen:api
```

The script uses Python from `./.venv` (or `$PYTHON`, or `python` on PATH),
exports the schema through `backend/export_openapi.py`, and runs
`openapi-typescript`. `src/types.ts` contains short aliases for the generated
types. Regenerate after changing `backend/app/schemas.py` or routes; CI compares
the file with the current schema and fails if it is outdated.

## Pipelines

- **CI** (`.github/workflows/ci.yml`) runs backend tests, frontend type checking
  and builds, and checks API types on every PR and push to `main`. It publishes nothing.
- **Release** (`.github/workflows/release.yml`) runs on `v*` tags. It checks that
  the tag matches `VERSION`, runs tests, builds the frontend, packages
  `LlamaPanel-v<version>.zip` (including `docs/`) and its `.sha256`, and creates
  a GitHub Release with the commits since the previous tag.

Release archives also include `release.json`, declaring the updater protocol and
minimum Python version. See [application updates](updates.md) before changing
the release layout or launcher protocol. Version bumps remain a maintainer action;
the updater only installs published stable releases.

There are two ways to publish a new version. The versions below are examples;
choose a version newer than the current one.

**GitHub Actions** (`.github/workflows/bump-version.yml`): open Actions →
**Bump version** → **Run workflow** and enter a version such as `0.2.0`.
The workflow validates the format and version increase, updates `VERSION`,
commits to `main`, creates `v0.2.0`, and pushes. This triggers `release.yml`.
It requires a `RELEASE_TOKEN` secret: a fine-grained PAT with Contents: Read
and write for this repository. Tags pushed with the default `GITHUB_TOKEN`
do not trigger other workflows.

**Manually:**

```bash
echo 0.2.0 > VERSION
git commit -am "Bump version to 0.2.0"
git tag v0.2.0
git push && git push origin v0.2.0
```
