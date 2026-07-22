#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

STATE_FILE="/etc/velora/state.json"

if [[ ! -f "$STATE_FILE" ]]; then
    echo "Velora is not installed." >&2
    echo "State file not found: ${STATE_FILE}" >&2
    echo "Run: sudo bash install.sh" >&2
    exit 1
fi

# --- Read state via embedded Python (safe: one value per line, no eval) ---

read_state_fields() {
    python3 -c "
import json, sys

with open('$STATE_FILE') as f:
    state = json.load(f)

if state.get('managed_by') != 'velora':
    print('NONE', file=sys.stderr)
    sys.exit(1)

# Print one value per line in fixed order — bash reads them safely
print(state.get('public_ip', 'unknown'))
print(str(state.get('port', '443')))
print(state.get('config_path', 'unknown'))
print(state.get('generated_url_path', 'unknown'))
print(state.get('client_name', 'Velora'))
print(state.get('server_name', 'unknown'))
print(state.get('created_at', 'unknown'))
"
}

mapfile -t STATE_VALUES < <(read_state_fields)

if [[ ${#STATE_VALUES[@]} -lt 7 ]]; then
    echo "Error: State file is invalid or not managed by Velora." >&2
    exit 1
fi

PUBLIC_IP="${STATE_VALUES[0]}"
PORT="${STATE_VALUES[1]}"
CONFIG_PATH="${STATE_VALUES[2]}"
GENERATED_URL_PATH="${STATE_VALUES[3]}"
CLIENT_NAME="${STATE_VALUES[4]}"
SERVER_NAME="${STATE_VALUES[5]}"
CREATED_AT="${STATE_VALUES[6]}"

echo "=============================="
echo " Velora Status"
echo "=============================="
echo ""

echo "Installation:  Velora managed"
echo "Public IP:     ${PUBLIC_IP}"
echo "Port:          ${PORT}"
echo "Config path:   ${CONFIG_PATH}"
echo ""

# Xray service status
echo "--- Xray Service ---"
if systemctl is-active --quiet xray 2>/dev/null; then
    echo "Status:        active (running)"
elif systemctl is-enabled --quiet xray 2>/dev/null; then
    echo "Status:        inactive (enabled but not running)"
else
    echo "Status:        inactive"
fi
echo ""

echo "--- Connection ---"
echo "URL file:      ${GENERATED_URL_PATH}"
echo ""

if [[ -f "${GENERATED_URL_PATH}" ]]; then
    echo "To display the connection URL:"
    echo "  cat ${GENERATED_URL_PATH}"
    if [[ "$(id -u)" -ne 0 ]]; then
        echo ""
        echo "If access is denied, use:"
        echo "  sudo cat ${GENERATED_URL_PATH}"
    fi
else
    echo "Warning: URL file not found at ${GENERATED_URL_PATH}" >&2
    echo "The file may have been moved or deleted." >&2
fi

echo ""
echo "--- Commands ---"
echo "Status check:  sudo bash ${SCRIPT_DIR}/status.sh"
echo "Uninstall:     sudo bash ${SCRIPT_DIR}/uninstall.sh"
echo ""
