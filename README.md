# 🛡️ Velora

Simple self-hosted private tunnel installer for personal servers.

<p>
  <img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg">
  <img alt="Ubuntu 22.04 | 24.04" src="https://img.shields.io/badge/OS-Ubuntu%2022.04%20%7C%2024.04-E95420?logo=ubuntu&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white">
  <img alt="Bash" src="https://img.shields.io/badge/Shell-Bash-4EAA25?logo=gnubash&logoColor=white">
  <img alt="Protocol" src="https://img.shields.io/badge/Protocol-VLESS%20%2B%20Reality-6f42c1">
  <img alt="Install script" src="https://img.shields.io/badge/Install%20script-%3C20s-brightgreen">
</p>

## 🎬 Demo

`install.sh` itself, timed, from a clean Ubuntu VPS to a working
VLESS+Reality tunnel — doesn't include `git clone`, which depends on your
own network:

https://github.com/user-attachments/assets/36a90715-e4ee-4f0e-847e-c1eb5b7bd450

## ✨ What It Does

Velora automates the deployment of a VLESS + Reality tunnel on your personal
Ubuntu VPS. After running 2–3 commands, you get a ready-to-use private tunnel
with a single-line connection URL ready for import into your client.

## ⚡ Features

- Zero-config sensible defaults — works out of the box
- Fully automated Xray installation via the official XTLS script
- Generates a single-line VLESS import URL
- Safe: backs up existing Xray config before making changes
- Dry-run mode for validation without touching the system
- Clean uninstall with backup restoration

## 🐧 Supported OS

- Ubuntu 22.04 LTS
- Ubuntu 24.04 LTS

Other distributions are not supported.

## 📋 Requirements

- A fresh Ubuntu 22.04 or 24.04 VPS
- Root access (sudo)
- Port 443 available (or choose a custom port)
- Internet access during installation

## 🚀 Quick Start

```bash
git clone https://github.com/jesuspeterson342-dot/Velora.git
cd Velora
sudo bash install.sh
```

That's it. The installer will:

1. Install Xray (if not already present)
2. Generate keys and configuration
3. Write the Xray server config
4. Start and enable the Xray service
5. Save your connection URL

## ⚙️ CLI Options

All options are passed through `install.sh` to the Python installer:

```bash
sudo bash install.sh [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--port PORT` | `443` | Inbound listen port |
| `--server-name HOST` | `www.microsoft.com` | SNI server name for Reality |
| `--dest HOST:PORT` | `www.microsoft.com:443` | Reality destination target |
| `--client-name NAME` | `Velora` | Client label in the import URL |
| `--dry-run` | off | Validate without system changes |
| `--print-url` | off | Print the full VLESS URL to terminal |
| `--output-dir DIR` | `generated` | Directory for generated files |
| `--config-path PATH` | auto | Override Xray config path |

### Examples

```bash
# Default install
sudo bash install.sh

# Custom port
sudo bash install.sh --port 8443

# Dry-run to preview without installing
python3 installer.py --dry-run

# Print the URL to terminal after install
sudo bash install.sh --print-url
```

## 📁 Generated Files

After a successful installation, Velora creates these files inside the
project directory:

```
generated/
  URL.txt          ← Your VLESS import URL (single line)
  client.json      ← Client configuration data
  server-info.txt  ← Server status summary
```

The state file is stored at `/etc/velora/state.json` for status checks
and clean uninstall.

## 🔗 How to Copy the Connection URL

The generated VLESS URL is saved to `generated/URL.txt`.

**From the project directory:**

```bash
cat generated/URL.txt
```

**If you are outside the project directory,** use the absolute path shown
by the installer output:

```bash
cat /absolute/path/to/Velora/generated/URL.txt
```

**If access is denied (permission):**

```bash
sudo cat generated/URL.txt
```

Copy the single line and import it into your client application.

**Important:** If the URL visually wraps in your terminal, the file still
contains a single unbroken line. Copy carefully — do not add extra spaces
or newlines.

## ⏱️ Timed Install (optional)

Want to see how fast it actually runs on your own server?

```bash
sudo bash timed-install.sh
```

Same as `install.sh`, but with a live elapsed-time counter and a final
`Done in Ns.` summary. Actual time depends on your network speed and server
specs — this measures your run, it isn't a guarantee.

## 📊 Status Check

```bash
sudo bash status.sh
```

Shows:
- Velora installation status
- Xray service status
- Public IP and port
- Config path
- Path to your connection URL

## 🧹 Uninstall

```bash
sudo bash uninstall.sh
```

Velora's uninstaller:

1. Stops the Xray service
2. Restores your previous Xray config (if a backup exists)
3. Removes only files created by Velora
4. Does **not** remove the Xray binary or systemd service

## 🛠️ Troubleshooting

### Port 443 already in use

Check what is using the port:

```bash
sudo ss -tlnp | grep :443
```

Stop the conflicting service or choose a different port:

```bash
sudo bash install.sh --port 8443
```

### Xray command not found

The installer downloads Xray automatically. If it fails, check your
internet connection and try again.

### Xray config test failed

The installer validates the config before starting Xray. If validation
fails, the previous config (if any) is automatically restored. Check the
error output for details.

### UFW active

If `ufw` is enabled, you will see a warning. Make sure to allow the
target port:

```bash
sudo ufw allow 443/tcp
```

### VPS provider firewall / security group

Many cloud providers have an additional firewall or security group layer.
Make sure your VPS provider allows inbound TCP on the port you chose.

### URL wraps visually in terminal

The file contains a single line. When you select and copy from your
terminal, make sure you copy the entire line without extra characters.

### Permission denied when reading URL.txt

The generated files are owned by the user who ran `sudo`. If you get
a permission error, use:

```bash
sudo cat generated/URL.txt
```

### Unsupported OS

Velora only supports Ubuntu 22.04 and 24.04. Check your OS:

```bash
cat /etc/os-release
```

## 🔒 Security Notes

- `generated/URL.txt` grants full access to your tunnel. Keep it private.
- Do not commit generated files to version control (they are in `.gitignore`).
- The private key is stored only inside the Xray server config file.
- The state file at `/etc/velora/state.json` does **not** store the private key.
- Generated files are created with restrictive permissions (600).

## 📄 License

MIT License. See [LICENSE](LICENSE).
