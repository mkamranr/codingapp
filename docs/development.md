# Development

## Prerequisites

- Python 3.11
- Node 20+
- An OpenAI-compatible LLM endpoint (vLLM locally or on another machine) for manual testing. Tests don't need one.

## Backend

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt          # Windows: .venv\Scripts\pip
```

Configure through environment variables or `backend/.env` (ignored by git):

```ini
ADMIN_PASSWORD=admin123
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=EMPTY
```

Run it:

```bash
.venv/bin/python -m uvicorn app.main:app --port 8090 --reload
```

Data goes to `backend/data/` (or `DATA_DIR`). API docs: `http://localhost:8090/api/docs`.

## Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8090
npm run build      # type-check + production build into frontend/dist
```

To serve the built UI from the backend, set `STATIC_DIR=../frontend/dist`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```

The tests cover:
- extraction and its safety limits;
- context building and ranking;
- the code parser and the workspace;
- the API flows;
- LDAP modes (with a fake directory);
- the runtime entrypoint `docker/start.py`.

The release build runs the same tests inside the runtime image.

## Versions

| File | Bump when |
|---|---|
| `VERSION` | every release |
| `RUNTIME_VERSION` | `backend/requirements.txt` or the runtime stage of the `Dockerfile` changes |

Add an entry to `CHANGELOG.md`.

## Building releases

On a machine with Docker and internet access:

```bash
bash scripts/build-release.sh               # full offline package (runtime image + code)
bash scripts/build-release.sh --code-only   # code package (~400 KB), same runtime
```

Each build runs the tests, builds the UI, builds the runtime image, assembles `code/`, and self-tests
offline (`--network none`) before packaging. Details are in [BUILD.md](../BUILD.md).

`python scripts/make-source-package.py` creates `packages/codingapp-<ver>-source.zip` for
transferring the source to a build machine.

## Project conventions

- Deploy scripts are POSIX bash with LF line endings (`.gitattributes` enforces this).
- The UI must not load anything from the internet; the build fails if it does.
- Runtime settings that admins change go in the database (`runtime_settings`). Deployment settings go in `.env`.
