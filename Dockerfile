# CodingApp. Built on a machine WITH internet; nothing is downloaded at runtime.
#
# The RUNTIME image holds only Python + libraries + the start script. The application code
# (backend + built UI) is NOT in the image: it lives in the install folder on the server
# (./code) and is mounted read-only at /code. Code updates therefore need no new image,
# unless backend/requirements.txt changes (then bump RUNTIME_VERSION and ship a full package).
#
#   docker build --target web .                   -> builds the web UI (dist copied out by the build script)
#   docker build --target test .                  -> runs the backend tests on the runtime
#   docker build -t codingapp-runtime:1 .         -> runtime image (default target)

# ---------- 1) web UI build (output copied out, never shipped as an image) ----------
FROM node:20.18.0-alpine3.20 AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build \
 && ! grep -Eq '(src|href)="https?://' dist/index.html   # fail if the UI references external assets

# ---------- 2) runtime: Python + libraries only ----------
FROM python:3.11.10-slim-bookworm AS runtime
ARG RUNTIME_VERSION=1
LABEL org.opencontainers.image.title="codingapp-runtime" \
      org.opencontainers.image.version="${RUNTIME_VERSION}" \
      org.opencontainers.image.description="Runtime for CodingApp; the application code is mounted at /code"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    CODE_DIR=/code \
    STATIC_DIR=/code/static \
    RUNTIME_VERSION=${RUNTIME_VERSION}

WORKDIR /opt/runtime
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY docker/start.py ./start.py

RUN useradd --system --uid 10001 --home /opt/runtime codingapp \
 && mkdir -p /data /code \
 && chown -R codingapp /data
USER codingapp
WORKDIR /code

VOLUME ["/data"]
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/health', timeout=5)" || exit 1

CMD ["python", "/opt/runtime/start.py"]

# ---------- 3) tests (build-time only, never shipped) ----------
FROM runtime AS test
USER root
RUN pip install --no-cache-dir pytest==8.3.3
COPY backend/app /code/app
COPY backend/tests /code/tests
COPY backend/requirements.txt /code/requirements.txt
RUN chown -R codingapp /code
USER codingapp
RUN python /opt/runtime/start.py --check /code \
 && DATA_DIR=/tmp/codingapp-test python -m pytest -q -p no:cacheprovider tests

# ---------- 4) runtime image (default target) ----------
FROM runtime AS release
