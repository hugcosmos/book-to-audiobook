from __future__ import annotations

import subprocess
from pathlib import Path

from pydub import AudioSegment

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
        # Generate FFMETADATA
        metadata_path = output_path.parent / "ffmetadata.txt"
        self._generate_ffmetadata(durations, metadata_path, book_title, book_author)
        # Concatenate audio
        combined_mp3 = output_path.parent / "combined_temp.mp3"
        self._concat_audio([f for _, f in chapter_files], combined_mp3)
        # Build M4B with optional cover image
        cmd = [
            "ffmpeg", "-y",
            "-i", str(combined_mp3),
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
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log.error("ffmpeg M4B build failed: %s", result.stderr)
            raise RuntimeError(f"M4B build failed: {result.stderr}")
        # Patch ftyp brand from M4A/isom to M4B so Apple Books recognizes audiobook chapters
        self._patch_m4b_brand(output_path)
        # Cleanup temp files
        combined_mp3.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        log.info("M4B created: %s", output_path)
        return output_path

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

    def _concat_audio(self, files: list[Path], output: Path) -> None:
        merged = AudioSegment.empty()
        for f in files:
            merged += AudioSegment.from_mp3(str(f))
        merged.export(str(output), format="mp3", bitrate="128k")

    @staticmethod
    def _patch_m4b_brand(path: Path) -> None:
        """Patch ftyp box major brand to M4B for Apple Books chapter support."""
        M4B = b"M4B "
        with open(path, "r+b") as f:
            # ftyp is always the first atom: [size(4)][ftyp(4)][brand(4)][version(4)][compat...]
            header = f.read(64)
            idx = header.find(b"ftyp")
            if idx < 0:
                return
            brand_offset = idx + 4
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
        log.info("Patched M4B brand: %s -> M4B", old_brand)

    def _generate_ffmetadata(
        self,
        chapter_durations: list[tuple[str, float]],
        output_path: Path,
        book_title: str = "",
        book_author: str = "",
    ) -> None:
        lines = [";FFMETADATA1"]
        if book_title:
            lines.append(f"title={book_title}")
        if book_author:
            lines.append(f"artist={book_author}")
        start_ms = 0
        for title, duration in chapter_durations:
            end_ms = start_ms + int(duration * 1000)
            lines.extend([
                "",
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"title={title}",
            ])
            start_ms = end_ms
        output_path.write_text("\n".join(lines), encoding="utf-8")
