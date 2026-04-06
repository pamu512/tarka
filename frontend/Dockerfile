FROM node:20-alpine AS build
RUN apk upgrade --no-cache
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
# Baked into the UI for regional AI governance banners (us | eu_uk | global).
ARG VITE_AI_GOVERNANCE_PROFILE=global
ENV VITE_AI_GOVERNANCE_PROFILE=${VITE_AI_GOVERNANCE_PROFILE}
RUN npm run build

FROM nginx:alpine
RUN apk upgrade --no-cache
COPY --from=build /app/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
