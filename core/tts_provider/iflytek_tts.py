from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log


class IflytekTTSProvider(BaseTTSProvider):
    provider_name = "iflytek"
    supported_languages = [
        "zh-CN",
    ]

    _WS_URL = "wss://tts-api.xfyun.cn/v2/tts"

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.max_retries = settings.tts.max_retries

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        if not settings.iflytek_tts.app_id or not settings.iflytek_tts.api_key or not settings.iflytek_tts.api_secret:
            raise ValueError(
                "iFlytek TTS requires B2A_IFLYTEK_TTS__APP_ID, B2A_IFLYTEK_TTS__API_KEY, B2A_IFLYTEK_TTS__API_SECRET"
            )

    def _build_auth_url(self) -> str:
        """Build WebSocket URL with HMAC-SHA256 auth signature."""
        from datetime import datetime, timezone
        from urllib.parse import urlencode

        date = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
        signature_origin = f"host: tts-api.xfyun.cn\ndate: {date}\nGET /v2/tts HTTP/1.1"
        signature = base64.b64encode(
            hmac.new(
                settings.iflytek_tts.api_secret.encode(),
                signature_origin.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        authorization = base64.b64encode(
            f'api_key="{settings.iflytek_tts.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'.encode()
        ).decode()

        params = urlencode({"authorization": authorization, "date": date, "host": "tts-api.xfyun.cn"})
        return f"{self._WS_URL}?{params}"

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        chunk_size = settings.iflytek_tts.chunk_max_chars
        chunks = TextProcessor.chunk(text, max_chars=chunk_size, language=self.config.language)
        log.info("iFlytek TTS: %d chunks (max %d chars)", len(chunks), chunk_size)

        if not chunks:
            raise ValueError("No text to synthesize")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(chunks) == 1:
            if progress:
                progress(0, 1)
            await self._ws_synthesize_to_file(chunks[0], output_path)
            if progress:
                progress(1, 1)
            return output_path

        # Multiple chunks: synthesize each to temp mp3, concat via ffmpeg
        import tempfile
        temp_dir = Path(tempfile.mkdtemp())
        chunk_files: list[Path] = []
        for i, chunk in enumerate(chunks):
            if progress:
                progress(i, len(chunks))
            chunk_path = temp_dir / f"chunk_{i:04d}.mp3"
            await self._ws_synthesize_to_file(chunk, chunk_path)
            chunk_files.append(chunk_path)

        if progress:
            progress(len(chunks), len(chunks))

        # Concat via ffmpeg
        list_file = temp_dir / "list.txt"
        list_file.write_text("".join(f"file '{f}'\n" for f in chunk_files))
        import subprocess
        subprocess.run(
            [settings.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(output_path)],
            check=True, capture_output=True,
        )
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        return output_path

    async def _synthesize_single(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize one chunk via WebSocket, return (audio_array, sample_rate)."""
        for attempt in range(self.max_retries):
            try:
                return await self._ws_synthesize(text)
            except Exception as e:
                log.warning(
                    "iFlytek TTS attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    async def _ws_synthesize_to_file(self, text: str, output_path: Path) -> None:
        """Synthesize one chunk, write mp3 directly to file."""
        import websockets

        business_params = {
            "aue": "lame",
            "sfl": 0,
            "auf": "audio/L16;rate=16000",
            "vcn": self.config.voice,
            "speed": max(0, min(200, int(50 * self.config.speed))),
            "volume": 50,
            "pitch": 50,
            "bgs": 0,
            "tte": "UTF8",
        }
        if self.config.voice.startswith("x4_"):
            business_params["ent"] = "xts"

        request_frame = {
            "common": {"app_id": settings.iflytek_tts.app_id},
            "business": business_params,
            "data": {
                "status": 2,
                "text": base64.b64encode(text.encode("utf-8")).decode(),
            },
        }

        for attempt in range(self.max_retries):
            try:
                url = self._build_auth_url()
                audio_frames: list[bytes] = []

                async with websockets.connect(
                    url,
                    ping_interval=30,
                    ping_timeout=60,
                    close_timeout=10,
                ) as ws:
                    await ws.send(json.dumps(request_frame))
                    while True:
                        response = await asyncio.wait_for(ws.recv(), timeout=120)
                        resp_data = json.loads(response)
                        code = resp_data.get("code", -1)
                        if code != 0:
                            msg = resp_data.get("message", "unknown error")
                            sid = resp_data.get("sid", "")
                            raise RuntimeError(f"iFlytek TTS error {code}: {msg} (sid={sid})")
                        audio = resp_data.get("data", {}).get("audio", "")
                        if audio:
                            audio_frames.append(base64.b64decode(audio))
                        status = resp_data.get("data", {}).get("status", 0)
                        if status == 2:
                            break

                output_path.write_bytes(b"".join(audio_frames))
                return

            except Exception as e:
                log.warning(
                    "iFlytek TTS attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    async def _ws_synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Connect to iFlytek WebSocket, send text, collect audio frames."""
        import websockets

        business_params = {
            "aue": "lame",
            "sfl": 0,
            "auf": "audio/L16;rate=16000",
            "vcn": self.config.voice,
            "speed": max(0, min(200, int(50 * self.config.speed))),
            "volume": 50,
            "pitch": 50,
            "bgs": 0,
            "tte": "UTF8",
        }
        if self.config.voice.startswith("x4_"):
            business_params["ent"] = "xts"

        request_frame = {
            "common": {"app_id": settings.iflytek_tts.app_id},
            "business": business_params,
            "data": {
                "status": 2,
                "text": base64.b64encode(text.encode("utf-8")).decode(),
            },
        }

        for attempt in range(self.max_retries):
            try:
                url = self._build_auth_url()
                audio_frames: list[bytes] = []

                async with websockets.connect(
                    url,
                    ping_interval=30,
                    ping_timeout=60,
                    close_timeout=10,
                ) as ws:
                    await ws.send(json.dumps(request_frame))

                    while True:
                        response = await asyncio.wait_for(ws.recv(), timeout=120)
                        resp_data = json.loads(response)
                        code = resp_data.get("code", -1)

                        if code != 0:
                            msg = resp_data.get("message", "unknown error")
                            sid = resp_data.get("sid", "")
                            raise RuntimeError(f"iFlytek TTS error {code}: {msg} (sid={sid})")

                        audio = resp_data.get("data", {}).get("audio", "")
                        if audio:
                            audio_frames.append(base64.b64decode(audio))

                        status = resp_data.get("data", {}).get("status", 0)
                        if status == 2:
                            break

                raw_mp3 = b"".join(audio_frames)
                import io
                audio_array, sample_rate = sf.read(io.BytesIO(raw_mp3), dtype="float32")
                if audio_array.ndim > 1:
                    audio_array = audio_array[:, 0]
                return audio_array, sample_rate

            except Exception as e:
                log.warning(
                    "iFlytek TTS attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    @staticmethod
    def _wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
        import subprocess
        cmd = [
            settings.ffmpeg_path,
            "-i", str(wav_path),
            "-codec:a", "libmp3lame",
            "-q:a", "2",
            str(mp3_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    def estimate_duration(self, char_count: int) -> float:
        return char_count / settings.tts.chars_per_second
