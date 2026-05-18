from __future__ import annotations

import asyncio
import importlib.metadata
import shutil
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from config.settings import settings
from config.user_settings import get_user_settings_dict, load_user_settings
from core.book_parser.parser_factory import get_parser

load_user_settings()
from core.tts_provider.tts_factory import get_tts_provider
from core.text_processor import TextProcessor
from core.audio_builder import AudioBuilder
from core.models import BookMetadata, Chapter, ConversionRecord, OutputFile, TTSConfig

console = Console()


def _safe_filename(name: str) -> str:
    for ch in ('/', '\\', ':', '*', '?', '"', '<', '>', '|'):
        name = name.replace(ch, '-')
    return name[:200]


def _combined_label(selected: list, book_title: str, total_chapters: int) -> str:
    n = len(selected)
    if n == total_chapters:
        return book_title
    if n == 1:
        return f"{book_title} - {selected[0].title}"
    indices = sorted(ch.index for ch in selected)
    is_contiguous = indices == list(range(indices[0], indices[0] + n))
    if is_contiguous:
        return f"{book_title} - {selected[0].title}~{selected[-1].title}"
    return f"{book_title} - {selected[0].title}等{n}章"


def _ensure_registered(input_path: Path) -> tuple[BookMetadata, dict[int, str]]:
    """Ensure book is in uploads library. Return (BookMetadata, text_map)."""
    from core.converter import Converter

    converter = Converter()
    resolved = input_path.resolve()

    # Check if already registered by samefile (handles symlinks, hardlinks)
    for book in converter._books.values():
        book_path = Path(book.file_path)
        if book_path.exists() and resolved.exists():
            try:
                if book_path.samefile(resolved):
                    parser = get_parser(book.file_path)
                    text_map = {ch.index: ch.text for ch in parser.get_chapters()}
                    return book, text_map
            except OSError:
                if book_path.resolve() == resolved:
                    parser = get_parser(book.file_path)
                    text_map = {ch.index: ch.text for ch in parser.get_chapters()}
                    return book, text_map

    # Register new book
    book_id = uuid.uuid4().hex[:12]
    upload_dir = settings.upload_dir / book_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / input_path.name
    shutil.copy2(str(input_path), str(dest))

    parser = get_parser(str(dest))
    metadata = parser.get_metadata()
    metadata.id = book_id
    metadata.file_path = str(dest)
    chapters = parser.get_chapters()
    metadata.chapters = chapters
    text_map = {ch.index: ch.text for ch in chapters}

    if hasattr(parser, "extract_cover"):
        cover_path = parser.extract_cover(upload_dir)
        if cover_path:
            metadata.cover_path = cover_path

    converter.add_book(metadata)
    console.print(f"[dim]Registered book: {metadata.title} (id: {book_id})[/dim]")
    return metadata, text_map


@click.group()
@click.version_option(version=importlib.metadata.version("book-to-audiobook"))
def cli():
    pass


@cli.command(help="""Convert an ebook to audiobook.

Supported formats:
  - EPUB, PDF, TXT: Always supported
  - MOBI, AZW3: Require Calibre (ebook-convert) to be installed

INPUT_FILE: Path to your ebook file (required). Can be:
  - Relative path: book.pdf (if file is in current directory)
  - Absolute path: /Users/you/Downloads/book.pdf
  - Quoted path with spaces: "My Book.pdf"

Options:
  -c, --chapters     Chapter range (e.g., '1-5,7,10-' for chapters 1-5, 7, 10+)
  -p, --provider     TTS provider: edge-tts, elevenlabs, baidu-tts, iflytek-tts, qwen3_mlx
  -v, --voice        Voice name (run 'book2audio voice list' for available voices)
  -l, --language     Language code (zh-CN, en-US, ja-JP, etc.)
  -s, --speed        Speech speed (0.5-2.0, defaults to 1.0)
  --model-path       Local model path (only for qwen3_mlx provider)
  --book-id          Add output to existing library book (share directory with web app)

Examples:
  # Convert entire book with default settings
  book2audio convert /path/to/your/book.pdf

  # Convert specific chapters
  book2audio convert book.epub -c 1-10

  # Use specific provider and voice
  book2audio convert book.pdf -p edge-tts -v zh-CN-XiaoyiNeural

  # Add to existing library book (share output with web app)
  book2audio convert --book-id a74e947e332e

  # Use local qwen3_mlx model
  book2audio convert book.epub -p qwen3_mlx --model-path ~/.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit""")
