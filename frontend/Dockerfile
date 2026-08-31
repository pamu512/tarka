FROM node:20-alpine AS build
RUN apk upgrade --no-cache
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
# Baked into the UI for regional AI governance banners (us | eu_uk | global).
ARG VITE_AI_GOVERNANCE_PROFILE=global
ENV VITE_AI_GOVERNANCE_PROFILE=${VITE_AI_GOVERNANCE_PROFILE}
# Production default: lean nav (no brochure Command Center / ingress demo routes).
# Sales demo image: --build-arg VITE_LEAN_NAV=false
ARG VITE_LEAN_NAV=true
ENV VITE_LEAN_NAV=${VITE_LEAN_NAV}
# Desk-strict: case/calibration/QA never auto-mock (missed-mark bridge)
ARG VITE_DESK_STRICT=true
ENV VITE_DESK_STRICT=${VITE_DESK_STRICT}
ARG VITE_USE_API_MOCKS=false
ENV VITE_USE_API_MOCKS=${VITE_USE_API_MOCKS}
# Empty Advise/signals URL = plane off. Empty graph URL → home /decisions (not the product default).
ARG VITE_GRAPH_SERVICE_URL=
ENV VITE_GRAPH_SERVICE_URL=${VITE_GRAPH_SERVICE_URL}
ARG VITE_INVESTIGATION_AGENT_URL=
ENV VITE_INVESTIGATION_AGENT_URL=${VITE_INVESTIGATION_AGENT_URL}
ARG VITE_SIGNAL_API_URL=
ENV VITE_SIGNAL_API_URL=${VITE_SIGNAL_API_URL}
RUN npm run build

FROM nginx:alpine
RUN apk upgrade --no-cache
COPY --from=build /app/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
