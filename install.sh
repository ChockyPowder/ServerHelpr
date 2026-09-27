#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/ChockyPowder/ServerHelpr.git"
INSTALL_DIR="/opt/serverhelpr"
MODEL="${SERVERHELPR_MODEL:-qwen3.5:4b}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root."
  exit 1
fi

echo "==> Installing system packages"
apt-get update
apt-get install -y git python3 python3-venv python3-pip openssh-client ca-certificates curl

echo "==> Checking Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed."
  echo "Install it first with the official Ollama installer, then rerun this script."
  exit 1
fi

systemctl enable --now ollama 2>/dev/null || true

echo "==> Installing ServerHelpr into ${INSTALL_DIR}"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  git -C "${INSTALL_DIR}" pull --ff-only
else
  rm -rf "${INSTALL_DIR}"
  git clone "${REPO}" "${INSTALL_DIR}"
fi

echo "==> Creating Python virtual environment"
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

echo "==> Creating config"
if [[ ! -f "${INSTALL_DIR}/config.yaml" ]]; then
  cp "${INSTALL_DIR}/config.example.yaml" "${INSTALL_DIR}/config.yaml"
fi

echo "==> Pulling model: ${MODEL}"
ollama pull "${MODEL}"

echo
echo "============================================================"
echo " ServerHelpr installed"
echo "============================================================"
echo
echo "Edit:"
echo "  ${INSTALL_DIR}/config.yaml"
echo
echo "Then configure your Debian servers and SSH keys."
echo
echo "Start:"
echo "  cd ${INSTALL_DIR}"
echo "  ./.venv/bin/python -m serverhelpr"
echo
echo "Model:"
echo "  ${MODEL}"
echo
