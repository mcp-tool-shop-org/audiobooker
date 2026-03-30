# Pin to Debian Bookworm slim; bump tag deliberately when upgrading Python.
FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY audiobooker/ audiobooker/
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Install core + dev extras only. The [render] extra requires voice-soundboard
# which is NOT on PyPI — mount it via a volume or install it separately at
# runtime (e.g. from a local wheel or git clone).
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir '.[dev]'

# Pin to same slim tag as builder.
FROM python:3.11-slim
# FFmpeg version is provided by Debian stable (bookworm); no separate pin needed.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN useradd -r -s /bin/false audiobooker
WORKDIR /home/audiobooker
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# /data — working directory for input books and output audiobooks.
# /ext — optional mount point for extra packages (e.g. voice-soundboard wheel).
VOLUME /data
VOLUME /ext

HEALTHCHECK CMD audiobooker --help || exit 1

USER audiobooker
ENTRYPOINT ["audiobooker"]
CMD ["--help"]
