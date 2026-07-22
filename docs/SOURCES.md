# Sources

This document lists the official sources referenced during Velora development.

## Xray Install Script

- **XTLS Xray-install**: https://github.com/XTLS/Xray-install
- Official install script used: `install-release.sh` from the above repository.
- Downloaded, verified for existence, and executed explicitly via `bash`.

## Xray Reality Configuration

- **XTLS Xray-examples**: https://github.com/XTLS/Xray-examples
- Canonical REALITY server config: `VLESS-TCP-XTLS-Vision-REALITY/REALITY.ENG.md`
- Fields used in Velora config were verified against this official example.
- No unverified fields were added to the generated config.

## Xray Command Reference

- **XTLS documentation**: https://xtls.github.io/en/document/command.html
- Config validation command: `xray run -test -config=<path>`
- Key generation command: `xray x25519`

## VLESS Share URL Format

- **XTLS outbound config documentation**: https://xtls.github.io/en/config/outbounds/vless.html
- URL structure: `vless://UUID@ADDRESS:PORT?params...#REMARK`
- Parameters confirmed: `type`, `security`, `pbk`, `fp`, `sni`, `sid`, `flow`, `encryption`

## Implementation Note

All configuration fields in the generated Xray config were implemented only after
verification against the official sources listed above. No fields were added
from memory or assumptions.
