#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Pre-flight checks ---

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Error: This script must be run as root (use sudo)." >&2
    exit 1
fi

# OS detection
if [[ ! -f /etc/os-release ]]; then
    echo "Error: Cannot detect OS (/etc/os-release missing)." >&2
    exit 1
fi

source /etc/os-release

if [[ "$ID" != "ubuntu" ]]; then
    echo "Error: Unsupported OS '${ID}'. Velora supports Ubuntu 22.04 and 24.04 only." >&2
    exit 1
fi

if [[ "$VERSION_ID" != "22.04" && "$VERSION_ID" != "24.04" ]]; then
    echo "Error: Unsupported Ubuntu version '${VERSION_ID}'. Velora supports Ubuntu 22.04 and 24.04 only." >&2
    exit 1
fi

echo "Detected ${PRETTY_NAME:-Ubuntu ${VERSION_ID}}"

# --- Install system dependencies ---

echo "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 curl unzip ca-certificates

# --- Install Xray if missing ---

if ! command -v xray &>/dev/null; then
    echo "Xray not found. Downloading official Xray install script..."

    XRAY_INSTALL_SCRIPT="/tmp/velora-install-xray.sh"
    XRAY_INSTALL_URL="https://github.com/XTLS/Xray-install/raw/main/install-release.sh"

    if ! curl -fsSL --connect-timeout 30 --max-time 120 \
        -o "$XRAY_INSTALL_SCRIPT" "$XRAY_INSTALL_URL"; then
        echo "Error: Failed to download Xray install script from ${XRAY_INSTALL_URL}" >&2
        exit 1
    fi

    if [[ ! -s "$XRAY_INSTALL_SCRIPT" ]]; then
        echo "Error: Downloaded Xray install script is empty." >&2
        exit 1
    fi

    echo "Running Xray install script..."
    bash "$XRAY_INSTALL_SCRIPT"

    if ! command -v xray &>/dev/null; then
        echo "Error: Xray installation completed but 'xray' command is still not found." >&2
        exit 1
    fi

    echo "Xray installed successfully."
else
    echo "Xray is already installed: $(command -v xray)"
fi

# --- Run the Python installer ---

cd "$SCRIPT_DIR"
exec python3 "$SCRIPT_DIR/installer.py" "$@"
