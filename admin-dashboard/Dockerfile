FROM node:22-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV DASHBOARD_BASE_PATH=/wissen
RUN npm run build

ENV HOST=0.0.0.0
ENV PORT=3000
ENV WRANGLER_LOG_PATH=/tmp/wrangler.log
EXPOSE 3000

USER node

CMD ["npx", "vinext", "start", "--host", "0.0.0.0"]

