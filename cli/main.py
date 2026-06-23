from __future__ import annotations

import asyncio
import importlib.metadata
import shutil
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.text import Text

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


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{max(1, round(seconds))}s"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    hours = int(seconds // 3600)
    mins = (seconds % 3600) / 60
    return f"{hours}h {mins:.0f}min"


def _resolve_book(input_file, book_id):
    """Resolve book from either input_file or book_id. Returns (book, converter)."""
    from core.converter import Converter

    if not input_file and not book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id[/red]")
        raise SystemExit(1)

    if input_file and book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id, not both[/red]")
        raise SystemExit(1)

    converter = Converter()

    if book_id:
        book = converter.get_book(book_id)
        if not book:
            console.print(f"[red]Book not found: {book_id}[/red]")
            raise SystemExit(1)
        return book, converter

    input_path = Path(input_file)
    book, _ = _ensure_registered(input_path)
    return book, converter


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


# ── CLI Group ──────────────────────────────────────────────────────────

@click.group()
@click.version_option(version=importlib.metadata.version("book-to-audiobook"))
def cli():
    """book2audio — Convert ebooks to audiobooks with TTS."""
    pass


# ── convert ────────────────────────────────────────────────────────────

@cli.command(help="""Convert an ebook to audiobook.

Supported formats: EPUB, PDF, TXT (always), MOBI/AZW3 (needs Calibre).

Chapter text edited via 'book2audio chapters --edit' will be used
instead of the original text during conversion.

Examples:
  book2audio convert book.epub
  book2audio convert book.epub -c 1-10
  book2audio convert book.pdf -p edge -v zh-CN-XiaoyiNeural
  book2audio convert --book-id a74e947e332e
  book2audio convert book.epub -p qwen3_mlx
  book2audio convert book.epub -p kokoro -v zf_003""")
@click.argument("input_file", required=False, type=click.Path(exists=True))
@click.option("--chapters", "-c", default=None, help="Chapter range (e.g., '1-5,7,10-')")
@click.option("--provider", "-p", default=None, help="TTS provider: edge, elevenlabs, baidu, iflytek, qwen3_mlx, supertonic, cosyvoice, kokoro")
@click.option("--voice", "-v", default=None, help="Voice name (see 'book2audio doc')")
@click.option("--language", "-l", default="zh-CN", help="Language code (zh-CN, en-US, ja-JP, etc.)")
@click.option("--speed", "-s", type=float, default=None, help="Speech speed (0.5-2.0, default: 1.0)")
@click.option("--model-path", default=None, help="Local model path (for qwen3_mlx)")
@click.option("--book-id", default=None, help="Existing book ID from library")
def convert(input_file, chapters, provider, voice, language, speed, model_path, book_id):
    if not input_file and not book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id[/red]")
        raise SystemExit(1)

    if input_file and book_id:
        console.print("[red]Error: Provide INPUT_FILE or --book-id, not both[/red]")
        raise SystemExit(1)

    input_path = Path(input_file) if input_file else None
    if input_path:
        console.print(f"\n[bold blue]Input:[/bold blue] {input_path.resolve()}")

    from core.converter import Converter
    converter = Converter()

    if book_id:
        book = converter.get_book(book_id)
        if not book:
            console.print(f"[red]Book not found: {book_id}[/red]")
            raise SystemExit(1)
        console.print(f"[bold blue]Book:[/bold blue] {book.title} ({book_id})")
    else:
        book, text_map = _ensure_registered(input_path)

    all_chapters = book.chapters
    console.print(f"[bold blue]Chapters:[/bold blue] {len(all_chapters)} found")

    if chapters:
        selected_indices = _parse_chapter_range(chapters, len(all_chapters))
        selected_chapters = [all_chapters[i] for i in selected_indices]
        console.print(f"[bold blue]Selected:[/bold blue] Chapters {chapters} ({len(selected_chapters)} chapters)")
    else:
        selected_chapters = all_chapters
        console.print(f"[bold blue]Selected:[/bold blue] All {len(selected_chapters)} chapters")

    effective_provider = provider or settings.tts.provider
    if voice is None:
        voice = settings.tts.default_voice
    console.print(f"[bold blue]Provider:[/bold blue] {effective_provider}")
    console.print(f"[bold blue]Voice:[/bold blue] {voice}")
    console.print(f"[bold blue]Language:[/bold blue] {language}")

    if speed is None:
        if effective_provider == "qwen3_mlx":
            speed = settings.qwen3_mlx.speed
        elif effective_provider == "supertonic":
            speed = settings.supertonic.speed
        elif effective_provider == "cosyvoice":
            speed = settings.cosyvoice.speed
        elif effective_provider == "kokoro":
            speed = settings.kokoro.speed
        else:
            speed = 1.0
    console.print(f"[bold blue]Speed:[/bold blue] {speed}x")

    config = TTSConfig(voice=voice, language=language, speed=speed)
    if model_path:
        config.model_path = model_path
        console.print(f"[bold blue]Model Path:[/bold blue] {model_path}")

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
                progress.update(task, advance=1, description=f"Chapter {chapter.index + 1}: {chapter.title[:30]}...")

                # Resolve text: disk file → in-memory → re-parse
                chapter_text = converter.get_chapter_text(book.id, chapter.index) or ""
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

    console.print("\n[bold green]Conversion complete![/bold green]")
    console.print(f"\n[bold blue]Output directory:[/bold blue] {output_dir.resolve()}")
    console.print("[bold blue]Files generated:[/bold blue]")
    for of in output_files:
        console.print(f"  - {of.filename}")
    console.print(f"\nOpen directory: [cyan]open {output_dir}[/cyan]")


