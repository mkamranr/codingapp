# Building the packages (internet-connected machine)

Everything is built and tested here; the air-gapped server downloads nothing.

## Requirements

| | |
|---|---|
| OS | Linux or macOS (bash), or Windows with Docker Desktop in **Linux containers** mode |
| Docker | 20.10+ with BuildKit (default in Docker 23+) |
| Internet | Docker Hub (`node`, `python` base images), npm registry, PyPI |
| Disk | ~3 GB free |

You don't need Node or Python: everything builds inside Docker. Behind a proxy? Export
`HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` first; they are passed to the build.

## Build

```bash
unzip codingapp-1.0.1-source.zip
cd codingapp-1.0.1-source
bash scripts/build-release.sh
```

Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1`

Result, in `release/`:

```
codingapp-1.0.1-offline.tar.gz          <- carry this to the air-gapped server
codingapp-1.0.1-offline.tar.gz.sha256   <- its checksum (compare after the transfer)
```

Then follow **DEPLOY.md**, which is also inside the package. In short:
`tar -xzf codingapp-1.0.1-offline.tar.gz && cd codingapp && sudo bash install.sh`.

Building only creates files in `release/`. It never installs or starts CodingApp on the build
machine, and it never uses its port.

### What the script does (any failure stops it, so no broken package is produced)

1. **Backend tests** run on the runtime image (same Linux and Python as production).
2. **Web UI build**, with Node inside Docker. It fails if the UI would load anything from the internet.
3. **Runtime image** `codingapp-runtime:<RUNTIME_VERSION>`: Python + pinned libraries, no app code.
4. **Code folder**: backend (`app/`), built UI (`static/`), `VERSION`, `requirements.txt`.
5. **Offline self-test**: the code runs in the runtime image with `--network none`. It checks
   the libraries match, the app starts, the UI and assets are served, admin login works, the
   database is writable and the admin API works.
6. **Package** with `MANIFEST.txt` (kind, version, runtime, CPU, image id) and `SHA256SUMS`.

## Later releases

| You changed… | Do | Build | On the server |
|---|---|---|---|
| backend or UI code only | bump `VERSION` | `bash scripts/build-release.sh --code-only` → `codingapp-code-<v>.tar.gz` (~400 KB) | `sudo ./codingapp.sh update <file>` |
| `backend/requirements.txt` (libraries) or the runtime part of the Dockerfile | bump `VERSION` **and** `RUNTIME_VERSION` | `bash scripts/build-release.sh` → full package | `sudo ./codingapp.sh update <file>` |

Windows: add `-CodeOnly` for a code package. If you forget to bump `RUNTIME_VERSION`, nothing
breaks silently: the server refuses a code package whose libraries don't match its runtime.

## Other CPU

The package must match the **server's** CPU (`uname -m` there: `x86_64` → `linux/amd64`, the
default; `aarch64` → `linux/arm64`): `bash scripts/build-release.sh --platform linux/arm64`.
Cross-building needs emulation once: `docker run --privileged --rm tonistiigi/binfmt --install all`.
The installer refuses a package built for the wrong CPU.