@click.argument("input_file", required=False, type=click.Path(exists=True))
@click.option("--chapters", "-c", default=None, help="Chapter range to convert (e.g., '1-5,7,10-' for chapters 1-5, 7, and 10 onwards)")
@click.option("--provider", "-p", default=None, help="TTS provider: edge-tts, elevenlabs, baidu-tts, iflytek-tts, qwen3_mlx")
@click.option("--voice", "-v", default="vivian", help="Voice name (use 'book2audio voice list' to see available voices)")
@click.option("--language", "-l", default="zh-CN", help="Language code (e.g., zh-CN, en-US, ja-JP)")
@click.option("--speed", "-s", type=float, default=None, help="Speech speed (0.5-2.0, default: 1.0)")
@click.option("--model-path", default=None, help="Path to local model directory (for qwen3_mlx provider)")
@click.option("--book-id", default=None, help="Existing book ID (convert without file path)")
def convert(input_file, chapters, provider, voice, language, speed, model_path, book_id):
    if not input_file and not book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id[/red]")
        raise SystemExit(1)

    if input_file and book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id, not both[/red]")
        raise SystemExit(1)

    input_path = Path(input_file) if input_file else None
    if input_path:
        console.print(f"\n[bold blue]📚 Input:[/bold blue] {input_path.resolve()}")

    from core.converter import Converter
    converter = Converter()

    if book_id:
        book = converter.get_book(book_id)
        if not book:
            console.print(f"[red]Book not found: {book_id}[/red]")
            raise SystemExit(1)
        console.print(f"[bold blue]📁 Output:[/bold blue] Using existing library book: {book_id}")
        # Reload text from parser (meta.json strips text)
        parser = get_parser(book.file_path)
        text_map = {ch.index: ch.text for ch in parser.get_chapters()}
    else:
        book, text_map = _ensure_registered(input_path)

    all_chapters = book.chapters
    console.print(f"[bold blue]📖 Chapters:[/bold blue] {len(all_chapters)} found")

    if chapters:
        selected_indices = _parse_chapter_range(chapters, len(all_chapters))
        selected_chapters = [all_chapters[i] for i in selected_indices]
        console.print(f"[bold blue]✅ Selected:[/bold blue] Chapters {chapters} ({len(selected_chapters)} chapters)")
    else:
        selected_chapters = all_chapters
        console.print(f"[bold blue]✅ Selected:[/bold blue] All {len(selected_chapters)} chapters")

    effective_provider = provider or settings.tts.provider
    console.print(f"[bold blue]🔊 Provider:[/bold blue] {effective_provider}")
    console.print(f"[bold blue]🗣️ Voice:[/bold blue] {voice}")
    console.print(f"[bold blue]🌐 Language:[/bold blue] {language}")

    if speed is None:
        if effective_provider == "qwen3_mlx":
            speed = settings.qwen3_mlx.speed
        else:
            speed = 1.0
    console.print(f"[bold blue]⚡ Speed:[/bold blue] {speed}x")

    config = TTSConfig(voice=voice, language=language, speed=speed)
    if model_path:
        config.model_path = model_path
        console.print(f"[bold blue]📦 Model Path:[/bold blue] {model_path}")

    tts = get_tts_provider(provider=effective_provider, config=config)
    text_processor = TextProcessor()

    book_title = book.title or (input_path.stem if input_path else "audiobook")
    book_author = book.author or ""
    cover_path = book.cover_path if book.cover_path else None

    output_dir = settings.output_dir / book.id
    output_dir.mkdir(parents=True, exist_ok=True)

    chapter_files = []
    audio_builder = AudioBuilder()

    async def _convert_all():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task(f"Converting {len(selected_chapters)} chapters...", total=len(selected_chapters))

            for i, chapter in enumerate(selected_chapters):
                progress.update(task, advance=1, description=f"Chapter {chapter.index}: {chapter.title[:30]}...")

                chapter_text = chapter.text or text_map.get(chapter.index, "")
                cleaned_text = text_processor.clean(chapter_text)

                temp_mp3 = output_dir / f"_tmp_{chapter.index:04d}.mp3"
                await tts.synthesize(cleaned_text, temp_mp3)
                named_mp3 = output_dir / _safe_filename(f"{book_title} - {chapter.title}.mp3")
                temp_mp3.rename(named_mp3)
                chapter_files.append((chapter, named_mp3))

    asyncio.run(_convert_all())

    output_files: list[OutputFile] = []

    # Per-chapter MP3s
    for chapter, ch_path in chapter_files:
        output_files.append(OutputFile(
            path=str(ch_path), filename=ch_path.name, type="chapter", title=chapter.title,
        ))

    # Combined m4b + mp3
    combined_label = _combined_label(selected_chapters, book_title, len(all_chapters))
    m4b_path = output_dir / _safe_filename(f"{combined_label}.m4b")
    mp3_path = output_dir / _safe_filename(f"{combined_label}.mp3")

    audio_builder.build_m4b(chapter_files, m4b_path, book_title=book_title, book_author=book_author, cover_path=cover_path)
    output_files.append(OutputFile(path=str(m4b_path), filename=m4b_path.name, type="m4b"))

    audio_builder.build_combined_mp3(chapter_files, mp3_path)
    output_files.append(OutputFile(path=str(mp3_path), filename=mp3_path.name, type="mp3"))

    # Persist conversion record
    record = ConversionRecord(
        selected_chapters=[ch.index for ch in selected_chapters],
        output_files=output_files,
    )
    book.conversions.append(record)
    converter.save_book(book)

    console.print("\n[bold green]✅ Conversion complete![/bold green]")
    console.print(f"\n[bold blue]📁 Output directory:[/bold blue] {output_dir.resolve()}")
    console.print(f"[bold blue]Files generated:[/bold blue]")
    for of in output_files:
        console.print(f"  • {of.filename}")
    console.print(f"\n[bold blue]Quick actions:[/bold blue]")
    console.print(f"  Open directory: [cyan]open {output_dir}[/cyan]")


