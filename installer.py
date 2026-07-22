#!/usr/bin/env python3
"""
Velora — Simple self-hosted private tunnel installer.

Installs and configures a VLESS + Reality tunnel on Ubuntu VPS.
Uses only the Python standard library. No external dependencies.
"""

import argparse
import json
import os
import pathlib
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "generated"
STATE_DIR = pathlib.Path("/etc/velora")
STATE_FILE = STATE_DIR / "state.json"

XRAY_INSTALL_SCRIPT_URL = (
    "https://github.com/XTLS/Xray-install/raw/main/install-release.sh"
)

# Preferred Xray config location
PREFERRED_CONFIG_PATH = pathlib.Path("/usr/local/etc/xray/config.json")
FALLBACK_CONFIG_PATH = pathlib.Path("/etc/xray/config.json")

IP_DETECTION_ENDPOINTS = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
]

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class VeloraError(Exception):
    """Base exception for Velora installer errors."""


def fail(message: str, code: int = 1) -> None:
    """Print an error message to stderr and exit."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------


def run_command(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: int | None = 30,
    input_str: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a command safely (no shell=True). Capture stdout/stderr by default."""
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True,
            timeout=timeout,
            input=input_str,
        )
    except subprocess.CalledProcessError as exc:
        raise VeloraError(
            f"Command failed: {' '.join(cmd)}\n{exc.stderr or exc.stdout or ''}"
        ) from exc
    except FileNotFoundError:
        raise VeloraError(f"Command not found: {cmd[0]}")


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------


