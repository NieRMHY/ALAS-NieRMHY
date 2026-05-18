# ARM64 Dockerfile for AzurLaneAutoScript
# Build: docker build -t alas-arm64 -f dev_tools/arm64/Dockerfile .
# Run:   docker run -v ${PWD}:/app/AzurLaneAutoScript -p 22267:22267 --name alas -it --rm alas-arm64

FROM python:3.14-slim-bookworm

WORKDIR /app/AzurLaneAutoScript

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY deploy/docker/requirements.txt /tmp/requirements.txt

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        adb \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        openssh-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN git config --global --add safe.directory '*'

RUN uv pip install --system --upgrade pip && \
    uv pip install --system -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt && \
    rm -rf /root/.cache/uv

CMD ["python", "gui.py"]
