FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# Docker CLI only (talks to the host daemon via the mounted socket) for the sandbox.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

COPY pyproject.toml ./
COPY app ./app
COPY config ./config
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 1000 agent \
    && mkdir -p /srv/data && chown -R agent:agent /srv/data /srv/config

USER agent
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
