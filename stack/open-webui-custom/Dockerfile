# syntax=docker/dockerfile:1

ARG OPEN_WEBUI_VERSION=v0.11.0
ARG OPEN_WEBUI_REVISION=f9590b8017199e56d5e953657e6498e3cef1d246

FROM node:22-alpine3.20 AS frontend
ARG OPEN_WEBUI_VERSION
ARG OPEN_WEBUI_REVISION

RUN apk add --no-cache git
WORKDIR /src
RUN git clone --depth 1 --branch "${OPEN_WEBUI_VERSION}" https://github.com/open-webui/open-webui.git . \
    && test "$(git rev-parse HEAD)" = "${OPEN_WEBUI_REVISION}"

COPY stack/open-webui-custom/sidebar-wissensportal.patch /tmp/sidebar-wissensportal.patch
RUN git apply --check /tmp/sidebar-wissensportal.patch \
    && git apply /tmp/sidebar-wissensportal.patch

RUN npm ci --force
ENV NODE_OPTIONS="--max-old-space-size=8192"
RUN npm run build

FROM ghcr.io/open-webui/open-webui:v0.11.0
ENV WEBUI_NAME="KAHLE-Vinci"
COPY --from=frontend /src/build /app/build

COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/favicon.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/favicon-96x96.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/apple-touch-icon.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/web-app-manifest-192x192.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/web-app-manifest-512x512.png
COPY stack/open-webui-custom/patch_branding.py /tmp/patch_branding.py
RUN python /tmp/patch_branding.py \
      --index /app/build/index.html \
      --env /app/backend/open_webui/env.py \
    && rm /tmp/patch_branding.py

LABEL org.opencontainers.image.title="KAHLE OpenWebUI"
LABEL org.opencontainers.image.version="0.11.0-kahle.2"
LABEL de.kahle.open-webui.base-revision="f9590b8017199e56d5e953657e6498e3cef1d246"
LABEL de.kahle.open-webui.customization="Wissensportal-Link, KAHLE-Vinci-Name und Favicon"
