{
  description = "Tarka — Rust + Python dev shell with local DB services (process-compose + services-flake)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    rust-overlay = {
      url = "github:oxalica/rust-overlay";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    process-compose-flake = {
      url = "github:Platonic-Systems/process-compose-flake";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    services-flake = {
      url = "github:juspay/services-flake";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];

      imports = [ inputs.process-compose-flake.flakeModule ];

      perSystem =
        { config, pkgs, self', ... }:
        let
          system = pkgs.stdenv.hostPlatform.system;

          # rust-overlay applies only where `rust-bin` is needed (devShell); DB services use stock nixpkgs.
          pkgsRust = import inputs.nixpkgs {
            inherit system;
            overlays = [ inputs.rust-overlay.overlays.default ];
            config = { };
          };

          rustToolchain = pkgsRust.rust-bin.stable.latest.default.override {
            extensions = [ "clippy" ];
          };

          nativeLibs = pkgs.lib.makeLibraryPath [
            pkgs.stdenv.cc.cc.lib
            pkgs.openssl.out
            pkgs.zlib
            rustToolchain
          ];

          exportLdHook = ''
            export LD_LIBRARY_PATH="${nativeLibs}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
          '';

          exportDyldHook = pkgs.lib.optionalString pkgs.stdenv.isDarwin ''
            export DYLD_LIBRARY_PATH="${nativeLibs}''${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
          '';

          # Detached process-compose (F1bonacc1/process-compose `up -D`).
          startLocalDbs = ''
            if [[ -z "''${TARKA_SKIP_LOCAL_DB:-}" ]]; then
              echo "[devshell] Starting Postgres 15, Redis, ClickHouse, Loki, Promtail (process-compose, detached)…"
              if ! command -v tarka_dbs >/dev/null 2>&1; then
                echo "[devshell] tarka_dbs not on PATH; skipping local databases." >&2
              elif ! tarka_dbs up -D; then
                echo "[devshell] WARNING: process-compose up -D failed (ports in use?). Shell continues; fix or set TARKA_SKIP_LOCAL_DB=1." >&2
              fi
            fi
            export TARKA_LOKI_PUSH_URL="''${TARKA_LOKI_PUSH_URL:-http://127.0.0.1:3100/loki/api/v1/push}"
          '';
        in
        {
          process-compose.tarka_dbs =
            { pkgs, ... }:
            {
              imports = [ inputs.services-flake.processComposeModules.default ];

              services.postgres.pg15 = {
                enable = true;
                package = pkgs.postgresql_15;
                listen_addresses = "127.0.0.1";
                port = 5432;
                initialDatabases = [
                  { name = "tarka"; }
                ];
              };

              # Upstream Redis from nixpkgs (7.x on unstable). Docker redis:7-alpine image is not reproduced in Nix.
              services.redis.redis7 = {
                enable = true;
                package = pkgs.redis;
                bind = "127.0.0.1";
                port = 6379;
              };

              services.clickhouse.ch = {
                enable = true;
                package = pkgs.clickhouse;
              };

              settings.processes.loki = {
                command = "${pkgs.grafana-loki}/bin/loki -config.file ${./infrastructure/loki/loki-local.yaml}";
              };
              settings.processes.promtail = {
                command = "${pkgs.promtail}/bin/promtail -config.file ${./infrastructure/loki/promtail-local.yaml}";
                depends_on."loki".condition = "process_started";
              };
            };

          devShells.default = pkgs.mkShell {
            name = "tarka";

            inputsFrom = [
              config.process-compose.tarka_dbs.services.outputs.devShell
            ];

            packages = [
              self'.packages.tarka_dbs
              rustToolchain
              pkgs.cargo-edit
              pkgs.cargo-watch
              (pkgs.python311.withPackages (
                ps: with ps; [
                  poetry-core
                ]
              ))
              pkgs.poetry
              pkgs.postgresql_15
              pkgs.redis
              pkgs.clickhouse
              pkgs.grafana-loki
              pkgs.promtail
            ];

            shellHook = exportLdHook + exportDyldHook + startLocalDbs;
          };
        };
    };
}
