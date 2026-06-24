# Security Policy

## Supported Versions

Only the latest release on the `main` branch receives security fixes.

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < latest | :x:               |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities privately:

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Fill in the advisory form with:
   - Description of the issue
   - Steps to reproduce
   - Affected version / commit
   - Suggested fix (if any)

You should receive a response within **7 days**. Reports are acknowledged
before any fix is published, and credit is given in the release notes unless
you prefer to remain anonymous.

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
