# Compila React y lo sirve con Nginx, que además termina HTTPS y
# reenvía /api, /admin y /static a Django.
FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# Imagen Debian: ya incluye openssl para el certificado autofirmado.
FROM nginx:1.27
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY certificado.sh /docker-entrypoint.d/05-certificado.sh
RUN chmod +x /docker-entrypoint.d/05-certificado.sh
EXPOSE 80 443
