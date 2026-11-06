#!/usr/bin/env bash
# CodingApp management script for the AIR-GAPPED server. Needs only bash + Docker (>= 20.10).
#
# Everything lives in THIS folder (the project folder):
#   .env      settings                  code/           application (mounted read-only)
#   data/     database + secret key     code.previous/  code before the last update (rollback)
#   backups/  backups                   codingapp-runtime-<n>.tar.gz   runtime image file
# The Docker image is only the runtime (Python + libraries).
#
#   sudo bash install.sh                  first install (or repair) in this folder
#   sudo ./codingapp.sh update <package>  apply a code package OR a newer full package
#   sudo ./codingapp.sh rollback          back to the code that ran before the last update
#   sudo ./codingapp.sh restart           after editing .env or files in code/
#   sudo ./codingapp.sh start|stop|status|logs|version|check-llm
#   sudo ./codingapp.sh backup | restore <file>
#   sudo ./codingapp.sh uninstall [--purge]   (--purge also deletes data/)
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$HERE"

PROJECT=codingapp
CONTAINER=codingapp
OLD_VOLUME=codingapp_data   # where version 1.0.0 kept its data
APP_UID=10001

if [ -t 1 ]; then R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[1m'; N=$'\e[0m'; else R= G= Y= B= N=; fi
info() { echo "${G}>>${N} $*"; }
warn() { echo "${Y}!!${N} $*" >&2; }
die()  { echo "${R}xx${N} $*" >&2; exit 1; }
step() { echo; echo "${B}== $*${N}"; }

manifest_get() { grep -E "^$1=" "${2:-MANIFEST.txt}" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '\r' || true; }
BUNDLE_KIND="$(manifest_get kind)"
BUNDLE_VERSION="$(manifest_get version)"
BUNDLE_RUNTIME="$(manifest_get runtime)"
BUNDLE_ARCH="$(manifest_get arch)"

env_get() {  # env_get KEY [default]
  local v=""
  [ -f .env ] && v="$(grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '\r' || true)"
  echo "${v:-${2:-}}"
}
env_set() {  # env_set KEY VALUE
  local v; v="$(printf '%s' "$2" | sed -e 's/[\\&|]/\\&/g')"   # escape \ & | for sed
  if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$v|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi
}

runtime_version() { env_get RUNTIME_VERSION "${BUNDLE_RUNTIME:-1}"; }
runtime_image() { echo "codingapp-runtime:$(runtime_version)"; }
code_version() { tr -d ' \r\n' < "${1:-code}/VERSION" 2>/dev/null || echo "?"; }

# ---------- docker / compose ----------
need_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed."
  if ! docker info >/dev/null 2>&1; then
    if [ "$(id -u)" -ne 0 ]; then die "Cannot talk to the Docker daemon. Run with sudo, or add $(whoami) to the 'docker' group."; fi
    die "The Docker daemon is not running (try: systemctl start docker)."
  fi
}
DC=()
detect_compose() {
  if docker compose version >/dev/null 2>&1; then DC=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then DC=(docker-compose)
  else DC=(); fi
}
dc() { "${DC[@]}" -p "$PROJECT" -f docker-compose.yml "$@"; }
container_exists() { docker container inspect "$CONTAINER" >/dev/null 2>&1; }
container_running() { [ "$(docker container inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || echo false)" = "true" ]; }
restart_count() { docker container inspect -f '{{.RestartCount}}' "$CONTAINER" 2>/dev/null || echo 0; }
image_present() { docker image inspect "$1" >/dev/null 2>&1; }

HEALTH_PY='import json,urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8090/api/health",timeout=5).read().decode())'

wait_healthy() {
  info "Waiting for CodingApp to become ready..."
  local i out
  for i in $(seq 1 60); do
    if ! container_running || [ "$(restart_count)" != "0" ]; then
      docker logs --tail 60 "$CONTAINER" 2>&1 || true
      die "The container stopped or keeps restarting. See the log above."
    fi
    if out="$(docker exec "$CONTAINER" python -c "$HEALTH_PY" 2>/dev/null)"; then
      info "Ready: $out"
      return 0
    fi
    sleep 2
  done
  docker logs --tail 60 "$CONTAINER" 2>&1 || true
  die "CodingApp did not become ready within 2 minutes."
}

health_version() {
  docker exec "$CONTAINER" python -c "$HEALTH_PY" 2>/dev/null \
    | sed -n 's/.*"version":"\([^"]*\)".*/\1/p' || true
}

# data/ must exist and belong to the container user (uid 10001)
ensure_data() {
  mkdir -p data
  if [ "$(stat -c %u data 2>/dev/null || echo x)" != "$APP_UID" ]; then
    docker run --rm --user 0 --network none -v "$HERE/data:/data:z" --entrypoint chown "$(runtime_image)" -R "$APP_UID" /data
  fi
}

cmd_start() {
  need_docker; detect_compose
  [ -f .env ] || die ".env not found in $HERE. Install first: sudo bash install.sh"
  [ -f code/app/main.py ] || die "Application code is missing: $HERE/code/app/main.py"
  local img; img="$(runtime_image)"
  image_present "$img" || die "Runtime image $img is not loaded. Run: sudo bash install.sh"
  chmod -R a+rX code 2>/dev/null || true   # the container user must be able to read the code
  ensure_data
  if container_exists && [ -z "$(docker container inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$CONTAINER" 2>/dev/null)" ] && [ ${#DC[@]} -gt 0 ]; then
    docker rm -f "$CONTAINER" >/dev/null   # created by plain docker run earlier
  fi
  if [ ${#DC[@]} -gt 0 ]; then
    info "Starting code $(code_version) on $img with ${DC[*]}"
    dc up -d --no-build --remove-orphans
  else
    warn "Docker Compose not found; starting with plain 'docker run'."
    info "Starting code $(code_version) on $img"
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$CONTAINER" --restart unless-stopped \
      --env-file .env \
      -p "$(env_get APP_BIND 0.0.0.0):$(env_get APP_PORT 8090):8090" \
      -v "$HERE/data:/data:z" \
      -v "$HERE/code:/code:ro,z" \
      --add-host host.docker.internal:host-gateway \
      --log-driver json-file --log-opt max-size=20m --log-opt max-file=5 \
      "$img" >/dev/null
  fi
  wait_healthy
  local host; host="$( (hostname -I 2>/dev/null || true) | awk '{print $1}')"
  info "CodingApp: ${B}http://${host:-<server>}:$(env_get APP_PORT 8090)${N}"
}

cmd_stop() {
  need_docker; detect_compose
  if [ ${#DC[@]} -gt 0 ] && [ -n "$(docker container inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$CONTAINER" 2>/dev/null)" ]; then
    dc down --remove-orphans
  elif container_exists; then
    docker rm -f "$CONTAINER" >/dev/null
  fi
  info "Stopped (data is kept in $HERE/data)."
}

cmd_version() {
  echo "Project folder : $HERE"
  echo "Code version   : $(code_version)"
  echo "Runtime image  : $(runtime_image)"
  echo "Settings       : $HERE/.env  (port $(env_get APP_PORT 8090))"
  echo "Data           : $HERE/data"
  [ -d code.previous ] && echo "Rollback to    : $(code_version code.previous)  (./codingapp.sh rollback)"
  return 0
}

cmd_status() {
  need_docker
  cmd_version
  if ! container_exists; then warn "Not running."; return 1; fi
  docker ps -a --filter "name=^/${CONTAINER}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  if container_running; then docker exec "$CONTAINER" python -c "$HEALTH_PY" || true; fi
}

cmd_logs() { need_docker; docker logs -f --tail "${1:-200}" "$CONTAINER"; }

LLM_CHECK_PY='
import json, os, sys, urllib.request
base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
key = os.environ.get("LLM_API_KEY", "") or "EMPTY"
hdr = {"Authorization": "Bearer " + key}
print("LLM_BASE_URL =", base)
try:
    req = urllib.request.Request(base + "/models", headers=hdr)
    data = json.load(urllib.request.urlopen(req, timeout=15))
except Exception as e:
    print("FAILED to reach", base + "/models:", e); sys.exit(1)
for m in data.get("data", []):
    print("  model:", m.get("id"), " max_model_len:", m.get("max_model_len"))
want = os.environ.get("LLM_MODEL", "")
if want and want not in [m.get("id") for m in data.get("data", [])]:
    print("FAILED: LLM_MODEL", want, "is not served by this server"); sys.exit(1)
root = base[:-3] if base.endswith("/v1") else base
try:
    req = urllib.request.Request(root + "/tokenize", data=json.dumps({"prompt": "hello"}).encode(),
                                 headers={**hdr, "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)
    print("  /tokenize: available (exact token counting)")
except Exception:
    print("  /tokenize: not available (token counts will be estimated)")
print("OK")
'

cmd_check_llm() {
  need_docker
  local img; img="$(runtime_image)"
  image_present "$img" || die "Runtime image $img is not loaded."
  [ -f .env ] || die ".env not found."
  info "Checking the LLM connection from inside a container..."
  docker run --rm --env-file .env --add-host host.docker.internal:host-gateway \
    --entrypoint python "$img" -c "$LLM_CHECK_PY"
}

cmd_backup() {
  need_docker
  local img stamp tmp out
  img="$(runtime_image)"; stamp="$(date +%Y%m%d-%H%M%S)"; tmp="$(mktemp -d "$HERE/.backup.XXXXXX")"
  mkdir -p backups; out="backups/codingapp-backup-$stamp.tar.gz"
  chmod 777 "$tmp"
  if container_running; then
    # consistent online copy using SQLite's backup API (works for 1.0.0 containers too)
    docker exec "$CONTAINER" python -c "import sqlite3;s=sqlite3.connect('/data/codingapp.db');d=sqlite3.connect('/data/.backup.db');s.backup(d);d.close()"
    docker cp "$CONTAINER:/data/.backup.db" "$tmp/codingapp.db"
    docker exec "$CONTAINER" rm -f /data/.backup.db
    docker cp "$CONTAINER:/data/secret.key" "$tmp/secret.key" 2>/dev/null || true
  elif [ -f data/codingapp.db ]; then
    image_present "$img" || die "Runtime image $img is not loaded."
    docker run --rm --user 0 --network none -v "$HERE/data:/data:ro,z" -v "$tmp:/b:z" --entrypoint sh "$img" \
      -c 'cp /data/codingapp.db /b/ && (cp /data/secret.key /b/ 2>/dev/null || true) && chmod -R a+r /b' \
      || { rm -rf "$tmp"; die "Backup failed: could not copy $HERE/data."; }
  else
    rm -rf "$tmp"; warn "Nothing to back up yet."; return 0
  fi
  [ -f .env ] && cp .env "$tmp/env.backup"
  tar -C "$tmp" -czf "$out" .
  rm -rf "$tmp"
  chmod 600 "$out"
  info "Backup written: $HERE/$out  (contains secrets, keep it safe)"
}

cmd_restore() {
  local file="${1:-}"
  [ -f "$file" ] || die "Usage: ./codingapp.sh restore backups/codingapp-backup-<date>.tar.gz"
  need_docker
  local img tmp; img="$(runtime_image)"; tmp="$(mktemp -d "$HERE/.restore.XXXXXX")"
  tar -C "$tmp" -xzf "$file"
  [ -f "$tmp/codingapp.db" ] || { rm -rf "$tmp"; die "Not a CodingApp backup (codingapp.db missing)."; }
  read -r -p "This REPLACES all current CodingApp data. Type 'restore' to continue: " ans
  [ "$ans" = "restore" ] || { rm -rf "$tmp"; die "Cancelled."; }
  if [ -f "$tmp/env.backup" ]; then
    local old; old="$(grep -E '^SECRET_KEY=' "$tmp/env.backup" | cut -d= -f2- || true)"
    if [ -n "$old" ] && [ "$old" != "$(env_get SECRET_KEY)" ]; then
      warn "SECRET_KEY in the backup differs from .env; restoring the backup's SECRET_KEY."
      env_set SECRET_KEY "$old"
    fi
  fi
  chmod -R a+rX "$tmp"
  cmd_stop
  mkdir -p data
  docker run --rm --user 0 --network none -v "$HERE/data:/data:z" -v "$tmp:/r:ro,z" --entrypoint sh "$img" -c \
    "rm -f /data/codingapp.db /data/codingapp.db-wal /data/codingapp.db-shm && cp /r/codingapp.db /data/ && \
     (cp /r/secret.key /data/ 2>/dev/null || true) && chown -R $APP_UID /data"
  rm -rf "$tmp"
  cmd_start
}

cmd_uninstall() {
  need_docker
  cmd_stop || true
  if [ "${1:-}" = "--purge" ]; then
    read -r -p "Delete ALL CodingApp data in $HERE/data? Type 'delete' to confirm: " ans
    [ "$ans" = "delete" ] || die "Cancelled."
    if [ -d data ]; then
      docker run --rm --user 0 --network none -v "$HERE/data:/data:z" --entrypoint sh "$(runtime_image)" \
        -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null; true' || true
      rmdir data 2>/dev/null || true
    fi
    info "Data removed."
  fi
  docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^codingapp(-runtime)?:' | xargs -r docker rmi >/dev/null 2>&1 || true
  info "Container and images removed. $HERE is kept (delete the folder to remove everything)."
}

# ---------- shared by install / update ----------

# check_code IMAGE DIR: are the libraries in IMAGE the ones the code in DIR needs?
check_code() {
  docker run --rm --network none -v "$2:/code:ro,z" --entrypoint python "$1" /opt/runtime/start.py --check /code
}

# selftest IMAGE CODEDIR SELFTEST_PY: boot the code in a throw-away container with no network
selftest() {
  local t=codingapp-selftest
  docker rm -f -v "$t" >/dev/null 2>&1 || true
  docker run -d --name "$t" --network none -v "$2:/code:ro,z" \
    -e ADMIN_PASSWORD=selftest-pass -e LLM_BASE_URL=http://127.0.0.1:9/v1 "$1" >/dev/null
  if ! docker exec -i "$t" python - < "$3"; then
    docker logs "$t" 2>&1 | tail -40
    docker rm -f -v "$t" >/dev/null 2>&1 || true
    return 1
  fi
  docker rm -f -v "$t" >/dev/null 2>&1 || true
}

# load_image DIR RUNTIME [IMAGE_ID]: docker load the runtime image file found in DIR (if needed)
load_image() {
  local dir="$1" rt="$2" want="${3:-}" img="codingapp-runtime:$2" file=""
  if image_present "$img" && { [ -z "$want" ] || [ "$(docker image inspect -f '{{.Id}}' "$img")" = "$want" ]; }; then
    info "Runtime image $img is already loaded."
    return
  fi
  for f in "$dir/codingapp-runtime-$rt.tar.gz" "$dir/codingapp-runtime-$rt.tar"; do [ -f "$f" ] && { file="$f"; break; }; done
  [ -n "$file" ] || die "Image file codingapp-runtime-$rt.tar(.gz) not found in $dir."
  info "Loading runtime image from $(basename "$file") (this can take a minute)"
  docker load -i "$file"
  image_present "$img" || die "Loading finished but $img is missing."
}

check_arch() {  # check_arch linux/amd64
  local arch; arch="$(docker version -f '{{.Server.Arch}}' 2>/dev/null || uname -m)"
  case "$arch" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; esac
  if [ -n "$1" ] && [ "linux/$arch" != "$1" ]; then
    die "This package was built for $1 but this server is linux/$arch. Rebuild with the matching platform."
  fi
  echo "   Architecture linux/$arch: ok"
}

# switch_code NEWDIR NEW_RUNTIME: stop, current code -> code.previous, NEWDIR -> code
switch_code() {
  cmd_stop
  rm -rf code.previous
  if [ -d code ]; then
    mv code code.previous
    runtime_version > code.previous/.runtime
  fi
  mv "$1" code
  chmod -R a+rX code
  env_set RUNTIME_VERSION "$2"
}

# start, verify the expected version, roll the code back if it fails
start_or_rollback() {
  local want="$1"
  if (cmd_start) && [ "$(health_version)" = "$want" ]; then
    return 0
  fi
  if [ -d code.previous ]; then
    warn "Version $want did not start correctly; rolling back to $(code_version code.previous)."
    do_rollback || true
    rm -rf code.previous   # the failed version; never roll "back" into it
    die "Rolled back. CodingApp runs $(code_version) again. Your data was not changed."
  fi
  die "Version $want did not start correctly (see above)."
}

do_rollback() {
  [ -d code.previous ] || die "Nothing to roll back to (no code.previous folder)."
  local prev_rt; prev_rt="$(cat code.previous/.runtime 2>/dev/null || runtime_version)"
  cmd_stop
  rm -f code.previous/.runtime
  rm -rf code.rollback
  mv code code.rollback
  mv code.previous code
  runtime_version > code.rollback/.runtime
  mv code.rollback code.previous
  env_set RUNTIME_VERSION "$prev_rt"
  cmd_start
}

cmd_rollback() {
  [ -f .env ] || die "Not installed in $HERE."
  [ -d code.previous ] || die "Nothing to roll back to (no code.previous folder)."
  info "Rolling back from $(code_version) to $(code_version code.previous)"
  do_rollback
  info "Now running $(code_version). (Run rollback again to return to $(code_version code.previous).)"
}

# add settings introduced by a newer version to .env (existing values are kept)
add_new_settings() {
  local key line
  while IFS= read -r line; do
    key="${line%%=*}"
    [[ "$line" =~ ^[A-Z_]+= ]] || continue
    grep -qE "^$key=" .env || { echo "$line" >> .env; echo "   added new setting $key"; }
  done < "$1"
  sed -i '/^APP_VERSION=/d' .env   # 1.0.0 setting; the version now comes from code/VERSION
}

# replace a file of this folder atomically (safe even for the running codingapp.sh)
put_file() { cp "$1" "$HERE/.$2.new" && mv -f "$HERE/.$2.new" "$HERE/$2"; }

# ---------- update: code package or full package ----------
cmd_update() {
  local pkg="${1:-}"
  [ -f "$pkg" ] || die "Usage: sudo ./codingapp.sh update /path/to/codingapp-code-<version>.tar.gz | codingapp-<version>-offline.tar.gz"
  [ -f .env ] && [ -d code ] || die "Not installed in $HERE yet: run  sudo bash install.sh  first."
  pkg="$(readlink -f "$pkg")"
  need_docker

  step "1/5 Unpack and verify $(basename "$pkg")"
  local tmp dir
  tmp="$(mktemp -d "$HERE/.update.XXXXXX")"
  trap 'rm -rf "$tmp"' EXIT
  tar -C "$tmp" -xzf "$pkg"
  dir="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n1)"
  [ -n "$dir" ] && [ -f "$dir/MANIFEST.txt" ] || die "Not a CodingApp package (MANIFEST.txt missing)."
  local kind newv rt
  kind="$(manifest_get kind "$dir/MANIFEST.txt")"
  newv="$(manifest_get version "$dir/MANIFEST.txt")"
  rt="$(manifest_get runtime "$dir/MANIFEST.txt")"
  [ "$kind" = "code" ] || [ "$kind" = "full" ] || die "Unknown package kind '$kind'."
  (cd "$dir" && sha256sum -c --quiet SHA256SUMS) || die "Checksum mismatch: the package was damaged during transfer."
  info "Package: $kind $newv, runtime $rt (installed: code $(code_version), runtime $(runtime_version))"
  if [ "$kind" = "full" ]; then
    check_arch "$(manifest_get arch "$dir/MANIFEST.txt")"
    load_image "$dir" "$rt" "$(manifest_get image_id "$dir/MANIFEST.txt")"
  fi
  local img="codingapp-runtime:$rt"
  image_present "$img" || die "This code needs runtime image $img, which is not on this server. Use the FULL package of this version."

  step "2/5 Compatibility check and offline self-test (production untouched)"
  chmod -R a+rX "$dir/code"
  check_code "$img" "$dir/code" || die "Not compatible with $img. Nothing was changed."
  selftest "$img" "$dir/code" "$dir/selftest.py" || die "Self-test failed. Nothing was changed."

  step "3/5 Backup"
  cmd_backup

  step "4/5 Switch code $(code_version) -> $newv"
  local prev_rt; prev_rt="$(runtime_version)"
  switch_code "$dir/code" "$rt"
  put_file "$dir/selftest.py" selftest.py
  [ -f "$dir/CHANGELOG.md" ] && put_file "$dir/CHANGELOG.md" CHANGELOG.md
  if [ "$kind" = "full" ]; then
    for f in codingapp.sh install.sh docker-compose.yml .env.example DEPLOY.md MANIFEST.txt SHA256SUMS; do
      [ -f "$dir/$f" ] && put_file "$dir/$f" "$f"
    done
    chmod +x codingapp.sh install.sh
    add_new_settings .env.example
    for f in "$dir"/codingapp-runtime-*.tar*; do [ -e "$f" ] && mv -f "$f" "$HERE/"; done
    for f in codingapp-runtime-*.tar*; do   # keep only the image files of the current and the rollback runtime
      case "$f" in codingapp-runtime-"$rt".tar*|codingapp-runtime-"$prev_rt".tar*) ;; *) rm -f "$f" ;; esac
    done
  fi

  step "5/5 Restart and verify"
  start_or_rollback "$newv"
  rm -rf "$tmp"; trap - EXIT
  echo
  info "${B}Updated to $newv.${N} Previous code kept in code.previous ($(code_version code.previous)); undo with: sudo ./codingapp.sh rollback"
}

# ---------- first install (in this folder) ----------
version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

preflight() {
  info "Pre-flight checks"
  need_docker
  local sv; sv="$(docker version -f '{{.Server.Version}}' 2>/dev/null || echo 0)"
  version_ge "${sv%%-*}" "20.10" || die "Docker $sv is too old; 20.10 or newer is required (host-gateway support)."
  echo "   Docker engine $sv: ok"
  check_arch "$BUNDLE_ARCH"
  detect_compose
  if [ ${#DC[@]} -gt 0 ]; then echo "   Compose: ${DC[*]}"; else warn "Docker Compose not found; plain 'docker run' will be used (fully supported)."; fi
  local avail
  avail="$(df -Pk "$HERE" 2>/dev/null | awk 'NR==2{print int($4/1024)}' || echo 0)"
  if [ "${avail:-0}" -gt 0 ] && [ "$avail" -lt 2048 ]; then
    warn "Only ${avail} MB free for $HERE; at least 2 GB is recommended."
  else
    echo "   Free space for $HERE: ${avail} MB"
  fi
}

new_secret() { docker run --rm --network none --entrypoint python "$(runtime_image)" -c "import secrets;print(secrets.token_urlsafe(48))"; }

configure_env() {
  local created=0
  if [ ! -f .env ]; then
    cp .env.example .env
    created=1
    info "Created .env from .env.example"
  else
    add_new_settings .env.example
  fi
  chmod 600 .env
  [ -n "$(env_get SECRET_KEY)" ] || { env_set SECRET_KEY "$(new_secret)"; echo "   generated SECRET_KEY"; }

  if [ "$created" = 1 ] && [ -t 0 ]; then
    local pw pw2 url
    echo
    while :; do
      read -r -s -p "Password for the built-in admin '$(env_get ADMIN_USERNAME admin)': " pw; echo
      [ ${#pw} -ge 8 ] || { warn "Use at least 8 characters."; continue; }
      [[ "$pw" != *'$'* && "$pw" != *'"'* && "$pw" != *"'"* && "$pw" != *' '* ]] || { warn "Please avoid \$, quotes and spaces (Docker Compose would alter them)."; continue; }
      read -r -s -p "Repeat password: " pw2; echo
      [ "$pw" = "$pw2" ] && break || warn "Passwords do not match."
    done
    env_set ADMIN_PASSWORD "$pw"
    read -r -p "Web port [$(env_get APP_PORT 8090)]: " url
    [ -n "$url" ] && env_set APP_PORT "$url"
    read -r -p "vLLM URL [$(env_get LLM_BASE_URL)]: " url
    [ -n "$url" ] && env_set LLM_BASE_URL "$url"
    read -r -p "vLLM API key [$(env_get LLM_API_KEY EMPTY)]: " url
    [ -n "$url" ] && env_set LLM_API_KEY "$url"
  fi

  local pw; pw="$(env_get ADMIN_PASSWORD)"
  if [ -z "$pw" ] || [ "$pw" = "change-me" ]; then
    die "Edit $HERE/.env: set ADMIN_PASSWORD (and check APP_PORT, LLM_BASE_URL), then run  sudo bash install.sh  again."
  fi
  [ -n "$(env_get LLM_BASE_URL)" ] || die "LLM_BASE_URL is empty in $HERE/.env."
}

check_port() {
  local port; port="$(env_get APP_PORT 8090)"
  container_running && return 0   # our own container holds the port (re-install / upgrade from 1.0.0)
  if command -v ss >/dev/null 2>&1 && ss -Hltn "sport = :$port" 2>/dev/null | grep -q .; then
    ss -Hltnp "sport = :$port" 2>/dev/null | sed 's/^/   in use: /' || true
    die "Port $port is already in use on this server. Set another APP_PORT in $HERE/.env, then run  sudo bash install.sh  again."
  fi
}

cmd_install() {
  [ $# -eq 0 ] || die "install takes no options: CodingApp is installed in this folder ($HERE)."
  [ "$BUNDLE_KIND" = "full" ] || die "Run install.sh from an extracted FULL package (MANIFEST.txt with kind=full)."
  local first=1; [ -f .installed ] && first=0
  chmod +x codingapp.sh install.sh 2>/dev/null || true   # lost if the package was packed on Windows
  echo "${B}CodingApp $(code_version) (runtime $BUNDLE_RUNTIME): offline install in $HERE${N}"

  step "1/7 Pre-flight"
  preflight
  if [ "$first" = 1 ]; then
    (sha256sum -c --quiet SHA256SUMS) || die "Checksum mismatch: the package was damaged during transfer."
    echo "   Package checksums: ok"
  fi
  if [ -f .env ] && [ -z "$(env_get RUNTIME_VERSION)" ]; then env_set RUNTIME_VERSION "$BUNDLE_RUNTIME"; fi

  step "2/7 Runtime image"
  load_image "$HERE" "$(runtime_version)"
  local img; img="$(runtime_image)"

  step "3/7 Compatibility check and offline self-test (nothing running is touched)"
  chmod -R a+rX code
  check_code "$img" "$HERE/code" || die "The code does not match the runtime image."
  selftest "$img" "$HERE/code" "$HERE/selftest.py" || die "Self-test failed. Nothing was changed."

  step "4/7 Settings ($HERE/.env)"
  if [ ! -f .env ]; then
    # upgrading from 1.0.0 (its own folder)? take its settings over
    local old
    old="$(docker container inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$CONTAINER" 2>/dev/null || true)"
    for d in "$old" "$HERE/../codingapp-1.0.0"; do
      if [ -n "$d" ] && [ -f "$d/.env" ] && [ "$(cd "$d" && pwd)" != "$HERE" ]; then
        cp -p "$d/.env" .env
        info "Settings taken over from the previous installation: $d/.env"
        break
      fi
    done
  fi
  configure_env
  [ "$first" = 1 ] && env_set RUNTIME_VERSION "$BUNDLE_RUNTIME"
  info "Using port $(env_get APP_PORT 8090), vLLM $(env_get LLM_BASE_URL)"
  check_port

  step "5/7 Data ($HERE/data)"
  local legacy=0
  if container_running; then
    cmd_backup                                       # safety copy of whatever is running now
  fi
  if [ ! -f data/codingapp.db ] && docker volume inspect "$OLD_VOLUME" >/dev/null 2>&1; then
    legacy=1
    info "Copying the data of the previous version (Docker volume $OLD_VOLUME) into $HERE/data"
    cmd_stop
    mkdir -p data
    docker run --rm --user 0 --network none -v "$OLD_VOLUME:/from:ro" -v "$HERE/data:/to:z" --entrypoint sh "$img" \
      -c "cp -a /from/. /to/ && chown -R $APP_UID /to"
    [ -f data/codingapp.db ] || die "Copying the data failed. The previous version's data is untouched in volume $OLD_VOLUME."
    echo "   copied (the volume $OLD_VOLUME itself is left untouched)"
  elif [ -f data/codingapp.db ]; then
    echo "   existing data kept"
  else
    echo "   new, empty database"
  fi

  step "6/7 vLLM connection"
  if ! cmd_check_llm; then
    warn "The LLM is not reachable yet. CodingApp will start anyway; fix LLM_BASE_URL in .env and run ./codingapp.sh restart."
  fi

  step "7/7 Start"
  if ! (cmd_stop && cmd_start); then
    [ "$legacy" = 1 ] && warn "To go back to 1.0.0: cd to its folder and run  sudo bash install.sh  (its data is untouched)."
    die "CodingApp did not start (see above)."
  fi
  date -u +"installed=%Y-%m-%dT%H:%M:%SZ version=$(code_version)" > .installed
  echo
  info "${B}CodingApp $(code_version) is installed in $HERE${N}"
  info "Sign in as '$(env_get ADMIN_USERNAME admin)'. Configure Active Directory under Administration -> Directory (LDAP)."
  info "Manage with:  cd $HERE && sudo ./codingapp.sh status | logs | restart | update | rollback | backup"
  if [ "$legacy" = 1 ]; then
    echo "   1.0.0 leftovers, remove once you are happy:  docker image rm codingapp:1.0.0 ; docker volume rm $OLD_VOLUME"
  fi
}

case "${1:-}" in
  install)   shift; cmd_install "$@" ;;
  update)    shift; cmd_update "${1:-}" ;;
  rollback)  cmd_rollback ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  restart)   cmd_stop; cmd_start ;;
  status)    cmd_status ;;
  version)   cmd_version ;;
  logs)      shift; cmd_logs "${1:-200}" ;;
  check-llm) cmd_check_llm ;;
  backup)    cmd_backup ;;
  restore)   shift; cmd_restore "${1:-}" ;;
  uninstall) shift; cmd_uninstall "${1:-}" ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