def require_root() -> None:
    """Exit if not running as root."""
    if os.geteuid() != 0:
        fail("This installer must be run as root (use sudo).")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_port(value: str) -> int:
    """Validate --port argument: must be an integer 1..65535."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer")
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Velora — Private tunnel installer",
    )
    parser.add_argument(
        "--port",
        type=parse_port,
        default=443,
        help="Inbound listen port (default: 443)",
    )
    # Not www.microsoft.com: xtls/reality caps the buffered handshake it
    # captures from `dest` at 8192 bytes (transport/internet/reality's vendored
    # tls.go), and microsoft.com's OCSP-stapled certificate chain (8273 bytes)
    # exceeds that, so the Reality handshake never completes for any client.
    # cloudflare.com's chain is well under the cap.
    parser.add_argument(
        "--server-name",
        default="www.cloudflare.com",
        help="SNI server name for Reality (default: www.cloudflare.com)",
    )
    parser.add_argument(
        "--dest",
        default="www.cloudflare.com:443",
        help="Reality destination target (default: www.cloudflare.com:443)",
    )
    parser.add_argument(
        "--client-name",
        default="Velora",
        help="Client label in the import URL (default: Velora)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without system changes (no root required)",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the full VLESS URL to terminal after install",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated files (default: generated)",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Override Xray config path",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_output_dir(raw: str) -> pathlib.Path:
    """Resolve --output-dir relative to PROJECT_ROOT or as absolute path."""
    p = pathlib.Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def detect_config_path(cli_override: str | None = None) -> pathlib.Path:
    """Determine the Xray config path to use."""
    if cli_override:
        p = pathlib.Path(cli_override).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    for candidate in (PREFERRED_CONFIG_PATH, FALLBACK_CONFIG_PATH):
        if candidate.parent.exists():
            return candidate

    # Neither parent exists — create the preferred one
    PREFERRED_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    return PREFERRED_CONFIG_PATH


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def get_public_ip() -> str:
    """Detect public IPv4 address using fallback endpoints."""
    last_error: str | None = None
    for url in IP_DETECTION_ENDPOINTS:
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                raw = resp.read().decode("utf-8").strip()
            if validate_ipv4(raw):
                return raw
            last_error = f"Endpoint {url} returned non-IPv4: {raw}"
        except Exception as exc:
            last_error = f"Endpoint {url} failed: {exc}"

    fail(f"Could not detect public IPv4 address. {last_error}")


def validate_ipv4(addr: str) -> bool:
    """Return True if addr is a valid IPv4 address."""
    try:
        socket.inet_pton(socket.AF_INET, addr)
        return True
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Cryptography helpers
# ---------------------------------------------------------------------------


def generate_uuid() -> str:
    """Generate a random UUIDv4."""
    import uuid

    return str(uuid.uuid4())


def generate_reality_keys() -> tuple[str, str]:
    """Generate a Reality keypair via `xray x25519`.

    Returns (private_key, public_key). The private key is never printed.
    """
    # xray x25519 output format varies across Xray versions, e.g.:
    #   Private key: <value>          Public key: <value>          (older)
    #   PrivateKey: <value>           Password (PublicKey): <value> (newer)
    result = run_command(["xray", "x25519"], timeout=15)
    output = result.stdout

    private_key: str | None = None
    public_key: str | None = None

    for line in output.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        normalized = re.sub(r"[^a-z]", "", label.lower())
        value = value.strip()
        if normalized == "privatekey":
            private_key = value
        elif normalized in ("publickey", "passwordpublickey"):
            public_key = value

    if not private_key or not public_key:
        raise VeloraError(
            f"Failed to parse xray x25519 output:\n{output}"
        )

    return private_key, public_key


def generate_short_id() -> str:
    """Generate a hex short ID (16 hex chars = 8 bytes)."""
    return secrets.token_hex(8)


# ---------------------------------------------------------------------------
# Port check
# ---------------------------------------------------------------------------


def check_port_available(port: int) -> None:
    """Raise VeloraError if the port is out of range or already in use."""
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise VeloraError(f"Invalid port: {port}. Must be between 1 and 65535.")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
    except OSError:
        raise VeloraError(
            f"Port {port} is already in use. Choose a different port with --port."
        )


# ---------------------------------------------------------------------------
# Xray config generation
# ---------------------------------------------------------------------------


def build_xray_config(
    port: int,
    uuid: str,
    private_key: str,
    short_id: str,
    server_name: str,
    dest: str,
) -> dict:
    """Build a VLESS + Reality inbound configuration dict.

    Only fields verified against official Xray documentation are used.
    Reference: https://github.com/XTLS/Xray-examples
    """
    return {
        "inbounds": [
            {
                "listen": "0.0.0.0",
                "port": port,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        {
                            "id": uuid,
                            "flow": "xtls-rprx-vision",
                        }
                    ],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": dest,
                        "xver": 0,
                        "serverNames": [server_name],
                        "privateKey": private_key,
                        "shortIds": [short_id],
                    },
                },
            }
        ],
        "outbounds": [
            {
                "protocol": "freedom",
                "tag": "direct",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Atomic file write
# ---------------------------------------------------------------------------


def write_json_atomic(path: pathlib.Path, data: dict, mode: int = 0o600) -> None:
    """Write JSON data atomically: write to a temp file first, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.chmod(mode)
    tmp.replace(path)


