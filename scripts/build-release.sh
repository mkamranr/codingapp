#!/usr/bin/env bash
# Run on the INTERNET-connected build server (Linux/macOS with Docker). Needs only Docker + bash.
#
#   bash scripts/build-release.sh                 FULL package: runtime image + code + install scripts
#       -> release/codingapp-<version>-offline.tar.gz   (unpacks to a folder named "codingapp")
#   bash scripts/build-release.sh --code-only     CODE update only (no image, a few hundred KB)
#       -> release/codingapp-code-<version>.tar.gz
#   options: --platform linux/arm64   (default linux/amd64)
#
# Versions: ./VERSION (application) and ./RUNTIME_VERSION (runtime image; bump it whenever
# backend/requirements.txt or the runtime part of the Dockerfile changes).
# Every step must pass, otherwise nothing is packaged.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE=full
PLATFORM=linux/amd64
while [ $# -gt 0 ]; do
  case "$1" in
    --code-only) MODE=code; shift ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    *) echo "Unknown option $1"; exit 1 ;;
  esac
done
VERSION="$(tr -d ' \r\n' < VERSION)"
RUNTIME="$(tr -d ' \r\n' < RUNTIME_VERSION)"
IMAGE="codingapp-runtime:$RUNTIME"
STAGE="$ROOT/release/.stage"
export DOCKER_BUILDKIT=1

step() { echo; echo "=== $* ==="; }
lf() { sed 's/\r$//' "$1" > "$2"; }   # copy a text file with LF line endings

step "Pre-flight"
command -v docker >/dev/null || { echo "Docker is not installed"; exit 1; }
docker info >/dev/null || { echo "Cannot reach the Docker daemon"; exit 1; }
NATIVE="linux/$(docker version -f '{{.Server.Arch}}')"
echo "mode=$MODE  version=$VERSION  runtime=$RUNTIME  platform=$PLATFORM  (build host: $NATIVE)"
[ "$PLATFORM" = "$NATIVE" ] || echo "NOTE: cross-building; QEMU/binfmt must be set up (docker run --privileged --rm tonistiigi/binfmt --install all)"

PROXY_ARGS=()
for v in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
  [ -n "${!v:-}" ] && PROXY_ARGS+=(--build-arg "$v=${!v}")
done

step "1/6 Backend tests (on the runtime image)"
docker build --pull --platform "$PLATFORM" --target test "${PROXY_ARGS[@]}" -t "codingapp-test:$VERSION" .
docker rmi "codingapp-test:$VERSION" >/dev/null 2>&1 || true

step "2/6 Build the web UI"
docker build --platform "$PLATFORM" --target web "${PROXY_ARGS[@]}" -t "codingapp-web:$VERSION" .
rm -rf "$STAGE"; mkdir -p "$STAGE/code"
cid="$(docker create --platform "$PLATFORM" "codingapp-web:$VERSION")"
docker cp "$cid:/web/dist" "$STAGE/code/static"
docker rm "$cid" >/dev/null
docker rmi "codingapp-web:$VERSION" >/dev/null 2>&1 || true

step "3/6 Build runtime image $IMAGE"
docker build --platform "$PLATFORM" --target release --build-arg "RUNTIME_VERSION=$RUNTIME" "${PROXY_ARGS[@]}" -t "$IMAGE" .

step "4/6 Assemble code $VERSION"
mkdir -p "$STAGE/code/app"
( cd backend/app && find . -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 ) | while IFS= read -r -d '' f; do
  mkdir -p "$STAGE/code/app/$(dirname "$f")"
  lf "backend/app/$f" "$STAGE/code/app/$f"
done
lf backend/requirements.txt "$STAGE/code/requirements.txt"
echo "$VERSION" > "$STAGE/code/VERSION"
chmod -R a+rX "$STAGE/code"

step "5/6 Offline self-test: runtime image + code, container started with --network none"
docker run --rm --network none -v "$STAGE/code:/code:ro" --entrypoint python "$IMAGE" /opt/runtime/start.py --check /code
docker rm -f -v codingapp-selftest >/dev/null 2>&1 || true
docker run -d --name codingapp-selftest --platform "$PLATFORM" --network none -v "$STAGE/code:/code:ro" \
  -e ADMIN_PASSWORD=selftest-pass -e LLM_BASE_URL=http://127.0.0.1:9/v1 "$IMAGE" >/dev/null
trap 'docker rm -f -v codingapp-selftest >/dev/null 2>&1 || true' EXIT
if ! docker exec -i codingapp-selftest python - < scripts/selftest.py; then
  docker logs codingapp-selftest | tail -50
  echo "SELF-TEST FAILED: nothing is packaged."; exit 1
fi
docker rm -f -v codingapp-selftest >/dev/null; trap - EXIT

step "6/6 Package"
if [ "$MODE" = full ]; then NAME="codingapp"; FILE="codingapp-$VERSION-offline.tar.gz"   # unpacks to ./codingapp = the project folder
else NAME="codingapp-code-$VERSION"; FILE="codingapp-code-$VERSION.tar.gz"; fi
PKG="$ROOT/release/.pkg"; OUT="$PKG/$NAME"
rm -rf "$PKG"
rm -rf "$OUT"; mkdir -p "$OUT"
mv "$STAGE/code" "$OUT/code"
lf scripts/selftest.py "$OUT/selftest.py"
lf CHANGELOG.md "$OUT/CHANGELOG.md"
if [ "$MODE" = full ]; then
  docker save "$IMAGE" | gzip -6 > "$OUT/codingapp-runtime-$RUNTIME.tar.gz"
  for f in deploy/docker-compose.yml deploy/.env.example deploy/codingapp.sh deploy/install.sh DEPLOY.md; do
    lf "$f" "$OUT/$(basename "$f")"
  done
  sed "s/^RUNTIME_VERSION=.*/RUNTIME_VERSION=$RUNTIME/" "$OUT/.env.example" > "$OUT/.env.tmp"
  mv "$OUT/.env.tmp" "$OUT/.env.example"
  chmod +x "$OUT/codingapp.sh" "$OUT/install.sh"
fi
{
  echo "name=codingapp"
  echo "kind=$MODE"
  echo "version=$VERSION"
  echo "runtime=$RUNTIME"
  echo "arch=$PLATFORM"
  echo "image=$IMAGE"
  echo "image_id=$(docker image inspect -f '{{.Id}}' "$IMAGE")"
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "built_on=$(hostname)"
} > "$OUT/MANIFEST.txt"
SHA=sha256sum; command -v sha256sum >/dev/null || SHA="shasum -a 256"   # macOS
( cd "$OUT" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort \
    | while IFS= read -r f; do $SHA "$f"; done > SHA256SUMS )
rm -rf "$STAGE"
tar -C "$PKG" -czf "$ROOT/release/$FILE" "$NAME"
rm -rf "$PKG"
( cd "$ROOT/release" && $SHA "$FILE" > "$FILE.sha256" )

echo
echo "DONE"
echo "  Carry to the air-gapped server:  release/$FILE"
echo "  Its checksum:                    $(cut -d' ' -f1 "$ROOT/release/$FILE.sha256")"
if [ "$MODE" = full ]; then
  echo "  First install there:             tar -xzf $FILE && cd codingapp && sudo bash install.sh"
  echo "  Upgrade an installed folder:     cd codingapp && sudo ./codingapp.sh update /path/to/$FILE"
else
  echo "  Apply there:                     cd codingapp && sudo ./codingapp.sh update /path/to/$FILE"
fi
ls -lh "$ROOT/release/$FILE"
