# Oden - Signal to Obsidian bridge
# Multi-arch Docker image (linux/amd64, linux/arm64)

FROM python:3.12-slim AS base

# Install Temurin JRE 25 (required by signal-cli 0.14.x)
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
    apt-get install -y --no-install-recommends temurin-25-jre && \
    # Cleanup
    apt-get purge -y wget gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Download and install signal-cli
ARG SIGNAL_CLI_VERSION=0.14.5
ARG LIBSIGNAL_CLIENT_VERSION=0.94.4
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

# Fix: upstream signal-cli JAR lacks libsignal_jni.so for Linux ARM64.
# Download pre-built native library and inject it into the JAR.
# Source: https://github.com/bbernhard/libsignal-client-builds
RUN if [ "$(dpkg --print-architecture)" = "arm64" ]; then \
        python3 -c "\
import urllib.request, tarfile, zipfile, os; \
url = 'https://github.com/bbernhard/libsignal-client-builds/releases/download/v${LIBSIGNAL_CLIENT_VERSION}/libsignal-client-build-v${LIBSIGNAL_CLIENT_VERSION}.tar.gz'; \
tar_path = '/tmp/libsignal-builds.tar.gz'; \
so = '/tmp/libsignal_jni.so'; \
jar = '/opt/signal-cli/lib/libsignal-client-${LIBSIGNAL_CLIENT_VERSION}.jar'; \
urllib.request.urlretrieve(url, tar_path); \
tf = tarfile.open(tar_path); \
member = tf.getmember('arm64/libsignal_jni.so'); \
src = tf.extractfile(member); \
data = src.read(); \
src.close(); \
tf.close(); \
open(so, 'wb').write(data); \
os.remove(tar_path); \
zf = zipfile.ZipFile(jar, 'a'); \
zf.write(so, 'libsignal_jni.so'); \
zf.close(); \
os.remove(so); \
print('Injected libsignal_jni.so for arm64')"; \
    fi

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
