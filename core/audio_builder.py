from __future__ import annotations

import subprocess
from pathlib import Path

from pydub import AudioSegment

from config.settings import settings
from core.models import Chapter
from utils.ffmpeg_utils import get_audio_duration
from utils.log import log


class AudioBuilder:
    def build_m4b(
        self,
        chapter_files: list[tuple[Chapter, Path]],
        output_path: Path,
        book_title: str,
        book_author: str,
        cover_path: str | None = None,
    ) -> Path:
        if not chapter_files:
            raise ValueError("No chapter files to build M4B")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Get durations
        durations: list[tuple[str, float]] = []
        for chapter, fpath in chapter_files:
            dur = get_audio_duration(str(fpath))
            if dur <= 0:
                dur = len(AudioSegment.from_mp3(str(fpath))) / 1000.0
            durations.append((chapter.title, dur))
        metadata_path = output_path.parent / "ffmetadata.txt"
        self._generate_ffmetadata(durations, metadata_path, book_title, book_author)
        try:
            # Feed the per-chapter MP3s directly into ffmpeg via the concat
            # demuxer, transcoding once to AAC. This avoids the previous
            # double lossy encode (MP3 -> combined_temp.mp3 -> AAC) and keeps
            # only one decoded copy in memory at a time (streamed by ffmpeg),
            # so long books no longer risk an OOM at the merge step.
            concat_list = self._write_concat_list(
                [f for _, f in chapter_files], output_path.parent
            )
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-i", str(metadata_path),
            ]
            if cover_path and Path(cover_path).exists():
                cmd += ["-i", str(cover_path)]
                cmd += [
                    "-map", "0:a", "-map", "2:v",
                    "-c:v", "mjpeg", "-disposition:v", "attached_pic",
                ]
            cmd += [
                "-map_metadata", "1",
                "-map_chapters", "1",
                "-c:a", "aac",
                "-b:a", "64k",
                "-movflags", "+faststart",
            ]
            if settings.audio.normalize_loudness:
                cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
            cmd.append(str(output_path))
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                log.error("ffmpeg M4B build failed: %s", result.stderr)
                raise RuntimeError(f"M4B build failed: {result.stderr}")
            # Patch ftyp brand from M4A/isom to M4B so Apple Books recognizes audiobook chapters
            self._patch_m4b_brand(output_path)
            log.info("M4B created: %s", output_path)
            return output_path
        finally:
            metadata_path.unlink(missing_ok=True)
            concat_list_path = output_path.parent / self._concat_list_name(output_path.stem)
            concat_list_path.unlink(missing_ok=True)

    def build_combined_mp3(
        self,
        chapter_files: list[tuple[Chapter, Path]],
        output_path: Path,
    ) -> Path:
        if not chapter_files:
            raise ValueError("No chapter files to build MP3")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._concat_audio([f for _, f in chapter_files], output_path)
        log.info("MP3 created: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Concat helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _concat_list_name(stem: str) -> str:
        return f"_concat_{stem}.txt"

    def _write_concat_list(self, files: list[Path], out_dir: Path) -> Path:
        """Write an ffmpeg concat demuxer list file. Caller must unlink it."""
        out_dir.mkdir(parents=True, exist_ok=True)
        list_path = out_dir / self._concat_list_name("m4btmp")
        lines = [f"file '{f.resolve()}'" for f in files]
        list_path.write_text("\n".join(lines), encoding="utf-8")
        return list_path

    def _concat_audio(self, files: list[Path], output: Path) -> None:
        """Concatenate chapter MP3s into one MP3 via streaming ffmpeg.

        Tries ``-c copy`` first (no re-encode, lossless, near-zero RAM). If that
        fails — which happens when chapters have mismatched sample rates or
        codecs — falls back to re-encoding with libmp3lame. Either way avoids
        loading the entire book into RAM as the old pydub loop did.
        """
        output.parent.mkdir(parents=True, exist_ok=True)
        concat_list = self._write_concat_list(files, output.parent)
        try:
            # Attempt 1: stream copy (lossless, fast, no re-encode).
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(output),
                ],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode == 0:
                return
            log.warning(
                "concat -c copy failed (%s), falling back to re-encode",
                (result.stderr or "").strip().splitlines()[-1:] or ["unknown"],
            )
            # Attempt 2: re-encode. Mismatched sample rates / codecs require this.
            audio_filters = []
            if settings.audio.normalize_loudness:
                audio_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "libmp3lame", "-b:a", "128k",
            ]
            if audio_filters:
                cmd += ["-af", ",".join(audio_filters)]
            cmd += ["-movflags", "+faststart", str(output)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if result.returncode != 0:
                log.error("ffmpeg concat re-encode failed: %s", result.stderr)
                raise RuntimeError(f"Audio concat failed: {result.stderr}")
        finally:
            concat_list.unlink(missing_ok=True)

    @staticmethod
    def _patch_m4b_brand(path: Path) -> None:
        """Patch ftyp box major brand to M4B for Apple Books chapter support.

        Rewrites bytes in place; on any error the original header bytes are
        restored so the file is never left half-patched. Bounds-checks every
        write against the 64-byte header that was read.
        """
        M4B = b"M4B "
        try:
            with open(path, "r+b") as f:
                # ftyp is always the first atom: [size(4)][ftyp(4)][brand(4)][version(4)][compat...]
                header = f.read(64)
                backup = bytearray(header)
                idx = header.find(b"ftyp")
                if idx < 0:
                    return
                brand_offset = idx + 4
                # Bounds-check: need 4 bytes for the major brand.
                if brand_offset + 4 > len(header):
                    return
                f.seek(brand_offset)
                old_brand = f.read(4)
                f.seek(brand_offset)
                f.write(M4B)
                # Patch compatible_brands: replace M4A/isom with M4B
                compat_start = brand_offset + 8
                for pos in range(compat_start, len(header) - 3, 4):
                    chunk = header[pos:pos + 4]
                    if chunk in (b"M4A ", b"isom"):
                        f.seek(pos)
                        f.write(M4B)
                f.flush()
            log.info("Patched M4B brand: %s -> M4B", old_brand)
        except OSError as e:
            # Restore the original 64-byte header if we managed to back it up,
            # so the file is not left in a half-patched state.
            try:
                with open(path, "r+b") as f:
                    f.write(backup)  # noqa: F821 — only referenced on the except path
                    f.flush()
            except (OSError, NameError):
                pass
            log.warning("Failed to patch M4B brand (left unpatched): %s", e)

    @staticmethod
    def _escape_ffmeta(value: str) -> str:
        """Escape a value for the FFMETADATA1 key=value format.

        ffmpeg's metadata parser treats ``=`` as the key/value separator, ``#``
        as a comment introducer, and ``\\`` as the escape char. Newlines/control
        chars would also break the line-oriented format. Chapter titles come
        from book content, so all of these are reachable.
        """
        # Drop newlines/CR (a title spanning lines would corrupt the file),
        # then escape backslash first, then = and #.
        cleaned = value.replace("\r", " ").replace("\n", " ")
        cleaned = cleaned.replace("\\", "\\\\")
        cleaned = cleaned.replace("=", "\\=")
        cleaned = cleaned.replace("#", "\\#")
        return cleaned

    def _generate_ffmetadata(
        self,
        chapter_durations: list[tuple[str, float]],
        output_path: Path,
        book_title: str = "",
        book_author: str = "",
    ) -> None:
        lines = [";FFMETADATA1"]
        if book_title:
            lines.append(f"title={self._escape_ffmeta(book_title)}")
        if book_author:
            lines.append(f"artist={self._escape_ffmeta(book_author)}")
        start_ms = 0
        for title, duration in chapter_durations:
            end_ms = start_ms + int(duration * 1000)
            lines.extend([
                "",
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"title={self._escape_ffmeta(title)}",
            ])
            start_ms = end_ms
        output_path.write_text("\n".join(lines), encoding="utf-8")
