# Pin to Debian Bookworm slim; bump tag deliberately when upgrading Python.
# Digest-pinned (not just tag-pinned) so two builds of the same commit can't
# silently pull different bytes under the mutable `3.11-slim` tag. This is
# the multi-arch index digest for `python:3.11-slim` on Docker Hub, resolved
# 2026-09-14 via the registry API — re-resolve and bump both FROM lines
# together on each deliberate Python/base-image bump (see comment above).
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY audiobooker/ audiobooker/
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Install core only (keeps the image slim). voice-soundboard (the TTS engine the
# `render` command needs) is on PyPI but pulls heavy ML deps, so it is left out
# by design — add it at runtime with `pip install voice-soundboard`, or mount a
# wheel at /ext. Everything except `render` works in this image as-is.
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir '.'

# Pin to same slim digest as builder.
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
# FFmpeg version is provided by Debian stable (bookworm); no separate pin needed.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# Explicit UID/GID (not left to useradd's default allocation) so an operator
# who chowns a bind-mounted /data to match this user gets a value that is
# stable across rebuilds instead of whatever the next free system UID is.
RUN groupadd -r -g 1000 audiobooker && useradd -r -u 1000 -g audiobooker -s /bin/false audiobooker
WORKDIR /home/audiobooker
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK CMD audiobooker --help || exit 1

USER audiobooker

# CH-B-004 (wave 5 amend): VOLUME must come AFTER USER, not before. VOLUME
# creates the mount-point directory at build time if it doesn't already
# exist (Dockerfile reference: "The VOLUME instruction creates a mount point
# ... and marks it as holding externally mounted volumes"), and that create
# happens as whichever user is active at that point in the build -- the same
# rule as a plain `RUN mkdir`. With VOLUME declared before `USER
# audiobooker`, /data and /ext were created while still root, baking
# root:root, mode-755 directories into the image layer: root can write,
# audiobooker (group "other" under that mode) can only read/traverse.
#
# That ownership then matters for exactly the case Docker documents:
# "The docker run command initializes the newly created volume with any
# data that exists at the specified location within the base image" --
# i.e. a fresh named volume, or the anonymous volume Docker creates for a
# VOLUME-declared path with no explicit -v/--mount, is seeded by copying the
# image's own directory at that path, ownership included. So any `docker
# run` of this image that does NOT bind-mount /data (no `-v host:/data`) got
# a /data the non-root audiobooker process cannot write to -- a real break,
# since /data is documented two lines below as "working directory for input
# books and OUTPUT audiobooks". The documented, recommended usage pattern
# (an operator bind-mounts and chowns a host directory to this image's fixed
# UID 1000, per the comment above USER) is unaffected either way -- a bind
# mount's host-side permissions fully shadow the image's own directory --
# but the image should not be silently broken for the un-mounted/named-volume
# case, and shouldn't bake root-owned paths under a non-root image regardless.
#
# /data — working directory for input books and output audiobooks.
# /ext — optional mount point for extra packages (e.g. voice-soundboard wheel).
VOLUME /data
VOLUME /ext

ENTRYPOINT ["audiobooker"]
CMD ["--help"]
