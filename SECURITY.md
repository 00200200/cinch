# Security & Trust Policy

## 🔒 Local-First, Zero Telemetry

`cinch` is strictly a local developer tool designed to translate and attach skills and agent configurations between AI developer harnesses on your local filesystem.

- **Zero Network Activity:** Cinch makes no outbound network requests, phone-home calls, or telemetry transmissions during execution.
- **No Scraping or Exfiltration:** It reads only your specified local config directories (or local checkout folders) and writes directly to your local project workspace.
- **No Destructive Overwrites:** By default, Cinch checks if target files exist. If a destination file is already present, Cinch refuses to overwrite it (`outcome: "exists"`), preserving your hand-crafted configurations.

---

## 🛡️ Reporting Security Issues

If you discover a potential security vulnerability or file safety flaw in Cinch:

1. **Private Disclosure:** Please report it privately by opening a [GitHub Security Advisory](https://github.com/00200200/cinch/security/advisories/new).
2. **Issue Tracker:** For non-sensitive bugs, feel free to open a standard GitHub issue.

Please describe the environment, the exact CLI command run, and the unexpected behavior. We investigate all security and file-integrity reports promptly.
