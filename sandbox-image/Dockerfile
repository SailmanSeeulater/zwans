# The default image the Docker executor runs commands in: Python, git, ripgrep, curl, pytest.
# Build: docker build -t zwans-sandbox:0.1 sandbox-image
FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
CMD ["sleep", "infinity"]