@cli.command(help="Manage application configuration.\n\nCommands:\n  show          Show all configuration\n  get <key>     Get a specific configuration value\n  set <key> <value>  Set a configuration value\n  reset <key>   Reset a configuration value to default\n\nExamples:\n  book2audio config show\n  book2audio config get tts.provider\n  book2audio config set tts.provider edge-tts")
@click.argument("command")
@click.argument("key", required=False)
@click.argument("value", required=False)
def config(command, key=None, value=None):
    from config.user_settings import get_user_settings_dict, save_user_settings
    
    if command == "show":
        import json
        data = get_user_settings_dict()
        console.print(json.dumps(data, indent=2, ensure_ascii=False))
    elif command == "get":
        if key:
            data = get_user_settings_dict()
            keys = key.split(".")
            result = data
            for k in keys:
                if isinstance(result, dict) and k in result:
                    result = result[k]
                else:
                    result = None
                    break
            console.print(result)
        else:
            console.print("Usage: book2audio config get <key>")
    elif command == "set":
        if key and value is not None:
            data = get_user_settings_dict()
            keys = key.split(".")
            current = data
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value
            save_user_settings(data)
            console.print(f"[green]Set {key} = {value}[/green]")
        else:
            console.print("Usage: book2audio config set <key> <value>")
    elif command == "reset":
        if key:
            data = get_user_settings_dict()
            keys = key.split(".")
            current = data
            for k in keys[:-1]:
                if k not in current:
                    console.print(f"Key not found: {key}")
                    return
                current = current[k]
            if keys[-1] in current:
                del current[keys[-1]]
                save_user_settings(data)
                console.print(f"[green]Reset {key}[/green]")
            else:
                console.print(f"Key not found: {key}")
        else:
            console.print("Usage: book2audio config reset <key>")
    else:
        console.print(f"Unknown command: {command}")