# ── chapters ───────────────────────────────────────────────────────────

@cli.command(help="""List, view, and edit chapters in an ebook.

By default shows a chapter list with char counts and estimated duration.

Use --show-text to view a chapter's full text content.
Use --edit to open a chapter in your $EDITOR for editing. Edited text
is saved separately and used during conversion instead of the original.

Examples:
  book2audio chapters book.epub
  book2audio chapters --book-id a74e947e332e
  book2audio chapters book.epub --show-text 3
  book2audio chapters book.epub --show-text 3 --head 30
  book2audio chapters book.epub --edit 3
  book2audio chapters --book-id abc123 --edit 3-5""")
@click.argument("input_file", required=False, type=click.Path(exists=True))
@click.option("--book-id", default=None, help="Existing book ID from library")
@click.option("--show-text", "-t", "show_text", default=None, type=int, help="Show text of chapter N (1-based)")
@click.option("--head", default=None, type=int, help="Show only first N lines of text (use with --show-text)")
@click.option("--edit", "-e", "edit_range", default=None, help="Edit chapter(s) in $EDITOR (e.g., '3' or '3-5')")
def chapters(input_file, book_id, show_text, head, edit_range):
    book, converter = _resolve_book(input_file, book_id)
    display_name = book.title

    # ── Show text mode ──
    if show_text is not None:
        idx = show_text - 1  # Convert 1-based to 0-based
        chapter = next((ch for ch in book.chapters if ch.index == idx), None)
        if not chapter:
            console.print(f"[red]Chapter {show_text} not found. Book has {len(book.chapters)} chapters.[/red]")
            raise SystemExit(1)

        text = converter.get_chapter_text(book.id, idx)
        if text is None:
            console.print(f"[red]Could not load text for chapter {show_text}.[/red]")
            raise SystemExit(1)

        if head:
            lines = text.splitlines()
            text = "\n".join(lines[:head])
            if len(lines) > head:
                text += f"\n... ({len(lines) - head} more lines)"

        edited_marker = " [dim yellow][edited][/dim yellow]" if chapter.edited else ""
        console.print(Panel(
            Text(text),
            title=f"Chapter {show_text}: {chapter.title}{edited_marker}",
            subtitle=f"{chapter.char_count:,} chars · ~{_format_duration(chapter.estimated_duration_seconds)}",
        ))
        return

    # ── Edit mode ──
    if edit_range is not None:
        # Parse range: single number like "3" or range like "3-5"
        if "-" in edit_range:
            parts = edit_range.split("-")
            start_idx = int(parts[0]) - 1
            end_idx = int(parts[1])
        else:
            start_idx = int(edit_range) - 1
            end_idx = start_idx + 1

        indices = list(range(start_idx, end_idx))
        for idx in indices:
            chapter = next((ch for ch in book.chapters if ch.index == idx), None)
            if not chapter:
                console.print(f"[red]Chapter {idx + 1} not found. Skipping.[/red]")
                continue

            text = converter.get_chapter_text(book.id, idx)
            if text is None:
                console.print(f"[red]Could not load text for chapter {idx + 1}. Skipping.[/red]")
                continue

            edited_text = click.edit(text, extension=".txt")
            if edited_text is None:
                console.print(f"[dim]Chapter {idx + 1}: no changes.[/dim]")
                continue

            if edited_text == text:
                console.print(f"[dim]Chapter {idx + 1}: content unchanged.[/dim]")
                continue

            ok = converter.save_chapter_text(book.id, idx, edited_text)
            if ok:
                # Refresh chapter reference after save
                chapter = next((ch for ch in book.chapters if ch.index == idx), None)
                console.print(
                    f"[green]Chapter {idx + 1} saved:[/green] "
                    f"{chapter.char_count:,} chars · ~{_format_duration(chapter.estimated_duration_seconds)}"
                )
            else:
                console.print(f"[red]Failed to save chapter {idx + 1}.[/red]")
        return

    # ── Default: list chapters ──
    chapter_list = book.chapters
    console.print(f"\n[bold blue]Chapters in {display_name}:[/bold blue]")

    total_chars = 0
    total_duration = 0.0
    max_num_width = len(str(len(chapter_list)))

    for chapter in chapter_list:
        char_count = chapter.char_count if chapter.char_count else (len(chapter.text) if chapter.text else 0)
        total_chars += char_count
        total_duration += chapter.estimated_duration_seconds

        num = chapter.index + 1
        edited_marker = " [yellow][edited][/yellow]" if chapter.edited else ""
        console.print(f"\n[bold]{num:>{max_num_width}}. {chapter.title}{edited_marker}[/bold]")
        console.print(f"    {char_count:,} chars · ~{_format_duration(chapter.estimated_duration_seconds)}")

    console.print(f"\n[bold green]Summary:[/bold green]")
    console.print(f"  Total chapters: {len(chapter_list)}")
    console.print(f"  Total characters: {total_chars:,}")
    console.print(f"  Estimated duration: {_format_duration(total_duration)}")
    console.print(f"\n[dim]Use --show-text N to view chapter text, --edit N to edit.[/dim]")


