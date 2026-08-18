FROM sports-intelligence-os-api:latest

USER root

RUN set -eu; \
    printf 'Acquire::Retries "5";\nAcquire::http::Timeout "120";\n' \
      > /etc/apt/apt.conf.d/80-sio-retries; \
    attempt=1; \
    until apt-get update; do \
      if [ "$attempt" -ge 5 ]; then exit 1; fi; \
      attempt=$((attempt + 1)); \
      sleep 2; \
    done; \
    attempt=1; \
    until apt-get install -y --no-install-recommends --fix-missing novnc websockify x11vnc xvfb; do \
      if [ "$attempt" -ge 5 ]; then exit 1; fi; \
      attempt=$((attempt + 1)); \
      apt-get update; \
      sleep 2; \
    done; \
    rm -rf /var/lib/apt/lists/*

COPY scripts/run_docker_browser.py /workspace/scripts/run_docker_browser.py
COPY scripts/cdp_proxy.py /workspace/scripts/cdp_proxy.py
RUN chown sio:sio /workspace/scripts/run_docker_browser.py /workspace/scripts/cdp_proxy.py

USER sio
