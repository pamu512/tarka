# Determinate Nix installer (https://github.com/DeterminateSystems/nix-installer). There is no
# smaller "nix-installer-only" image maintained for devcontainers; this layer bakes the installer.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    acl \
    bash \
    ca-certificates \
    curl \
    git \
    procps \
    sudo \
    xz-utils \
  && rm -rf /var/lib/apt/lists/*

# GitHub Codespaces-style /tmp default ACLs can break multi-user Nix; strip default ACLs when present.
RUN sh -c 'command -v setfacl >/dev/null && setfacl -k /tmp || true'

# Pinned installer tag for reproducibility; bump intentionally when upgrading Nix.
ARG DETERMINATE_INSTALLER_TAG=v3.18.1
RUN curl --proto '=https' --tlsv1.2 -sSf -L "https://install.determinate.systems/nix/tag/${DETERMINATE_INSTALLER_TAG}" \
    | sh -s -- install linux \
      --extra-conf "sandbox = false" \
      --extra-conf "filter-syscalls = false" \
      --extra-conf "experimental-features = nix-command flakes" \
      --init none \
      --no-confirm

ENV PATH="/nix/var/nix/profiles/default/bin:${PATH}"

RUN printf '%s\n' \
      'if [ -f /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]; then' \
      '  . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh' \
      'fi' \
    >> /etc/bash.bashrc
