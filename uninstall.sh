#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Pre-flight checks ---

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Error: This script must be run as root (use sudo)." >&2
    exit 1
fi

STATE_FILE="/etc/velora/state.json"

if [[ ! -f "$STATE_FILE" ]]; then
    echo "Velora state file not found at ${STATE_FILE}." >&2
    echo "Velora does not appear to be installed, or the state file was removed." >&2
    exit 1
fi

# --- Read all needed paths from state via a single Python call ---
# Python prints one value per line in a fixed order so bash can read them safely.

read_state_paths() {
    python3 -c "
import json, sys

with open('$STATE_FILE') as f:
    state = json.load(f)

if state.get('managed_by') != 'velora':
    print('Error: state file exists but is not managed by Velora.', file=sys.stderr)
    sys.exit(1)

# Print one value per line in fixed order (no shell metacharacter risk)
print(state.get('config_path', ''))
print(state.get('backup_path', ''))
print(str(state.get('config_created_by_velora', False)).lower())
print(state.get('generated_url_path', ''))
print(state.get('generated_client_json_path', ''))
print(state.get('generated_server_info_path', ''))
"
}

mapfile -t STATE_VALUES < <(read_state_paths)

if [[ ${#STATE_VALUES[@]} -lt 6 ]]; then
    echo "Error: Failed to read Velora state file." >&2
    exit 1
fi

CONFIG_PATH="${STATE_VALUES[0]}"
BACKUP_PATH="${STATE_VALUES[1]}"
CONFIG_CREATED_BY_VELORA="${STATE_VALUES[2]}"
GENERATED_URL_PATH="${STATE_VALUES[3]}"
GENERATED_CLIENT_JSON_PATH="${STATE_VALUES[4]}"
GENERATED_SERVER_INFO_PATH="${STATE_VALUES[5]}"

echo "Velora uninstall starting..."
echo "Config path: ${CONFIG_PATH:-none}"
echo "Backup path: ${BACKUP_PATH:-none}"

# --- Stop Xray ---

if systemctl is-active --quiet xray 2>/dev/null; then
    echo "Stopping Xray service..."
    systemctl stop xray
    echo "Xray stopped."
else
    echo "Xray service is not running."
fi

# --- Remove generated files (exact paths from state) ---

remove_if_exists() {
    local fp="$1"
    if [[ -n "$fp" && -f "$fp" ]]; then
        echo "Removing generated file: ${fp}"
        rm -f "$fp"
    fi
}

remove_if_exists "$GENERATED_URL_PATH"
remove_if_exists "$GENERATED_CLIENT_JSON_PATH"
remove_if_exists "$GENERATED_SERVER_INFO_PATH"

# Preserve generated/.gitkeep — only remove generated dir if empty and not the
# .gitkeep itself (which we leave alone).
for p in "$GENERATED_URL_PATH" "$GENERATED_CLIENT_JSON_PATH" "$GENERATED_SERVER_INFO_PATH"; do
    if [[ -n "$p" ]]; then
        parent_dir="$(dirname "$p")"
        # If parent is empty after removals, remove it — but only if .gitkeep
        # is the sole remaining file
        if [[ -d "$parent_dir" ]]; then
            shopt -s nullglob
            remaining=("$parent_dir"/*)
            shopt -u nullglob
            if [[ ${#remaining[@]} -eq 0 ]]; then
                rmdir "$parent_dir" 2>/dev/null || true
                echo "Removed empty directory: ${parent_dir}"
            fi
        fi
    fi
done

# --- Restore backup or remove Velora config ---

if [[ -n "$BACKUP_PATH" && -f "$BACKUP_PATH" ]]; then
    echo "Restoring backup config: ${BACKUP_PATH} -> ${CONFIG_PATH}"

    mkdir -p "$(dirname "$CONFIG_PATH")"
    cp "$BACKUP_PATH" "$CONFIG_PATH"
    # Xray runs as an unprivileged user (nobody), so the config must stay
    # world-readable — the backup itself is kept at 0600 for operator privacy.
    chmod 644 "$CONFIG_PATH"

    # Validate restored config
    echo "Testing restored config..."
    if xray run -test -config="$CONFIG_PATH" &>/dev/null; then
        echo "Restored config is valid."
        rm -f "$BACKUP_PATH"
        echo "Backup file removed."

        if systemctl is-enabled --quiet xray 2>/dev/null; then
            systemctl start xray
            echo "Xray restarted with restored config."
        fi
    else
        echo "Error: Restored config failed validation. Backup preserved at: ${BACKUP_PATH}" >&2
        echo "Your original config could not be validated. Manual inspection required." >&2
        exit 1
    fi

elif [[ "$CONFIG_CREATED_BY_VELORA" == "true" ]]; then
    if [[ -n "$CONFIG_PATH" && -f "$CONFIG_PATH" ]]; then
        echo "Removing Velora-created config: ${CONFIG_PATH}"
        rm -f "$CONFIG_PATH"
    fi
else
    echo "Config was not originally created by Velora and no backup exists."
    echo "Leaving config at ${CONFIG_PATH} untouched."
fi

# --- Remove Velora state file ---

if [[ -f "$STATE_FILE" ]]; then
    echo "Removing state file: ${STATE_FILE}"
    rm -f "$STATE_FILE"
fi

# --- Remove /etc/velora if empty ---

if [[ -d /etc/velora ]]; then
    if [[ -z "$(ls -A /etc/velora 2>/dev/null)" ]]; then
        rmdir /etc/velora
        echo "Removed empty directory: /etc/velora"
    fi
fi

echo ""
echo "Velora uninstall complete."
echo "Note: Xray binary and systemd service were not removed."
echo "If you want to remove Xray completely, use the official Xray uninstall script."
