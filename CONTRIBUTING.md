# Contributing to book-to-audiobook

Thanks for considering a contribution! This document explains how to
propose changes, report bugs, and work on the codebase.

## Before You Start

- Open an issue first for anything beyond a typo or trivial fix. This
  avoids duplicate work and lets us discuss the approach before code is
  written.
- Keep the MIT license in mind — code you submit will be released under
  the same license.

## Development Setup

Requirements:

- Python >= 3.11
- `ffmpeg` installed and on `PATH` (used for audio conversion)

```bash
git clone https://github.com/hugcosmos/book-to-audiobook.git
cd book-to-audiobook
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -r requirements.txt
```

Run the web UI locally:

```bash
./start.sh
```

Run the CLI:

```bash
book2audio --help
```

## Making Changes

1. Fork the repository and create a feature branch from `main`:

   ```bash
   git checkout -b feat/short-description
   ```

2. Make your change. Keep commits focused — one logical change per commit
   with a clear message (e.g. `feat: add voice X for provider Y`,
   `fix: prevent path traversal in upload route`).

3. Verify your change locally:

   - The web UI starts without errors.
   - Any relevant CLI command still works.
   - If you touch a TTS provider, test that provider end-to-end with a
     short input file.

4. Do **not** commit secrets, API keys, or `.env` files. The CI runs
   `gitleaks` — leaked credentials will block the PR.

5. If your change adds or changes a dependency, update **both**
   `pyproject.toml` and `requirements.txt` (they must stay in sync).

6. Push your branch and open a Pull Request against `main`. Fill in the
   PR template.

## Pull Request Checks

Every PR runs:

- **CodeQL** — static analysis for Python
- **pip-audit** — known vulnerabilities in dependencies
- **gitleaks** — secret/credential scan

All three must pass before merge.

## Code Style

- Follow the style of surrounding code.
- Keep functions focused; prefer composition over deep nesting.
- Type hints are welcome where they aid readability, but not required
  everywhere.

## Reporting Bugs

Use the **Bug report** issue template. Include:

- OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs (redact any API keys first)

## Reporting Security Issues

See [SECURITY.md](SECURITY.md). Do **not** open a public issue for
security vulnerabilities.