# ── config ─────────────────────────────────────────────────────────────

@cli.command(help="""Manage application configuration.

Commands: show, get, set, reset

Examples:
  book2audio config show
  book2audio config get tts.provider
  book2audio config set tts.provider edge""")
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


# ── voice ──────────────────────────────────────────────────────────────

@cli.command(help="""Manage TTS voices. List, add, or delete custom voices.

Commands: list, add, delete, show

Examples:
  book2audio voice list
  book2audio voice add --provider elevenlabs --voice-id "xxx" --name "My Voice" --language en-US
  book2audio voice delete "My Voice" """)
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
                    marker = " (custom)" if v.custom else ""
                    console.print(f"  - {v.name} ({v.language}){marker}")
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


# ── library ────────────────────────────────────────────────────────────

@cli.group(help="Manage your audiobook library (list, delete).")
def library():
    pass


@library.command(name="list", help="List all books in the library.")
def library_list():
    from core.converter import Converter

    converter = Converter()
    books = converter.get_all_books()

    if not books:
        console.print("[yellow]No books found in library.[/yellow]")
        return

    console.print("\n[bold blue]Library Books:[/bold blue]")
    console.print("-" * 70)
    console.print(f"{'ID':<14}  {'Title':<40}  {'Chapters'}")
    console.print("-" * 70)

    for book in books:
        book_id = book.id
        title = book.title[:38] + "..." if len(book.title) > 40 else book.title
        console.print(f"{book_id:<14}  {title:<40}  {len(book.chapters)}")

    console.print("-" * 70)
    console.print(f"\n[bold green]Total: {len(books)} books[/bold green]")
    console.print("\n[dim]book2audio convert --book-id <ID>    Convert a library book")
    console.print("[dim]book2audio chapters --book-id <ID>   View/edit chapters[/dim]")


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

    upload_dir = settings.upload_dir / book_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)

    output_dir = settings.output_dir / book_id
    if output_dir.exists():
        shutil.rmtree(output_dir)

    converter.delete_book(book_id)
    console.print(f"[green]Deleted: {book.title} ({book_id})[/green]")


