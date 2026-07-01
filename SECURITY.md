# Security Policy

## Supported Versions

Currently, only the latest release of **GFN Sync** is actively supported for security updates. 

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

Security and privacy are taken seriously in this project, especially since the tool parses local caches and binary VDF files on the user's system. 

If you discover a security vulnerability within GFN Sync, please **do not** open a public issue. Instead, please report it privately.

**How to report:**
1. Send an email to [vincentredor@gmail.com] or reach out via direct message on X/Twitter (@supernebuleux).
2. Include a detailed description of the vulnerability, the steps to reproduce it, and the potential impact.

You should receive a response within 48 hours. If the vulnerability is confirmed, a patch will be developed and released as quickly as possible.

### Out of Scope
Please note that the following are generally considered out of scope for security reports:
- Issues inherent to how SteamOS or Steam manages its `shortcuts.vdf` file permissions.
- Vulnerabilities located within the upstream official NVIDIA GeForce NOW client or community Flatpaks, as we do not control those applications.
- Physical access attacks (i.e., if an attacker already has physical access to your unlocked Steam Deck).

Thank you for helping keep the community secure!
