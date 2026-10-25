ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip poppler-utils \
 && pip install --no-cache-dir --break-system-packages paho-mqtt websocket-client

WORKDIR /opt/gpk_water
COPY app ./app
COPY config.yaml ./config.yaml
CMD ["python3", "-m", "app.main"]
