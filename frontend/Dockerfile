FROM node:20-alpine AS build

WORKDIR /app

# VITE_API_URL is baked in at build time (browser-side var).
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Use nginx's built-in envsubst-on-templates so the listen port can come from
# the environment. PORT defaults to 80 (docker-compose maps to it); Railway and
# similar hosts inject their own. The filter limits substitution to PORT so
# nginx's own $uri directives are not touched.
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV PORT=80
ENV NGINX_ENVSUBST_FILTER=PORT
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
