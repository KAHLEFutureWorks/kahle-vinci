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

COPY sidebar-wissensportal.patch /tmp/sidebar-wissensportal.patch
RUN git apply --check /tmp/sidebar-wissensportal.patch \
    && git apply /tmp/sidebar-wissensportal.patch

RUN npm ci --force
ENV NODE_OPTIONS="--max-old-space-size=8192"
RUN npm run build

FROM ghcr.io/open-webui/open-webui:v0.11.0
COPY --from=frontend /src/build /app/build

LABEL org.opencontainers.image.title="KAHLE OpenWebUI"
LABEL org.opencontainers.image.version="0.11.0-kahle.1"
LABEL de.kahle.open-webui.base-revision="f9590b8017199e56d5e953657e6498e3cef1d246"
LABEL de.kahle.open-webui.customization="Wissensportal-Link in der Sidebar"
