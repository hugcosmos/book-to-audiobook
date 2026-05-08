# Book to Audiobook

Convert ebooks (EPUB, MOBI, AZW3, PDF, TXT) to audiobooks (M4B / MP3) with chapter markers. Uses Edge TTS — free, no API key needed.

## Prerequisites

- Python >= 3.11
- [FFmpeg](https://ffmpeg.org/) (required for audio processing)
- [Calibre](https://calibre-ebook.com/) (optional, for MOBI/AZW3 support via `ebook-convert`)

## Install

```bash
git clone https://github.com/hugcosmos/book-to-audiobook.git && cd book-to-audiobook
pip install -e .
```

## Usage

```bash
# Start server
./start.sh

# Stop server
./stop.sh

# Or run directly
python -m app.main
```

Open http://localhost:8000 in your browser.

### Workflow

1. **Upload** — Drag & drop an ebook on the library page
2. **Select chapters** — Click the book card, pick chapters to convert
3. **Configure TTS** — Choose language, voice, speed, output format
4. **Convert** — Progress shows inline, no page navigation
5. **Download** — Files appear in conversion history after completion

Conversions are persisted — restart the server and all books/history remain.

## Configuration

All settings use the `B2A_` env prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `B2A_HOST` | `0.0.0.0` | Server bind address |
| `B2A_PORT` | `8000` | Server port |
| `B2A_UPLOAD_DIR` | `uploads` | Uploaded ebook storage |
| `B2A_OUTPUT_DIR` | `output` | Generated audio output |
| `B2A_MAX_UPLOAD_SIZE_MB` | `500` | Max upload file size |
| `B2A_DEFAULT_VOICE` | `zh-CN-XiaoxiaoNeural` | Default TTS voice |
| `B2A_FFMPEG_PATH` | `ffmpeg` | Path to ffmpeg binary |
| `B2A_FFMPEG_PATH` | `ffprobe` | Path to ffprobe binary |

Set via environment variables or `.env` file:

```bash
export B2A_PORT=9000
./start.sh
```

## Supported Languages

Chinese, English (US/UK), Japanese, Korean, French, German, Spanish, Russian — each with multiple voice options.

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
  tts_provider/    # Edge TTS integration
  audio_builder/   # FFmpeg audio assembly (M4B/MP3)
  text_processor/  # Text cleaning
config/            # Settings
uploads/           # Uploaded ebooks + meta.json state files
output/            # Generated audiobook files
```

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE).

This project uses [edge-tts](https://github.com/rany2/edge-tts) which connects to Microsoft Edge's online text-to-speech service. This is not an official Microsoft API and may violate Microsoft's Terms of Service. Use at your own risk.
