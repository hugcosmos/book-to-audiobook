# Security Policy

## Supported Versions

Only the latest release on the `main` branch receives security fixes.

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < latest | :x:               |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, open a **draft security advisory** (GitHub's private vulnerability
reporting channel):

1. Go to the repository's **Security and quality** tab → **Security advisories**
   section → **Open a draft security advisory**.
   Direct link: <https://github.com/hugcosmos/book-to-audiobook/security/advisories/new>
2. Fill in:
   - **Title** — short summary of the issue
   - **Description** — what the vulnerability is
   - **Steps to reproduce** — minimal reproduction
   - **Affected version / commit**
   - **Suggested fix** (if any)

Draft advisories are private — only repository maintainers can see them
until published. You should receive a response within **7 days**. Credit is
given in the release notes unless you prefer to remain anonymous.

## Scope

This project converts ebooks to audiobooks and exposes an optional local
FastAPI web UI. Security-relevant issues include but are not limited to:

- Path traversal in file upload / download / conversion
- Command injection via subprocess calls (ffmpeg, ebook tools)
- Server-side request forgery (SSRF) via TTS provider HTTP calls
- Secret leakage (API keys for TTS providers) in logs or responses
- Arbitrary code execution through crafted EPUB / PDF / MOBI input

## Out of Scope

- Self-hosted instances exposed to the public internet without auth — this
  project ships a local-only UI by default and is not designed to be
  internet-facing.
- Vulnerabilities in third-party dependencies — report them upstream. We
  track them via Dependabot and `pip-audit`.