@cli.command(help="Manage TTS voices. List, add, or delete custom voices.\n\nCommands:\n  list                  List all available voices\n  add                   Add a custom voice\n  delete <name>         Delete a custom voice by name\n  show <name>           Show details of a custom voice\n\nAdd Options:\n  --provider, -p        TTS provider: elevenlabs, baidu-tts, iflytek-tts\n  --voice-id            Voice ID from provider (required)\n  --name                Display name for the voice (required)\n  --language, -l        Language code (e.g., zh-CN)\n  --gender              Voice gender: male, female, neutral\n\nExamples:\n  book2audio voice list\n  book2audio voice add --provider elevenlabs --voice-id \"xxx\" --name \"My Voice\" --language en-US\n  book2audio voice delete \"My Voice\"")
@click.argument("command")
@click.argument("name", required=False)
@click.option("--provider", "-p", default=None)
@click.option("--voice-id", default=None)
@click.option("--language", "-l", default=None)
@click.option("--gender", default=None)
def voice(command, name, provider, voice_id, language, gender):
    from config.user_settings import get_custom_voices, add_custom_voice, delete_custom_voice
    from core.tts_provider.voices import VOICE_REGISTRY
    
    if command == "list":
        console.print("\n[bold blue]Available Voices:[/bold blue]")
        for prov, voices in VOICE_REGISTRY.items():
            if voices:
                console.print(f"\n[bold]{prov}:[/bold]")
                for v in voices:
                    marker = "⭐" if v.custom else "•"
                    console.print(f"  {marker} {v.name} ({v.language})")
    elif command == "add":
        if not (name and provider and voice_id):
            console.print("Usage: book2audio voice add --provider <provider> --voice-id <id> --name <name>")
            return
        voice_data = {
            "id": voice_id,
            "name": name,
            "language": language or "zh-CN",
        }
        if gender:
            voice_data["gender"] = gender
        try:
            add_custom_voice(provider, voice_data)
            console.print(f"[green]Added voice: {name}[/green]")
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
    elif command == "delete":
        if not name:
            console.print("Usage: book2audio voice delete <name>")
            return
        found = False
        for prov in VOICE_REGISTRY.keys():
            voices = get_custom_voices(prov)
            for v in voices:
                if v["name"] == name:
                    delete_custom_voice(prov, v["id"])
                    console.print(f"[green]Deleted voice: {name}[/green]")
                    found = True
                    break
            if found:
                break
        if not found:
            console.print(f"[red]Voice not found: {name}[/red]")
    elif command == "show":
        if not name:
            console.print("Usage: book2audio voice show <name>")
            return
        for prov in VOICE_REGISTRY.keys():
            voices = get_custom_voices(prov)
            for v in voices:
                if v["name"] == name:
                    console.print(v)
                    return
        console.print(f"[red]Voice not found: {name}[/red]")
    else:
        console.print(f"Unknown command: {command}")