# ── serve ──────────────────────────────────────────────────────────────

@cli.command(help="Start the web UI server.")
def serve():
    import uvicorn
    console.print(f"\n[bold green]Starting server at http://localhost:{settings.port}[/bold green]\n")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True, reload_dirs=["app", "core", "config", "cli", "utils"])


# ── doc ────────────────────────────────────────────────────────────────

@cli.command(help="Show full documentation with all commands and examples.")
def doc():
    console.print(Panel(
        "[bold]book2audio[/bold] — Convert ebooks to audiobooks with TTS\n\n"
        "Supported formats: EPUB, PDF, TXT (always), MOBI/AZW3 (needs Calibre).\n"
        "Web UI: [cyan]book2audio serve[/cyan]",
        title="book2audio",
        border_style="blue",
    ))

    console.print(Panel(
        "[bold]book2audio convert[/bold] INPUT_FILE [OPTIONS]\n\n"
        "Convert an ebook to audiobook. Chapter text edited via\n"
        "'book2audio chapters --edit' is used automatically.\n\n"
        "[bold]Options:[/bold]\n"
        "  -c, --chapters RANGE   Chapter range (e.g., '1-5,7,10-')\n"
        "  -p, --provider NAME    TTS provider\n"
        "  -v, --voice NAME       Voice name\n"
        "  -l, --language CODE    Language (zh-CN, en-US, ja-JP, etc.)\n"
        "  -s, --speed FLOAT      Speed 0.5-2.0 (default: 1.0)\n"
        "      --model-path PATH  Local model path (qwen3_mlx / cosyvoice / kokoro)\n"
        "      --book-id ID       Use existing library book\n\n"
        "[bold]Examples:[/bold]\n"
        "  [dim]book2audio convert book.epub[/dim]\n"
        "  [dim]book2audio convert book.epub -c 1-10 -p edge[/dim]\n"
        "  [dim]book2audio convert --book-id abc123 -c 3,5,7[/dim]\n"
        "  [dim]book2audio convert book.pdf -p qwen3_mlx -l en-US[/dim]\n"
        "  [dim]book2audio convert book.epub -p kokoro -v zf_003[/dim]",
        title="convert",
        border_style="green",
    ))

    console.print(Panel(
        "[bold]book2audio chapters[/bold] INPUT_FILE [OPTIONS]\n\n"
        "List, view, and edit chapter content.\n\n"
        "[bold]Options:[/bold]\n"
        "      --book-id ID       Use existing library book\n"
        "  -t, --show-text N      Show text of chapter N (1-based)\n"
        "      --head N           Show only first N lines (with --show-text)\n"
        "  -e, --edit RANGE       Edit chapter(s) in $EDITOR (e.g., '3' or '3-5')\n\n"
        "[bold]Examples:[/bold]\n"
        "  [dim]book2audio chapters book.epub[/dim]                           List all chapters\n"
        "  [dim]book2audio chapters book.epub -t 3[/dim]                      View chapter 3 text\n"
        "  [dim]book2audio chapters book.epub -t 3 --head 20[/dim]            First 20 lines of ch 3\n"
        "  [dim]book2audio chapters book.epub -e 3[/dim]                      Edit chapter 3 in $EDITOR\n"
        "  [dim]book2audio chapters --book-id abc123 -e 3-5[/dim]             Edit chapters 3-5\n\n"
        "[bold]Editing:[/bold]\n"
        "  Edited text is saved to uploads/<id>/chapters/<N>.txt.\n"
        "  Original file is never modified. Edited chapters show [yellow][edited][/yellow] tag.\n"
        "  Conversion uses edited text automatically when available.",
        title="chapters",
        border_style="green",
    ))

    console.print(Panel(
        "[bold]book2audio library[/bold] COMMAND\n\n"
        "[bold]Commands:[/bold]\n"
        "  list                    List all books\n"
        "  delete BOOK_ID          Delete a book and its files\n\n"
        "[bold]Examples:[/bold]\n"
        "  [dim]book2audio library list[/dim]\n"
        "  [dim]book2audio library delete abc123def456[/dim]",
        title="library",
        border_style="green",
    ))

    console.print(Panel(
        "[bold]book2audio voice[/bold] COMMAND [OPTIONS]\n\n"
        "[bold]Commands:[/bold]\n"
        "  list                    List all voices\n"
        "  add                     Add a custom voice\n"
        "  delete NAME             Delete a custom voice\n"
        "  show NAME               Show voice details\n\n"
        "[bold]Add options:[/bold]\n"
        "  -p, --provider PROV     Provider name\n"
        "      --voice-id ID       Voice ID from provider\n"
        "      --name NAME         Display name\n"
        "  -l, --language CODE     Language code\n"
        "      --gender GENDER     male / female / neutral\n\n"
        "[bold]Examples:[/bold]\n"
        "  [dim]book2audio voice list[/dim]\n"
        "  [dim]book2audio voice add -p elevenlabs --voice-id xxx --name \"My Voice\" -l en-US[/dim]",
        title="voice",
        border_style="green",
    ))

    console.print(Panel(
        "[bold]book2audio config[/bold] COMMAND [KEY] [VALUE]\n\n"
        "[bold]Commands:[/bold]\n"
        "  show                    Show all config\n"
        "  get KEY                 Get a value\n"
        "  set KEY VALUE           Set a value\n"
        "  reset KEY               Reset to default\n\n"
        "[bold]Examples:[/bold]\n"
        "  [dim]book2audio config show[/dim]\n"
        "  [dim]book2audio config get tts.provider[/dim]\n"
        "  [dim]book2audio config set tts.provider edge[/dim]\n"
        "  [dim]book2audio config set qwen3_mlx.speed 1.2[/dim]",
        title="config",
        border_style="green",
    ))

    console.print(Panel(
        "[bold]book2audio serve[/bold]\n\n"
        "Start the web UI server for browser-based conversion.\n"
        "Default: http://localhost:8000\n\n"
        "[bold]Example:[/bold]\n"
        "  [dim]book2audio serve[/dim]",
        title="serve",
        border_style="green",
    ))

    console.print(Panel(
        "[bold]TTS Providers:[/bold]\n\n"
        "  [bold]edge[/bold]           Free, good quality. Microsoft Edge voices.\n"
        "  [bold]qwen3_mlx[/bold]      Local, Apple Silicon optimized. Needs mlx-audio.\n"
        "  [bold]kokoro[/bold]         Local, ONNX/CPU (kokoro-onnx). 100+ CN voices. Intel Mac default.\n"
        "  [bold]supertonic[/bold]     Local, ONNX-based, 33 languages. Needs supertonic.\n"
        "  [bold]cosyvoice[/bold]     Local, ONNX/CPU (sherpa-onnx). Optional. Needs sherpa-onnx.\n"
        "  [bold]baidu[/bold]          Baidu API. Requires app_id + api_key.\n"
        "  [bold]iflytek[/bold]        iFlytek API. Requires app_id + api_key + api_secret.\n"
        "  [bold]elevenlabs[/bold]     ElevenLabs API. Requires api_key.\n\n"
        "[bold]Languages:[/bold] zh-CN, en-US, ja-JP, ko-KR,\n"
        "               fr-FR, de-DE, ru-RU, es-ES, pt-PT, it-IT + 23 more (supertonic)",
        title="providers",
        border_style="cyan",
    ))


# ── helpers ────────────────────────────────────────────────────────────

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
