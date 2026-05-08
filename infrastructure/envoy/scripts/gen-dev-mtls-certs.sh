#!/usr/bin/env bash
# Generate a self-signed "Tarka Development CA" and an Envoy leaf usable as both server and client
# cert (EKU serverAuth + clientAuth). Output: infrastructure/envoy/certs/dev/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/certs/dev"
mkdir -p "${OUT}"
cd "${OUT}"

if [[ -f ca.pem && -f envoy.pem && -f envoy-key.pem ]]; then
  echo "Certs already exist in ${OUT}; remove files to regenerate."
  exit 0
fi

openssl genrsa -out ca-key.pem 4096
openssl req -new -x509 -days 3650 -key ca-key.pem -out ca.pem \
  -subj "/CN=Tarka Development CA/O=Tarka Dev/OU=Platform"

openssl genrsa -out envoy-key.pem 2048
openssl req -new -key envoy-key.pem -out envoy.csr \
  -subj "/CN=envoy-sidecar.local/O=Tarka Dev/OU=Mesh"

cat > openssl-v3.ext <<'EOF'
subjectAltName=DNS:localhost,DNS:envoy-sidecar.local,IP:127.0.0.1
extendedKeyUsage=serverAuth,clientAuth
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
EOF

openssl x509 -req -in envoy.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial \
  -out envoy.pem -days 825 -sha256 -extfile openssl-v3.ext

openssl verify -CAfile ca.pem envoy.pem
rm -f envoy.csr openssl-v3.ext

chmod 0640 ca-key.pem envoy-key.pem
chmod 0644 ca.pem envoy.pem

echo "Wrote Development CA and Envoy leaf to ${OUT}"
