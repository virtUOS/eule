# Widget image — builds the single self-contained widget.js and serves it as static
# files (docs/07-deployment.md). Decoupled from the gateway and the proxy: it can be
# swapped for a self-hosted S3/object store later with no gateway change.
FROM node:24-alpine AS build
WORKDIR /w
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build   # tsc --noEmit && vite build → dist/widget.js

FROM nginx:alpine
# The built bundle (widget.js) + a production standalone page that loads /widget.js.
COPY --from=build /w/dist /usr/share/nginx/html
COPY deploy/ /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
