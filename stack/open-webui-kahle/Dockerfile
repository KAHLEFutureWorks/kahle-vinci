ARG OPEN_WEBUI_BASE_IMAGE=ghcr.io/open-webui/open-webui:v0.9.2
FROM ${OPEN_WEBUI_BASE_IMAGE}

COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/kahle/logo.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/logo.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/favicon.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/favicon-96x96.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/web-app-manifest-192x192.png
COPY public/logo/KAHLE-Vinci-Logo.png /app/build/static/web-app-manifest-512x512.png
COPY public/background/Logo_Kahle_Gruppe_positiv.jpg /app/build/static/kahle/chat-background.jpg
COPY stack/open-webui-kahle/static/kahle-branding.css /app/build/static/kahle/kahle-branding.css
COPY stack/open-webui-kahle/static/kahle-branding.js /app/build/static/kahle/kahle-branding.js
COPY stack/open-webui-kahle/patch_openwebui.py /tmp/patch_openwebui.py

RUN python /tmp/patch_openwebui.py \
      --index /app/build/index.html \
      --env /app/backend/open_webui/env.py \
    && rm /tmp/patch_openwebui.py