def write_text_atomic(path: pathlib.Path, content: str, mode: int = 0o600) -> None:
    """Write text data atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    tmp.chmod(mode)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def backup_existing_config(config_path: pathlib.Path) -> pathlib.Path | None:
    """Create a timestamped backup of the existing Xray config.

    Returns the backup path, or None if no config existed.
    """
    if not config_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = config_path.with_name(
        f"{config_path.name}.velora-backup-{timestamp}"
    )
    shutil.copy2(config_path, backup_path)
    backup_path.chmod(0o600)
    print(f"Backed up existing config to: {backup_path}")
    return backup_path


# ---------------------------------------------------------------------------
# Xray config test
# ---------------------------------------------------------------------------


def test_xray_config(config_path: pathlib.Path) -> bool:
    """Validate the Xray config with `xray run -test -config=<path>`.

    Returns True if valid, False otherwise.
    """
    try:
        run_command(
            ["xray", "run", "-test", f"-config={config_path}"],
            timeout=30,
        )
        return True
    except VeloraError as exc:
        print(f"Xray config validation failed:\n{exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Systemd actions
# ---------------------------------------------------------------------------


def start_xray_service() -> bool:
    """Enable and start the Xray systemd service.

    Returns True on success, False if the service failed to start.
    """
    # Check systemd is available
    try:
        run_command(["systemctl", "--version"], capture=False, timeout=5)
    except VeloraError:
        fail("systemd is not available on this system.")

    try:
        run_command(["systemctl", "enable", "xray"], capture=False)
        print("Xray service enabled.")
    except VeloraError as exc:
        print(f"Warning: Failed to enable xray service: {exc}", file=sys.stderr)
        return False

    try:
        run_command(["systemctl", "restart", "xray"], capture=False)
        print("Xray service restarted.")
    except VeloraError as exc:
        print(f"Error: Failed to restart xray service: {exc}", file=sys.stderr)
        return False

    # Verify it is active. The unit is Type=simple, so systemd marks it
    # "active" the instant the process forks — before Xray has finished
    # loading its config. A fast crash (e.g. an unreadable config file)
    # can therefore pass an immediate check. Re-check after a short delay
    # to catch that case instead of reporting false success.
    for attempt in range(2):
        if attempt:
            time.sleep(1)
        active = subprocess.run(
            ["systemctl", "is-active", "xray"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if active.stdout.strip() != "active":
            print(
                f"Error: Xray service is not active after restart. "
                f"Status: {active.stdout.strip()}.",
                file=sys.stderr,
            )
            return False

    print("Xray service is active.")
    return True


# ---------------------------------------------------------------------------
# VLESS URL generation
# ---------------------------------------------------------------------------


def build_vless_url(
    uuid: str,
    public_ip: str,
    port: int,
    server_name: str,
    public_key: str,
    short_id: str,
    client_name: str,
) -> str:
    """Build a VLESS Reality import URL.

    Format: vless://UUID@IP:PORT?params...#REMARK
    Query parameters use urllib.parse.urlencode.
    Fragment (client name) uses urllib.parse.quote.
    """
    params = {
        "encryption": "none",
        "security": "reality",
        "sni": server_name,
        "fp": "chrome",
        "pbk": public_key,
        "sid": short_id,
        "type": "tcp",
        "flow": "xtls-rprx-vision",
    }
    query = urllib.parse.urlencode(params)
    fragment = urllib.parse.quote(client_name, safe="")
    return f"vless://{uuid}@{public_ip}:{port}?{query}#{fragment}"


# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------


def write_generated_files(
    output_dir: pathlib.Path,
    vless_url: str,
    public_ip: str,
    port: int,
    uuid: str,
    public_key: str,
    short_id: str,
    server_name: str,
    client_name: str,
    dest: str,
    config_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Write URL.txt, client.json, and server-info.txt to output_dir.

    Returns (url_path, client_json_path, server_info_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # URL.txt — single line, no wrapping, no extra text
    url_path = output_dir / "URL.txt"
    write_text_atomic(url_path, vless_url + "\n", mode=0o600)

    # client.json
    client_data = {
        "protocol": "vless",
        "address": public_ip,
        "port": port,
        "uuid": uuid,
        "flow": "xtls-rprx-vision",
        "security": "reality",
        "sni": server_name,
        "fingerprint": "chrome",
        "publicKey": public_key,
        "shortId": short_id,
        "type": "tcp",
        "vlessUrl": vless_url,
    }
    client_json_path = output_dir / "client.json"
    write_json_atomic(client_json_path, client_data, mode=0o600)

    # server-info.txt
    server_info_lines = [
        "Project: Velora",
        f"Public IP: {public_ip}",
        f"Port: {port}",
        "Protocol: VLESS + Reality",
        f"Server name: {server_name}",
        f"Destination: {dest}",
        f"Client name: {client_name}",
        f"Config path: {config_path}",
        f"URL file: {url_path}",
        f"Client JSON: {client_json_path}",
        "Status command: sudo bash status.sh",
        "Uninstall command: sudo bash uninstall.sh",
    ]
    server_info_path = output_dir / "server-info.txt"
    write_text_atomic(server_info_path, "\n".join(server_info_lines) + "\n", mode=0o600)

    return url_path, client_json_path, server_info_path


def set_generated_file_ownership(
    output_dir: pathlib.Path,
    url_path: pathlib.Path,
    client_json_path: pathlib.Path,
    server_info_path: pathlib.Path,
) -> None:
    """If SUDO_UID/SUDO_GID are set, chown files to the original user."""
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")

    if sudo_uid is None or sudo_gid is None:
        return

    uid = int(sudo_uid)
    gid = int(sudo_gid)

    # Recursive helper
    def _chown(p: pathlib.Path) -> None:
        try:
            os.chown(p, uid, gid)
        except OSError:
            pass  # best-effort

    _chown(output_dir)
    output_dir.chmod(0o700)
    for f in (url_path, client_json_path, server_info_path):
        _chown(f)
        f.chmod(0o600)


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


def write_state(
    project_root: pathlib.Path,
    config_path: pathlib.Path,
    backup_path: pathlib.Path | None,
    config_created_by_velora: bool,
    port: int,
    public_ip: str,
    server_name: str,
    dest: str,
    client_name: str,
    uuid: str,
    short_id: str,
    public_key: str,
    generated_url_path: pathlib.Path,
    generated_client_json_path: pathlib.Path,
    generated_server_info_path: pathlib.Path,
) -> None:
    """Write the Velora state file. Never includes private key or full URL."""
    state = {
        "managed_by": "velora",
        "version": "0.1.0",
        "project_root": str(project_root),
        "config_path": str(config_path),
        "backup_path": str(backup_path) if backup_path else "",
        "config_created_by_velora": config_created_by_velora,
        "port": port,
        "public_ip": public_ip,
        "server_name": server_name,
        "dest": dest,
        "client_name": client_name,
        "uuid": uuid,
        "short_id": short_id,
        "public_key": public_key,
        "generated_url_path": str(generated_url_path),
        "generated_client_json_path": str(generated_client_json_path),
        "generated_server_info_path": str(generated_server_info_path),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    write_json_atomic(STATE_FILE, state, mode=0o600)


# ---------------------------------------------------------------------------
# Firewall checks
# ---------------------------------------------------------------------------


def check_firewall(port: int) -> None:
    """Warn if UFW is active without blocking installation.

    Checks shutil.which("ufw") first to avoid crashing when ufw is not installed.
    """
    if shutil.which("ufw") is None:
        return  # ufw not installed, nothing to check

    try:
        ufw_status = subprocess.run(
            ["ufw", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return  # ufw command failed for any reason, not fatal

    if ufw_status.returncode == 0 and "Status: active" in ufw_status.stdout:
        print()
        print(
            f"Warning: UFW appears to be active. "
            f"Make sure TCP port {port} is allowed."
        )
        print("Also check your VPS provider firewall/security group settings.")
        print()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace) -> None:
    """Simulate the full install without touching the system.

    No root, no Xray, no systemd, no apt, no network, no /etc writes.
    """
    output_dir = resolve_output_dir(args.output_dir)
    dry_dir = output_dir / "dry-run"
    dry_dir.mkdir(parents=True, exist_ok=True)

    # Safe mock values
    mock_public_ip = "203.0.113.10"  # TEST-NET-3 (RFC 5737)
    mock_uuid = "11111111-1111-4111-8111-111111111111"
    mock_private_key = "mock_private_key_for_dry_run"
    mock_public_key = "mock_public_key_for_dry_run"
    mock_short_id = "0123456789abcdef"

    print("--- Dry Run ---")
    print(f"Port:            {args.port}")
    print(f"Server name:     {args.server_name}")
    print(f"Dest:            {args.dest}")
    print(f"Client name:     {args.client_name}")
    print(f"Output dir:      {dry_dir}")
    print(f"Public IP:       {mock_public_ip}")

    # Build the Xray config
    config = build_xray_config(
        port=args.port,
        uuid=mock_uuid,
        private_key=mock_private_key,
        short_id=mock_short_id,
        server_name=args.server_name,
        dest=args.dest,
    )
    config_json = json.dumps(config, indent=2, ensure_ascii=False)

    # Generate VLESS URL
    vless_url = build_vless_url(
        uuid=mock_uuid,
        public_ip=mock_public_ip,
        port=args.port,
        server_name=args.server_name,
        public_key=mock_public_key,
        short_id=mock_short_id,
        client_name=args.client_name,
    )

    mock_config_path = pathlib.Path("/usr/local/etc/xray/config.json")

    # Write dry-run files
    write_generated_files(
        output_dir=dry_dir,
        vless_url=vless_url,
        public_ip=mock_public_ip,
        port=args.port,
        uuid=mock_uuid,
        public_key=mock_public_key,
        short_id=mock_short_id,
        server_name=args.server_name,
        client_name=args.client_name,
        dest=args.dest,
        config_path=mock_config_path,
    )

    # Validate JSON is valid
    json.loads(config_json)
    print("Config JSON:     valid")

    # Validate VLESS URL structure
    parsed = urllib.parse.urlparse(vless_url)
    if parsed.scheme != "vless":
        fail(f"Dry-run: generated URL has invalid scheme '{parsed.scheme}'")
    if parsed.hostname != mock_public_ip:
        fail("Dry-run: generated URL hostname mismatch")
    if parsed.port != args.port:
        fail("Dry-run: generated URL port mismatch")
    print("VLESS URL:       valid")

    # Validate generated files exist and have content
    for name in ("URL.txt", "client.json", "server-info.txt"):
        fp = dry_dir / name
        if not fp.exists() or fp.stat().st_size == 0:
            fail(f"Dry-run: {name} is missing or empty")
    print("Generated files: valid")

    # If --print-url, show the mock URL
    if args.print_url:
        print()
        print("Mock VLESS URL (dry-run):")
        print(vless_url)

    print()
    print("Dry run completed successfully.")


# ---------------------------------------------------------------------------
# Real install
# ---------------------------------------------------------------------------


def cleanup_failed_install(
    url_path: pathlib.Path,
    client_json_path: pathlib.Path,
    server_info_path: pathlib.Path,
) -> None:
    """Remove generated files and state file on a failed install.

    Only removes the exact paths created during this install attempt.
    Preserves generated/.gitkeep.
    """
    for fp in (url_path, client_json_path, server_info_path):
        if fp.exists():
            fp.unlink(missing_ok=True)
            print(f"Removed: {fp}")

    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"Removed: {STATE_FILE}")


# ---------------------------------------------------------------------------
# Real install
# ---------------------------------------------------------------------------


def rollback_config(config_path: pathlib.Path, backup_path: pathlib.Path | None) -> None:
    """Restore backup config if available, otherwise remove the Velora config."""
    if backup_path is not None and backup_path.exists():
        print("Rolling back to backup config...")
        shutil.copy2(backup_path, config_path)
        config_path.chmod(0o644)
        print("Backup restored.")
        # Re-test the restored backup
        if test_xray_config(config_path):
            # Try to start xray with the restored config
            subprocess.run(
                ["systemctl", "start", "xray"],
                capture_output=True,
                timeout=15,
            )
            print("Xray restarted with restored config.")
        else:
            print(
                "Warning: Restored backup also failed validation. "
                "Manual inspection required.",
                file=sys.stderr,
            )
    else:
        if config_path.exists():
            config_path.unlink(missing_ok=True)
            print("Removed invalid Velora config.")


def install(args: argparse.Namespace) -> None:
    """Run the real installation on a target VPS."""
    require_root()

    # installer.py only orchestrates key/config generation and the systemd
    # service — it never installs the Xray binary itself. That step lives in
    # install.sh. Running this script directly without install.sh (or an
    # existing Xray install) would otherwise fail deep into the run with a
    # bare "Command not found: xray".
    if shutil.which("xray") is None:
        fail(
            "Xray is not installed or not in PATH. Run install.sh instead "
            "(it installs Xray automatically), or install Xray manually via "
            "the official script: https://github.com/XTLS/Xray-install"
        )

    output_dir = resolve_output_dir(args.output_dir)

    # 1. Check port
    print(f"Checking port {args.port}...")
    check_port_available(args.port)

    # 2. Detect public IP
    print("Detecting public IPv4...")
    public_ip = get_public_ip()
    print(f"Public IP: {public_ip}")

    # 3. Generate UUID
    print("Generating UUID...")
    uuid = generate_uuid()

    # 4. Generate Reality keys
    print("Generating Reality keypair via xray x25519...")
    private_key, public_key = generate_reality_keys()
    print("Reality keypair generated.")

    # 5. Generate short ID
    short_id = generate_short_id()

    # 6. Determine config path
    config_path = detect_config_path(args.config_path)
    print(f"Config path: {config_path}")

    # 7. Backup existing config
    backup_path = backup_existing_config(config_path)
    if backup_path is not None:
        config_created_by_velora = False
    else:
        config_created_by_velora = True

    # 8. Build and write Xray config
    print("Building Xray config...")
    config = build_xray_config(
        port=args.port,
        uuid=uuid,
        private_key=private_key,
        short_id=short_id,
        server_name=args.server_name,
        dest=args.dest,
    )

    print(f"Writing Xray config to {config_path}...")
    # The Xray systemd service (per the official install script) runs as an
    # unprivileged user (nobody), so the config it reads at startup must be
    # world-readable — unlike the files under generated/, which only need to
    # be readable by the operator and are kept at 0o600.
    write_json_atomic(config_path, config, mode=0o644)

    # 9. Validate config
    print("Validating Xray config...")
    if not test_xray_config(config_path):
        rollback_config(config_path, backup_path)
        fail("Xray config validation failed. Aborting installation.")

    print("Xray config is valid.")

    # 10. Build VLESS URL
    vless_url = build_vless_url(
        uuid=uuid,
        public_ip=public_ip,
        port=args.port,
        server_name=args.server_name,
        public_key=public_key,
        short_id=short_id,
        client_name=args.client_name,
    )

    # 11. Write generated files
    print("Writing generated files...")
    url_path, client_json_path, server_info_path = write_generated_files(
        output_dir=output_dir,
        vless_url=vless_url,
        public_ip=public_ip,
        port=args.port,
        uuid=uuid,
        public_key=public_key,
        short_id=short_id,
        server_name=args.server_name,
        client_name=args.client_name,
        dest=args.dest,
        config_path=config_path,
    )

    # 12. Set ownership for generated files
    set_generated_file_ownership(
        output_dir, url_path, client_json_path, server_info_path
    )

    # 13. Write state file
    print("Writing state file...")
    write_state(
        project_root=PROJECT_ROOT,
        config_path=config_path,
        backup_path=backup_path,
        config_created_by_velora=config_created_by_velora,
        port=args.port,
        public_ip=public_ip,
        server_name=args.server_name,
        dest=args.dest,
        client_name=args.client_name,
        uuid=uuid,
        short_id=short_id,
        public_key=public_key,
        generated_url_path=url_path,
        generated_client_json_path=client_json_path,
        generated_server_info_path=server_info_path,
    )

    # 14. Start Xray
    print("Starting Xray service...")
    if not start_xray_service():
        print("Cleaning up failed installation artifacts...")
        rollback_config(config_path, backup_path)
        cleanup_failed_install(url_path, client_json_path, server_info_path)
        fail(
            f"Failed to start Xray service. "
            f"Config rolled back, generated files and state file removed. "
            f"Check: journalctl -u xray --no-pager -n 50"
        )

    # 15. Firewall check
    check_firewall(args.port)

    # 16. Final output
    print()
    print("========================================")
    print("  Velora installation complete!")
    print("========================================")
    print()
    print(f"Your connection URL has been saved to:")
    print(f"  {url_path}")
    print()
    if os.environ.get("SUDO_UID"):
        sudo_uid = os.environ["SUDO_UID"]
        sudo_gid = os.environ.get("SUDO_GID", sudo_uid)
        print("Files are owned by your user account.")
        print("To display the URL from the project directory:")
        print(f"  cat generated/URL.txt")
    else:
        print("Files are owned by root (no SUDO_UID detected).")
        print("To display the URL:")
        print(f"  sudo cat {url_path}")
    print()
    print("If you are outside the project directory, use the absolute path.")
    print("Copy the single line and import it into your client.")
    print("If the URL wraps visually in terminal, the file still")
    print("contains a single unbroken line.")
    print()

    if args.print_url:
        print("Your VLESS URL:")
        print(vless_url)
        print()
        print("The line above is also saved in generated/URL.txt")
        print()

    print("Status check:  sudo bash status.sh")
    print("Uninstall:     sudo bash uninstall.sh")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        args = parse_args()
        if args.dry_run:
            dry_run(args)
        else:
            install(args)
    except VeloraError as exc:
        fail(str(exc))
    except KeyboardInterrupt:
        fail("Interrupted by user.", code=130)
    except OSError as exc:
        fail(f"System error: {exc}")


if __name__ == "__main__":
    main()
