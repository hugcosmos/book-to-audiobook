# Book to Audiobook

Convert ebooks (EPUB, MOBI, AZW3, PDF, TXT) to audiobooks (M4B / MP3) with chapter markers.

## Prerequisites

- Python >= 3.11
- [FFmpeg](https://ffmpeg.org/) (required for audio processing)
- [Calibre](https://calibre-ebook.com/) (optional, for MOBI/AZW3 support via `ebook-convert`)

## Install

```bash
# Clone the repository
git clone https://github.com/hugcosmos/book-to-audiobook.git
cd book-to-audiobook

# Install dependencies and the CLI tool
pip install -e .
```

## Usage

### Web Interface

```bash
# Start server
./start.sh

# Stop server
./stop.sh

# Or run directly
python -m app.main
```

Open http://localhost:8000 in your browser.

### Command Line Interface (CLI)

After installation, the `book2audio` command is available system-wide:

```bash
# Verify installation
book2audio --help
```

#### CLI Commands

| Command | Description |
|---------|-------------|
| `convert` | Convert ebook to audiobook |
| `chapters` | Preview book chapters (shows char count and estimated time) |
| `voice` | Manage voices (list/add/delete) |
| `config` | Manage configuration (show/get/set/reset) |
| `library` | Manage audiobook library (list books) |
| `serve` | Start web server |

#### Convert Options

| Option | Description |
|--------|-------------|
| `-c, --chapters` | Chapter range (e.g., `1-5,7,10-` for chapters 1-5, 7, 10+) |
| `-p, --provider` | TTS provider: `edge-tts`, `elevenlabs`, `baidu-tts`, `iflytek-tts`, `qwen3_mlx` |
| `-v, --voice` | Voice name |
| `-l, --language` | Language code (zh-CN, en-US, ja-JP, etc.) |
| `-s, --speed` | Speech speed (0.5-2.0) |
| `--model-path` | Local model path (for qwen3_mlx provider) |
| `--book-id` | Add output to existing library book (shares directory with web app) |

#### CLI Examples

```bash
# Convert entire book with default settings
book2audio convert /path/to/book.pdf

# Convert specific chapters
book2audio convert book.epub -c 1-10

# Use specific provider and voice
book2audio convert book.pdf -p edge-tts -v zh-CN-XiaoyiNeural -s 1.2

# Use local qwen3_mlx model (avoid repeated downloads)
book2audio convert book.epub -p qwen3_mlx --model-path ~/.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit

# Add to existing library book (shares output with web app, preserves cover)
book2audio convert new_chapters.pdf --book-id a74e947e332e -c 11-20

# Preview chapters (shows char count and estimated conversion time)
book2audio chapters my_book.pdf

# List available voices
book2audio voice list

# Add custom voice
book2audio voice add --provider elevenlabs --voice-id "xxx" --name "My Voice" --language en-US

# Configure settings
book2audio config show
book2audio config set tts.provider edge-tts
book2audio config set qwen3_mlx.model_path "/path/to/local/model"

# List library books (to get book_id)
book2audio library list

# Start web server
book2audio serve
```

#### CLI Quick Start Example

```bash
# 1. Clone and install
git clone https://github.com/hugcosmos/book-to-audiobook.git
cd book-to-audiobook
pip install -e .

# 2. Check available voices
book2audio voice list

# 3. Configure default provider (optional)
book2audio config set tts.provider edge-tts

# 4. Set local model path to avoid repeated downloads (qwen3_mlx users)
book2audio config set qwen3_mlx.model_path "~/.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"

# 5. Preview book chapters
book2audio chapters my_book.pdf

# 6. Convert to audiobook
book2audio convert my_book.pdf --chapters 1-10 --speed 1.2

# 7. Find output files
# Output saved to: output/my_book/audiobook.m4b and audiobook.mp3
```

#### CLI and Web App Integration

CLI and Web app share the same configuration and output directory:
- Configuration: `config/user_settings.json`
- Output directory: `output/`
- Use `--book-id` flag to add CLI conversions to existing web app books
- CLI conversions inherit book metadata (title, author, cover) when using `--book-id`

### Workflow

1. **Upload** — Drag & drop an ebook on the library page
2. **Select chapters** — Click the book card, pick chapters to convert
3. **Configure TTS** — Choose provider, language, voice, speed
4. **Convert** — Progress shows inline, no page navigation
5. **Download** — Files appear in Generated Files after completion

Conversions are saved — restart the server and all books/history remain unless you delete them.


## TTS Providers

### Cloud Providers (require API keys)

| Provider | Env Variables | Description |
|----------|--------------|-------------|
| **Edge TTS** | None needed | Microsoft Edge online TTS. Free, no API key.  |
| **ElevenLabs** | `B2A_ELEVENLABS__API_KEY` | High-quality multilingual TTS. Get key at [elevenlabs.io](https://elevenlabs.io). |
| **Baidu TTS** | `B2A_BAIDU_TTS__API_KEY`, `B2A_BAIDU_TTS__SECRET_KEY` | Baidu speech synthesis. Get credentials at [cloud.baidu.com](https://cloud.baidu.com). |
| **iFlytek TTS** | `B2A_IFLYTEK_TTS__APP_ID`, `B2A_IFLYTEK_TTS__API_KEY`, `B2A_IFLYTEK_TTS__API_SECRET` | iFlytek speech synthesis. Get credentials at [xfyun.cn](https://xfyun.cn). |

### Local Models (no API key needed)

#### Qwen3 TTS via MLX — Apple Silicon

Runs entirely on-device. Requires Apple Silicon Mac (M1/M2/M3/M4).

```bash
# Faster model downloads (parallel transfer)
pip install hf-transfer

# China users: use HuggingFace mirror for faster downloads
export HF_ENDPOINT=https://hf-mirror.com

# Enable parallel downloads
export HF_HUB_ENABLE_HF_TRANSFER=1
```

Available models (configured in Settings page or `config/user_settings.json`):

| Model | Quantization | Quality | Speed | Memory |
|-------|-------------|---------|-------|--------|
| `0.6B-CustomVoice-4bit` | 4-bit | Good | Fastest | ~0.3GB |
| `0.6B-CustomVoice-8bit` | 8-bit | Good | Fast | ~0.6GB |
| `1.7B-CustomVoice-4bit` | 4-bit | Great | Fast | ~0.85GB |
| `1.7B-CustomVoice-8bit` | 8-bit | Great | Fast | ~1.7GB |
| `1.7B-CustomVoice-bf16` | bf16 | Best | Slower | ~3.4GB |

Set model in `config/user_settings.json`:

```json
{
  "qwen3_mlx": {
    "model_name": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
    "speed": 1.2
  }
}
```

## Configuration

All settings use the `B2A_` env prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `B2A_HOST` | `0.0.0.0` | Server bind address |
| `B2A_PORT` | `8000` | Server port |
| `B2A_UPLOAD_DIR` | `uploads` | Uploaded ebook storage |
| `B2A_OUTPUT_DIR` | `output` | Generated audio output |
| `B2A_MAX_UPLOAD_SIZE_MB` | `500` | Max upload file size |
| `B2A_FFMPEG_PATH` | `ffmpeg` | Path to ffmpeg binary |
| `B2A_FFPROBE_PATH` | `ffprobe` | Path to ffprobe binary |

Set via environment variables or `.env` file:

```bash
export B2A_PORT=8000
./start.sh
```

## Supported Languages

Chinese, English (US/UK), Japanese, Korean, French, German, Spanish, Russian.

## Project Structure

```
app/               # FastAPI web app
  main.py          # Entry point
  routes/          # HTTP routes
  templates/       # Jinja2 HTML templates
  static/          # CSS + JS
core/              # Core logic
  converter.py     # Conversion orchestrator + state persistence
  models.py        # Pydantic data models
  book_parser/     # EPUB, MOBI, PDF, TXT parsers
  tts_provider/    # TTS providers (Edge, Baidu, iFlytek, ElevenLabs, Qwen3 MLX)
  audio_builder/   # FFmpeg audio assembly (M4B/MP3)
  text_processor/  # Text cleaning + chunking
config/            # Settings (pydantic-settings)
uploads/           # Uploaded ebooks + meta.json state files
output/            # Generated audiobook files
```

## Dependencies & Licensing

All dependencies use permissive licenses compatible with MIT:

| License | Packages |
|---------|----------|
| MIT | fastapi, pydantic, pydantic-settings, beautifulsoup4, pdfplumber, pydub, sentencex, mlx-audio |
| BSD-3-Clause | uvicorn, jinja2, lxml, httpx, websockets, soundfile |
| Apache-2.0 | python-multipart, aiofiles, hf-transfer |
| LGPL-3.0 | edge-tts |

EPUB parsing uses a built-in parser (zipfile + lxml) — no ebooklib dependency.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

**Edge TTS**: This project includes [edge-tts](https://github.com/rany2/edge-tts) as one TTS provider, which connects to Microsoft Edge's online text-to-speech service. This is not an official Microsoft API and may violate Microsoft's Terms of Service. 

**Alternative Providers**: Users can choose alternative TTS providers (ElevenLabs, Baidu TTS, iFlytek TTS, or local Qwen3 MLX models) to avoid using Edge TTS. See the [TTS Providers](#tts-providers) section for configuration details.

**Use at your own risk**: The authors are not responsible for any violations of third-party terms of service.
