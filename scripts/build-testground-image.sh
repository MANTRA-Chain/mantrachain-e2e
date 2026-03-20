#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Build and fetch testground image tarball via remote Nix builder, then docker load it.

Usage:
  scripts/build-testground-image.sh [mantrachaind|evmd]

Environment overrides:
  CHAIN_CONFIG            Chain config (mantrachaind|evmd). CLI arg takes precedence.
  BUILDER_HOST            SSH host for Nix builder (default: linux-builder)
  BUILDER_USER            SSH user for Nix builder (default: builder)
  BUILDER_KEY             SSH private key path (default: $HOME/.ssh/linux-builder_ed25519)
  TARGET_SYSTEM           Nix target system (default: aarch64-linux)
  DOCKER_HOST             Docker host socket for docker load

Examples:
  scripts/build-testground-image.sh evmd
  CHAIN_CONFIG=mantrachaind scripts/build-testground-image.sh
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

CHAIN_CONFIG="${1:-${CHAIN_CONFIG:-evmd}}"
BUILDER_HOST="${BUILDER_HOST:-linux-builder}"
BUILDER_USER="${BUILDER_USER:-builder}"
BUILDER_KEY="${BUILDER_KEY:-$HOME/.ssh/linux-builder_ed25519}"
TARGET_SYSTEM="${TARGET_SYSTEM:-aarch64-linux}"
DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.colima/default/docker.sock}"
export DOCKER_HOST

case "$CHAIN_CONFIG" in
  mantrachaind)
    IMAGE_NAME="mantra-testground"
    NIX_PACKAGE="testground-image"
    ;;
  evmd)
    IMAGE_NAME="evmd-testground"
    NIX_PACKAGE="testground-image-evmd"
    ;;
  *)
    echo "Unsupported CHAIN_CONFIG: $CHAIN_CONFIG"
    usage
    exit 1
    ;;
esac

if [[ ! -f "$BUILDER_KEY" ]]; then
  cat <<EOF
Builder key not found: $BUILDER_KEY

To fix:
  mkdir -p "$HOME/.ssh"
  sudo cat /etc/nix/builder_ed25519 > "$HOME/.ssh/linux-builder_ed25519"
  chmod 600 "$HOME/.ssh/linux-builder_ed25519"
EOF
  exit 1
fi

if [[ ! -r "$BUILDER_KEY" ]]; then
  cat <<EOF
Builder key is not readable: $BUILDER_KEY

Likely cause:
  The file is owned by root with mode 600.

Fix options:
  1) Recreate as your user-owned key:
     sudo cat /etc/nix/builder_ed25519 > "$HOME/.ssh/linux-builder_ed25519"
     chmod 600 "$HOME/.ssh/linux-builder_ed25519"

  2) If already copied, change ownership:
     sudo chown "$(id -un)":staff "$BUILDER_KEY"
     chmod 600 "$BUILDER_KEY"
EOF
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ARTIFACT_DIR="$ROOT_DIR/scripts/artifacts"
ENV_FILE="$ARTIFACT_DIR/testground-image.env"
mkdir -p "$ARTIFACT_DIR"

STORE_URL="ssh-ng://${BUILDER_USER}@${BUILDER_HOST}?ssh-key=${BUILDER_KEY}"
ATTR_PATH=".#packages.${TARGET_SYSTEM}.${NIX_PACKAGE}"
TAR_FILE="${IMAGE_NAME}.tar.gz"

echo "Building ${ATTR_PATH} using ${STORE_URL}"
REMOTE_PATH="$(nix build "$ATTR_PATH" --store "$STORE_URL" --eval-store auto --print-out-paths --no-link)"
REMOTE_PATH="$(echo "$REMOTE_PATH" | tail -n1)"
if [[ -z "$REMOTE_PATH" ]]; then
  echo "Failed to resolve remote output path from nix build"
  exit 1
fi

echo "Copying artifact from ${BUILDER_USER}@${BUILDER_HOST}:${REMOTE_PATH}"
scp -i "$BUILDER_KEY" "${BUILDER_USER}@${BUILDER_HOST}:${REMOTE_PATH}" "./${TAR_FILE}"

echo "Loading docker image from ${TAR_FILE}"
LOAD_OUTPUT="$(docker load < "$TAR_FILE")"
IMAGE_TAG="$(echo "$LOAD_OUTPUT" | sed -n "s/.*${IMAGE_NAME}:\(.*\)$/\1/p" | tail -n1)"

echo "$LOAD_OUTPUT"
if [[ -z "$IMAGE_TAG" ]]; then
  echo "Unable to parse image tag from docker load output"
  exit 1
fi

echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"

cat > "$ENV_FILE" <<EOF
export CHAIN_CONFIG="${CHAIN_CONFIG}"
export NIX_PACKAGE="${NIX_PACKAGE}"
export IMAGE_NAME="${IMAGE_NAME}"
export IMAGE_TAG="${IMAGE_TAG}"
export IMAGE_TAR_FILE="${TAR_FILE}"
EOF

echo "Wrote environment file: ${ENV_FILE}"
echo "Run: source ${ENV_FILE}"
