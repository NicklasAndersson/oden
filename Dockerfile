# Oden - Signal to Obsidian bridge
# Multi-arch Docker image (linux/amd64, linux/arm64)

FROM python:3.12-slim AS base

# Install Temurin JRE 21 (required by signal-cli)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        wget \
        apt-transport-https \
        gnupg \
        ca-certificates && \
    # Add Adoptium repository
    wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(. /etc/os-release && echo $VERSION_CODENAME) main" \
        > /etc/apt/sources.list.d/adoptium.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends temurin-21-jre && \
    # Cleanup
    apt-get purge -y wget gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Download and install signal-cli
ARG SIGNAL_CLI_VERSION=0.13.23
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -sL "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz" \
        | tar -xz -C /opt && \
    mv /opt/signal-cli-${SIGNAL_CLI_VERSION} /opt/signal-cli && \
    chmod +x /opt/signal-cli/bin/signal-cli && \
    ln -s /opt/signal-cli/bin/signal-cli /usr/local/bin/signal-cli && \
    apt-get purge -y curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Set up application
WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY pyproject.toml README.md ./
COPY oden/ oden/
COPY templates/ templates/
COPY config.ini ./

RUN pip install --no-cache-dir .

# Data and vault volumes
# /data — Oden config (config.db, signal-data)
# /vault — Obsidian vault where reports are saved
VOLUME ["/data", "/vault"]

# Environment: ODEN_HOME controls where config.db and signal-data live
# WEB_HOST=0.0.0.0 so the web GUI is reachable from outside the container
ENV ODEN_HOME=/data \
    WEB_HOST=0.0.0.0

EXPOSE 8080

ENTRYPOINT ["python", "-m", "oden"]
