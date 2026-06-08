"""
╔══════════════════════════════════════════════╗
║   ClippedAI — Whisper Transcription Engine   ║
╚══════════════════════════════════════════════╝

Runs OpenAI Whisper locally (no API key needed).
Returns word-level timestamps for precise clip cutting.
"""

import os
import json
import time
import whisper
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable
from openai import OpenAI
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class TranscriptionEngine:
    """Local Whisper-based transcription with word-level timestamps."""

    SUPPORTED_MODELS = ["tiny", "base", "small", "medium", "large"]

    def __init__(self, model_size: str = "base", device: str = "cpu", language: Optional[str] = None):
        if model_size not in self.SUPPORTED_MODELS:
            raise ValueError(f"Model must be one of: {self.SUPPORTED_MODELS}")
        self.model_size = model_size
        self.device = device
        self.language = language
        self._model = None

    def load_model(self, progress_callback: Optional[Callable] = None):
        """Load the Whisper model (downloads on first run, cached afterwards)."""
        if self._model is not None:
            return
        logger.info(f"Loading Whisper model: {self.model_size} on {self.device}")
        if progress_callback:
            progress_callback("loading_model", f"Loading Whisper '{self.model_size}' model...")
        self._model = whisper.load_model(self.model_size, device=self.device)
        logger.info("Whisper model loaded successfully")

    def transcribe(self, video_path: str, progress_callback: Optional[Callable] = None) -> dict:
        """
        Transcribe the video and return a full transcript with word-level timestamps.

        Returns:
            {
                "text": "full transcript text",
                "language": "en",
                "duration": 7234.5,  # seconds
                "segments": [
                    {
                        "id": 0,
                        "start": 0.0,
                        "end": 4.2,
                        "text": "Hello everyone welcome back",
                        "words": [
                            {"word": "Hello", "start": 0.0, "end": 0.4},
                            ...
                        ],
                        "score": 0.0  # will be filled by scorer
                    },
                    ...
                ]
            }
        """
        self.load_model(progress_callback)

        video_path = str(video_path)
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        logger.info(f"Starting transcription of: {video_path}")
        if progress_callback:
            progress_callback("transcribing", "Transcribing audio with Whisper (this may take a while)...")

        start_time = time.time()

        api_key = os.environ.get("OPENAI_API_KEY")
        use_cloud = api_key and api_key != "your_openai_api_key_here"

        if use_cloud:
            logger.info("Using OpenAI Whisper API (Cloud)")
            if progress_callback:
                progress_callback("transcribing", "Transcribing with OpenAI API (Cloud)...")
            
            client = OpenAI(api_key=api_key)
            
            # Extract compressed audio to meet 25MB API limit
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_audio:
                audio_path = tmp_audio.name
                
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "16000", 
                    "-ac", "1", "-b:a", "32k", audio_path
                ], capture_output=True, check=True)
                
                with open(audio_path, "rb") as f:
                    api_result = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                        response_format="verbose_json",
                        timestamp_granularities=["word", "segment"]
                    )
                # Convert OpenAI API output to match local whisper format
                result = api_result.model_dump()
            finally:
                if os.path.exists(audio_path):
                    os.unlink(audio_path)
        else:
            logger.info("Using Local Whisper")
            if progress_callback:
                progress_callback("transcribing", "Transcribing locally (this may take a while)...")
            self.load_model(progress_callback)
            
            options = {
                "word_timestamps": True,
                "verbose": False,
                "task": "transcribe",
            }
            if self.language:
                options["language"] = self.language

            result = self._model.transcribe(video_path, **options)

        elapsed = time.time() - start_time
        logger.info(f"Transcription completed in {elapsed:.1f}s")

        # Get audio duration

        import subprocess
        try:
            probe_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", video_path
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            probe_data = json.loads(probe_result.stdout)
            duration = float(probe_data["format"]["duration"])
        except Exception:
            # Fallback: estimate from last segment
            duration = result["segments"][-1]["end"] if result["segments"] else 0

        # Normalize segments
        segments = []
        for seg in result["segments"]:
            words = []
            if "words" in seg:
                for w in seg["words"]:
                    words.append({
                        "word": w.get("word", "").strip(),
                        "start": round(w.get("start", seg["start"]), 3),
                        "end": round(w.get("end", seg["end"]), 3),
                        "probability": round(w.get("probability", 1.0), 3)
                    })
            segments.append({
                "id": seg["id"],
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "text": seg["text"].strip(),
                "words": words,
                "score": 0.0
            })

        transcript = {
            "text": result["text"].strip(),
            "language": result.get("language", "en"),
            "duration": round(duration, 2),
            "segments": segments,
            "model_used": self.model_size,
            "transcription_time": round(elapsed, 1),
        }

        if progress_callback:
            progress_callback(
                "transcription_done",
                f"Transcription complete! {len(segments)} segments, "
                f"language: {transcript['language']}"
            )

        return transcript

    def save_transcript(self, transcript: dict, output_path: str):
        """Save transcript to JSON file for reuse."""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)
        logger.info(f"Transcript saved to: {output_path}")

    def load_transcript(self, path: str) -> dict:
        """Load a previously saved transcript."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_srt(self, segments: list, output_path: str,
                     clip_start: float = 0.0, speed_factor: float = 1.0):
        """
        Generate an .srt subtitle file using word-level timestamps when available.
        - speed_factor: compensates for video speedup (e.g. 1.05 for 5% faster video)
        - Uses Whisper word timestamps for tight per-word sync when available
        """
        CHUNK = 4   # words per subtitle card
        lines = []
        counter = 1

        for seg in segments:
            # Try word-level timestamps first (much better sync)
            words = [
                w for w in seg.get("words", [])
                if w.get("word", "").strip()
                   and w.get("start") is not None
                   and w.get("end") is not None
            ]

            if words:
                for i in range(0, len(words), CHUNK):
                    chunk = words[i:i + CHUNK]
                    w_start = max(0.0, (chunk[0]["start"] - clip_start) / speed_factor)
                    w_end   = max(w_start + 0.15,
                                  (chunk[-1]["end"] - clip_start) / speed_factor)
                    text    = " ".join(w["word"].strip() for w in chunk)
                    if text:
                        lines += [str(counter),
                                  f"{self._format_time(w_start)} --> {self._format_time(w_end)}",
                                  text, ""]
                        counter += 1
            else:
                # Fallback: segment-level timing
                s_start = max(0.0, (seg["start"] - clip_start) / speed_factor)
                s_end   = max(s_start + 0.1, (seg["end"] - clip_start) / speed_factor)
                seg_words = seg["text"].strip().split()
                chunks = [" ".join(seg_words[i:i+CHUNK])
                          for i in range(0, len(seg_words), CHUNK)]
                for chunk_text in chunks:
                    if chunk_text:
                        lines += [str(counter),
                                  f"{self._format_time(s_start)} --> {self._format_time(s_end)}",
                                  chunk_text, ""]
                        counter += 1

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"SRT file written: {output_path}")

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
        ms = int((seconds % 1) * 1000)
        s = int(seconds) % 60
        m = (int(seconds) // 60) % 60
        h = int(seconds) // 3600
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
