# Book to Audiobook

Convert ebooks (EPUB, MOBI, AZW3, PDF, TXT) to audiobooks (M4B / MP3) with chapter markers.

## Prerequisites

- Python >= 3.11
- [FFmpeg](https://ffmpeg.org/)
- [Calibre](https://calibre-ebook.com/) (optional, for MOBI/AZW3)

## Install

```bash
pip install book-to-audiobook
```

From source:

```bash
git clone https://github.com/hugcosmos/book-to-audiobook.git
cd book-to-audiobook
pip install -e .
```

## Quick Start

```bash
# Web UI
book2audio serve                          # http://localhost:8000

# CLI
book2audio chapters book.epub            # preview chapters
book2audio convert book.epub -c 1-10     # convert chapters 1-10
book2audio doc                            # full command reference
```

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
book2audio convert book.epub -c 1-10 -p edge-tts -v zh-CN-XiaoyiNeural -s 1.2
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

### Local — Supertonic (ONNX)

On-device, 33 languages, no API key. Works on any platform (CPU/GPU).

```bash
pip install supertonic
```

10 built-in voices (5 male, 5 female). Supports English, Japanese, Korean, Arabic, German, French, Spanish, Russian, and 24 more languages.

## Supported Languages

Availability depends on provider:

| Language | Edge | Qwen3 MLX | ElevenLabs | Supertonic | Baidu | iFlytek |
|----------|------|-----------|------------|------------|-------|---------|
| Chinese (zh-CN) | ✓ | ✓ | ✓ | — | ✓ | ✓ |
| English (en-US) | ✓ | ✓ | ✓ | ✓ | — | — |
| Japanese | ✓ | ✓ | ✓ | ✓ | — | — |
| Korean | ✓ | ✓ | ✓ | ✓ | — | — |
| French | ✓ | ✓ | ✓ | ✓ | — | — |
| German | ✓ | ✓ | ✓ | ✓ | — | — |
| Spanish | ✓ | ✓ | ✓ | ✓ | — | — |
| Russian | ✓ | ✓ | ✓ | ✓ | — | — |
| Portuguese | — | ✓ | ✓ | ✓ | — | — |
| Italian | — | ✓ | ✓ | ✓ | — | — |
| + 23 more | — | — | — | ✓ | — | — |

## Configuration

Environment variables with `B2A_` prefix, or `book2audio config set`:

```bash
book2audio config show
book2audio config set tts.provider edge-tts
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

Users can choose alternative providers (ElevenLabs, Baidu, iFlytek, or local Qwen3 MLX / Supertonic) to avoid Edge TTS. Use at your own risk — the authors are not responsible for any violations of third-party terms of service.

## License

MIT — see [LICENSE](LICENSE).
