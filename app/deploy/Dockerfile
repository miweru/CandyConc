# CandyConc server image.
#
# Build context is the app directory, with the web interface already built into
# the package (python packaging/build_web.py writes src/candyconc/web_dist):
#
#   python packaging/build_web.py
#   docker build -f app/deploy/Dockerfile -t candyconc app
#
# Run (data volume, first create users, then start):
#   docker run --rm -it -v candyconc-data:/data candyconc \
#     python -m candyconc.tools.user_bootstrap --username admin --role admin
#   docker run -d -p 127.0.0.1:8010:8010 -v candyconc-data:/data candyconc
#
# The image runs in release security mode with role-based access control.
# Behind a reverse proxy with its own host name, set CANDYCONC_TRUSTED_HOSTS.
# The copilot is optional: set COPILOT_ENDPOINT and COPILOT_MODEL to enable it.

FROM python:3.11-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    CANDYCONC_ENABLE_OPENMP=off \
    CANDYCONC_REQUIRE_WEB_DIST=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY pyproject.toml setup.py setup_native.py MANIFEST.in README.md LICENSE requirements.txt ./
COPY src ./src
RUN python -m pip install --upgrade pip build \
    && python -m build --wheel --outdir /wheels .

FROM python:3.11-slim

ARG CANDYCONC_ENABLE_RBAC=1
ARG CANDYCONC_SECURITY_MODE=release

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CANDYCONC_ENABLE_OPENMP=off \
    CANDYCONC_ENABLE_RBAC=${CANDYCONC_ENABLE_RBAC} \
    CANDYCONC_SECURITY_MODE=${CANDYCONC_SECURITY_MODE} \
    CANDYCONC_HOME=/data \
    CANDYCONC_USER_FILE=/data/users.json

COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/candyconc-*.whl \
    && rm -rf /wheels \
    && useradd --system --home-dir /data --shell /usr/sbin/nologin candyconc \
    && mkdir -p /data \
    && chown candyconc:candyconc /data

USER candyconc
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/v1/health', timeout=3).read()"

CMD ["candy", "--host", "0.0.0.0", "--port", "8010"]