@cli.command(help="Preview chapters in an ebook before conversion.\n\nArguments:\n  INPUT_FILE    Path to the input ebook file (EPUB, PDF, MOBI, TXT)\n\nOptions:\n  --book-id     Show chapters for an existing library book\n\nExample:\n  book2audio chapters my_book.pdf\n  book2audio chapters --book-id a74e947e332e")
@click.argument("input_file", required=False, type=click.Path(exists=True))
@click.option("--book-id", default=None, help="Existing book ID (skip file upload)")
def chapters(input_file, book_id):
    if not input_file and not book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id[/red]")
        raise SystemExit(1)

    if input_file and book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id, not both[/red]")
        raise SystemExit(1)

    if book_id:
        from core.converter import Converter
        converter = Converter()
        book = converter.get_book(book_id)
        if not book:
            console.print(f"[red]Book not found: {book_id}[/red]")
            raise SystemExit(1)
        display_name = book.title
    else:
        input_path = Path(input_file)
        book, _ = _ensure_registered(input_path)
        display_name = input_path.name

    chapter_list = book.chapters

    console.print(f"\n[bold blue]📖 Chapters in {display_name}:[/bold blue]")

    total_chars = 0
    total_duration = 0.0
    max_num_width = len(str(len(chapter_list)))

    for chapter in chapter_list:
        char_count = chapter.char_count if chapter.char_count else (len(chapter.text) if chapter.text else 0)
        total_chars += char_count

        total_duration += chapter.estimated_duration_seconds

        duration_min = chapter.estimated_duration_seconds / 60
        if duration_min < 1:
            time_str = f"~{max(1, round(duration_min * 60))}s"
        else:
            time_str = f"~{round(duration_min)} min"

        num = chapter.index + 1
        console.print(f"\n[bold]{num:>{max_num_width}}. {chapter.title}[/bold]")
        console.print(f"    {char_count:,} chars · {time_str}")

    if total_duration < 60:
        total_time_str = f"{total_duration:.0f}s"
    elif total_duration < 3600:
        total_time_str = f"{total_duration / 60:.1f} min"
    else:
        hours = int(total_duration // 3600)
        mins = (total_duration % 3600) / 60
        total_time_str = f"{hours}h {mins:.0f}min"

    console.print(f"\n[bold green]📊 Summary:[/bold green]")
    console.print(f"  Total chapters: {len(chapter_list)}")
    console.print(f"  Total characters: {total_chars:,}")
    console.print(f"  Estimated conversion time: {total_time_str}")


@cli.group(help="Manage your audiobook library.")
def library():
    pass


@library.command(help="List all books in the library.")
def list():
    from core.converter import Converter
    
    converter = Converter()
    books = converter.get_all_books()
    
    if not books:
        console.print("[yellow]No books found in library.[/yellow]")
        return
    
    console.print("\n[bold blue]📚 Library Books:[/bold blue]")
    console.print("-" * 70)
    console.print(f"{'ID':<14}  {'Title':<40}  {'Chapters'}")
    console.print("-" * 70)

    for book in books:
        book_id = book.id
        title = book.title[:38] + "..." if len(book.title) > 40 else book.title
        console.print(f"{book_id:<14}  {title:<40}  {len(book.chapters)}")

    console.print("-" * 70)
    console.print(f"\n[bold green]Total: {len(books)} books[/bold green]")
    console.print("\n[bold blue]Usage:[/bold blue]")
    console.print(f"  Convert existing book: book2audio convert --book-id <BOOK_ID>")
    console.print(f"  View chapters:         book2audio chapters --book-id <BOOK_ID>")


@library.command(help="Delete a book from the library by ID.")
@click.argument("book_id")
def delete(book_id):
    import shutil
    from core.converter import Converter

    converter = Converter()
    book = converter.get_book(book_id)
    if not book:
        console.print(f"[red]Book not found: {book_id}[/red]")
        raise SystemExit(1)

    # Remove upload directory
    upload_dir = settings.upload_dir / book_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)

    # Remove output directory
    output_dir = settings.output_dir / book_id
    if output_dir.exists():
        shutil.rmtree(output_dir)

    converter.delete_book(book_id)
    console.print(f"[green]Deleted: {book.title} ({book_id})[/green]")


@cli.command(help="Start the web server to access the GUI interface.")
def serve():
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)


def _parse_chapter_range(chapter_str, total_chapters):
    indices = []
    parts = chapter_str.split(",")
    for part in parts:
        if "-" in part:
            start, end = part.split("-")
            start = int(start) - 1 if start else 0
            end = int(end) if end else total_chapters
            indices.extend(range(start, min(end, total_chapters)))
        else:
            indices.append(int(part) - 1)
    return sorted(set(indices))


if __name__ == "__main__":
    cli()