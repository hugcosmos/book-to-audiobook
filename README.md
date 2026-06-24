# Book to Audiobook

Convert ebooks (EPUB, MOBI, AZW3, PDF, TXT) to audiobooks (M4B / MP3) with chapter markers.

## Prerequisites

- Python >= 3.11
- [FFmpeg](https://ffmpeg.org/)
- [Calibre](https://calibre-ebook.com/) (optional, for MOBI/AZW3 — note: Calibre is GPLv3, separate from this project's MIT license)

## Install

Create an isolated environment first to avoid dependency conflicts:

**venv:**

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

**conda:**

```bash
conda create -n book2audio python=3.12 -y
conda activate book2audio
```

> Kokoro (the default provider on Intel Mac) needs Python ≤ 3.12 because
> onnxruntime has no macOS x86 wheel for Python 3.13.

Then choose one:

**From PyPI:**

```bash
pip install book-to-audiobook
```

**From source:**

```bash
git clone https://github.com/hugcosmos/book-to-audiobook.git
cd book-to-audiobook
pip install -e .
```

The default install pulls in a working local TTS engine:
**Qwen3 MLX on Apple Silicon**, **Kokoro on Intel Mac** (82M ONNX/CPU model,
100+ Chinese voices). No extra step needed — the provider is selected
automatically. Cloud providers (Edge/Baidu/iFlytek/ElevenLabs) only need API keys.

### Optional local providers

- **Supertonic** (ONNX, 31 languages): `pip install "book-to-audiobook[supertonic]"`
- **Kokoro on Apple Silicon**: `pip install "book-to-audiobook[kokoro]"`

## Quick Start

```bash
# Web UI
book2audio serve                          # http://localhost:8000

# CLI
book2audio chapters book.epub            # preview chapters
book2audio convert book.epub -c 1-10     # convert chapters 1-10
book2audio doc                            # full command reference
```

### `serve` vs `start.sh`

`book2audio serve` runs the server in the **foreground** with hot-reload — best for everyday use and development. To run it in the **background** (survives logout, logs to `.server.log`), use the helper scripts from the source checkout:

```bash
./start.sh     # background, reload off by default (B2A_RELOAD=1 to re-enable)
./stop.sh      # stop the background server (also sets HF_HUB_ENABLE_HF_TRANSFER=1)
```

`start.sh` automatically finds a Python that has the project dependencies installed (it checks your active venv/conda environment, then any `book2audio*` conda env) — the default `python3` usually won't have them. To override, set `PYTHON=/path/to/venv/bin/python`.

## CLI Reference

Run `book2audio doc` for detailed help, or `book2audio <command> --help`.

| Command | Description |
|---------|-------------|
| `convert` | Convert ebook to audiobook |
| `chapters` | List, view (`-t N`), and edit (`-e N`) chapters |
| `voice` | Manage voices (list/add/delete) |
| `config` | Manage configuration |
| `library` | Manage audiobook library |
| `serve` | Start web server |
| `doc` | Show full documentation |

### Convert

```bash
book2audio convert book.epub
book2audio convert book.epub -c 1-10 -p edge -v zh-CN-XiaoyiNeural -s 1.2
book2audio convert --book-id a74e947e332e -c 11-20
book2audio convert book.pdf -p qwen3_mlx -l en-US
```

### Chapters

```bash
book2audio chapters book.epub                    # list chapters
book2audio chapters book.epub -t 3               # view chapter 3 text
book2audio chapters book.epub -t 3 --head 20     # first 20 lines only
book2audio chapters book.epub -e 3               # edit chapter 3 in $EDITOR
book2audio chapters --book-id abc123 -e 3-5      # edit chapters 3-5
```

Edited text is saved separately (original never modified). Conversion uses edited text automatically. Edited chapters show `[edited]` tag.

## Web UI

Open http://localhost:8000. Drag & drop ebooks, select chapters, configure TTS, convert. Chapter text can be edited inline via the edit button on each chapter.

CLI and Web share the same library — books, edits, and conversion records persist across both.

## TTS Providers

### Cloud

| Provider | Setup | Cost |
|----------|-------|------|
| **Edge TTS** | No config needed | Free |
| **ElevenLabs** | `B2A_ELEVENLABS__API_KEY` | Paid |
| **Baidu TTS** | `B2A_BAIDU_TTS__API_KEY` + `B2A_BAIDU_TTS__SECRET_KEY` | Paid |
| **iFlytek TTS** | `B2A_IFLYTEK_TTS__APP_ID` + `B2A_IFLYTEK_TTS__API_KEY` + `B2A_IFLYTEK_TTS__API_SECRET` | Paid |

### Local — Qwen3 TTS via MLX (Apple Silicon)

On-device, no API key. Requires Apple Silicon Mac (M1+).

```bash
pip install hf-transfer
export HF_HUB_ENABLE_HF_TRANSFER=1
# China users: export HF_ENDPOINT=https://hf-mirror.com
```

| Model | Size | Quality | Memory |
|-------|------|---------|--------|
| `0.6B-CustomVoice-8bit` | Default | Good | ~0.6GB |
| `1.7B-CustomVoice-4bit` | Larger | Great | ~0.85GB |
| `1.7B-CustomVoice-8bit` | Larger | Great | ~1.7GB |

Set via Settings page or `book2audio config set qwen3_mlx.model_name <model>`.

### Local — Kokoro (ONNX / CPU, via kokoro-onnx)

Default on Intel Mac. Kokoro-82M is a compact 82M-parameter TTS model running on CPU via ONNX Runtime. The v1.1-zh model supports 100 Chinese voices + English.
On Apple Silicon, install via `pip install "book-to-audiobook[kokoro]"`.

Model files (~380MB) are downloaded automatically on first use to `~/.cache/book2audio/kokoro` (override with `B2A_KOKORO__MODEL_DIR`). 12 voices are curated by default (6 female, 6 male); all 100 Chinese voices are available via the Voice Manager.

### Local — Supertonic (ONNX)

On-device, 33 languages, no API key. Works on any platform (CPU/GPU).

```bash
pip install "book-to-audiobook[supertonic]"
# or directly: pip install supertonic
```

10 built-in voices (5 male, 5 female). Supports English, Japanese, Korean, Arabic, German, French, Spanish, Russian, and 22 more languages.

## Supported Languages

Availability depends on provider:

| Language | Edge | Qwen3 MLX | ElevenLabs | Supertonic | Kokoro | Baidu | iFlytek |
|----------|------|-----------|------------|------------|--------|-------|---------|
| Chinese (zh-CN) | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| English (en-US) | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Japanese | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Korean | ✓ | ✓ | ✓ | ✓ | — | — | — |
| French | ✓ | ✓ | ✓ | ✓ | — | — | — |
| German | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Spanish | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Russian | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Portuguese | — | ✓ | ✓ | ✓ | — | — | — |
| Italian | — | ✓ | ✓ | ✓ | — | — | — |
| + 22 more | — | — | — | ✓ | — | — | — |

## Configuration

Environment variables with `B2A_` prefix, or `book2audio config set`:

```bash
book2audio config show
book2audio config set tts.provider edge
book2audio config set qwen3_mlx.speed 1.2
```

| Variable | Default | Description |
|----------|---------|-------------|
| `B2A_HOST` | `0.0.0.0` | Server bind address |
| `B2A_PORT` | `8000` | Server port |
| `B2A_UPLOAD_DIR` | `uploads` | Ebook storage |
| `B2A_OUTPUT_DIR` | `output` | Audio output |

## Project Structure

```
app/               # FastAPI web app (routes, templates, static)
cli/               # Click CLI commands
core/              # converter, models, parsers, TTS providers, audio builder
config/            # Settings (pydantic-settings) + user_settings.json
uploads/           # Uploaded ebooks + chapter edits + meta.json
output/            # Generated audiobook files
```

## Disclaimer

**Edge TTS**: This project includes [edge-tts](https://github.com/rany2/edge-tts) as one TTS provider, which connects to Microsoft Edge's online text-to-speech service. This is not an official Microsoft API and may violate Microsoft's Terms of Service.

Users can choose alternative providers (Kokoro, Qwen3 MLX, Supertonic, ElevenLabs, Baidu, iFlytek) to avoid Edge TTS. Use at your own risk — the authors are not responsible for any violations of third-party terms of service.

## License

MIT — see [LICENSE](LICENSE).
