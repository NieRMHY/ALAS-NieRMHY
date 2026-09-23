# docker build -t hgjazhgj/alas:latest .
# docker run -v ${PWD}:/app/AzurPilot -p 25548:25548 --name AzurPilot -it --rm hgjazhgj/alas

FROM node:24-bookworm-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim-bookworm

ARG UV_INDEX_URL=https://pypi.org/simple
ARG UV_EXTRA_INDEX_URL=
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG NO_PROXY=127.0.0.1,localhost

ENV UV_INDEX_URL=${UV_INDEX_URL}
ENV UV_EXTRA_INDEX_URL=${UV_EXTRA_INDEX_URL}
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV no_proxy=${NO_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV PATH=/app/AzurPilot/.venv/bin:${PATH}

WORKDIR /app/AzurPilot

COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-build /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./

RUN if [ -n "$HTTP_PROXY" ]; then \
    printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$HTTP_PROXY" "$HTTPS_PROXY" > /etc/apt/apt.conf.d/99proxy; \
    fi

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

RUN git config --global --add safe.directory '*' && \
    if [ -n "$HTTP_PROXY" ]; then \
        git config --global http.proxy "$HTTP_PROXY" && \
        git config --global https.proxy "$HTTPS_PROXY"; \
    fi

RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    node --version && \
    npm --version && \
    uv venv --relocatable --python /usr/local/bin/python .venv && \
    uv sync --frozen --no-dev --no-install-project && \
    cp /usr/local/bin/uv .venv/bin/uv && \
    cp /usr/bin/adb .venv/bin/adb && \
    cp /usr/bin/git .venv/bin/git && \
    rm -rf /root/.cache/uv

COPY . .
COPY --from=frontend-build /frontend/dist ./frontend/dist
RUN .venv/bin/python -c "from pathlib import Path; from deploy.frontend import source_fingerprint; p=Path('frontend'); (p/'dist/.source-fingerprint').write_text(source_fingerprint(p))"

CMD [".venv/bin/python", "gui.py"]
