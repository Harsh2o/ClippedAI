"""
ClippedAI — FFmpeg Video Processor (Fixed for Windows)

Handles all video processing:
  - Cutting clips from the source video
  - Converting ANY aspect ratio to 9:16 vertical (1080x1920) with blurred background
  - Burning SRT subtitles into the video
  - Generating preview thumbnails
"""

import os
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable, List

from core.scorer import ScoredClip
from core.transcribe import TranscriptionEngine

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Uses FFmpeg to cut, reformat, and caption video clips."""

    def __init__(self, config: dict):
        vc = config.get("video", {})
        sc = config.get("subtitles", {})

        self.width  = vc.get("output_width", 1080)
        self.height = vc.get("output_height", 1920)
        self.fps    = vc.get("fps", 30)
        self.video_bitrate = vc.get("video_bitrate", "12M")  # Increased for higher quality
        self.audio_bitrate = vc.get("audio_bitrate", "320k") # Increased for higher quality
        self.blur_background = vc.get("blur_background", True)

        self.sub_font         = sc.get("font", "Arial")
        self.sub_font_size    = sc.get("font_size", 18)
        self.sub_primary      = sc.get("primary_color", "&H00FFFFFF")
        self.sub_outline_col  = sc.get("outline_color", "&H00000000")
        self.sub_outline_w    = sc.get("outline_width", 3)
        self.sub_shadow       = sc.get("shadow", 2)
        self.sub_bold         = sc.get("bold", True)
        self.sub_margin_v     = sc.get("margin_v", 80)

        self._check_ffmpeg()

    # ── Public entry point ────────────────────────────────────────────────────

    def process_clip(
        self,
        video_path: str,
        clip: ScoredClip,
        output_dir: str,
        transcript: dict,
        clip_index: int,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """
        Full pipeline for one clip:
          1. Cut raw segment from source
          2. Convert to 9:16 vertical 1080x1920 with blurred background
          3. Generate .srt subtitles
          4. Burn subtitles in
          5. Generate thumbnail
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        base        = f"short_{clip_index + 1:02d}"
        raw_clip    = str(output_dir / f"{base}_raw.mp4")
        vertical    = str(output_dir / f"{base}_vertical.mp4")
        srt_file    = str(output_dir / f"{base}.srt")
        final_clip  = str(output_dir / f"{base}_final.mp4")
        thumbnail   = str(output_dir / f"{base}_thumb.jpg")

        def cb(msg):
            if progress_callback:
                progress_callback("processing_clip", msg)

        try:
            # ── 1. Cut ─────────────────────────────────────────────────────
            cb(f"Clip {clip_index+1}: cutting {clip.start:.0f}s → {clip.end:.0f}s...")
            self._cut_clip(video_path, clip.start, clip.end, raw_clip)

            # ── 2. Make vertical 9:16 ──────────────────────────────────────
            cb(f"Clip {clip_index+1}: converting to 9:16 vertical...")
            self._make_vertical(raw_clip, vertical)

            # ── 2b. Break audio fingerprint ────────────────────────────────
            # Mix a very quiet generated ambient tone into the audio.
            # This changes the audio waveform so Content ID cannot match it
            # against the registered fingerprint. The tone is ~5% volume
            # (barely perceptible) but enough to scramble the fingerprint.
            cb(f"Clip {clip_index+1}: applying audio fingerprint protection...")
            audiomix = str(output_dir / f"{base}_audiomix.mp4")
            self._add_audio_mix(vertical, audiomix)

            # ── 3. Generate SRT ────────────────────────────────────────────
            cb(f"Clip {clip_index+1}: generating subtitles...")
            segs = [
                s for s in transcript["segments"]
                if s["start"] >= clip.start - 0.5 and s["end"] <= clip.end + 0.5
            ]
            engine = TranscriptionEngine()
            engine.generate_srt(segs, srt_file, clip_start=clip.start, speed_factor=1.05)

            # ── 4. Burn subtitles ──────────────────────────────────────────
            cb(f"Clip {clip_index+1}: burning subtitles...")
            self._burn_subtitles(audiomix, srt_file, final_clip)

            # ── 5. Thumbnail ───────────────────────────────────────────────
            self._generate_thumbnail(final_clip, thumbnail)

            # Cleanup intermediates
            for f in [raw_clip, vertical, audiomix]:
                try: os.remove(f)
                except: pass

            size_mb = os.path.getsize(final_clip) / (1024 * 1024)

            if progress_callback:
                progress_callback("clip_done", f"Clip {clip_index+1} ready! ({size_mb:.1f} MB)")

            return {
                "clip_index":    clip_index,
                "clip_number":   clip_index + 1,
                "title":         clip.title,
                "start":         clip.start,
                "end":           clip.end,
                "duration":      clip.duration,
                "score":         clip.score,
                "final_video":   final_clip,
                "subtitle_file": srt_file,
                "thumbnail":     thumbnail,
                "size_mb":       round(size_mb, 2),
                "status":        "success",
            }

        except Exception as e:
            logger.error(f"Failed to process clip {clip_index+1}: {e}")
            if progress_callback:
                progress_callback("clip_error", f"Clip {clip_index+1} failed: {e}")
            return {
                "clip_index":  clip_index,
                "clip_number": clip_index + 1,
                "status":      "error",
                "error":       str(e),
            }

    # ── FFmpeg steps ──────────────────────────────────────────────────────────

    def _cut_clip(self, input_path: str, start: float, end: float, output_path: str):
        """Cut clip with 5% speed shift to evade audio fingerprinting."""
        duration = end - start
        # 5% speed up: destroys audio waveform fingerprint (Content ID can't match)
        # setpts=0.95238*PTS matches the 1.05x atempo audio speed
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i",  input_path,
            "-t",  str(duration),
            "-filter_complex", "[0:v]setpts=0.95238*PTS[v];[0:a]atempo=1.05[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            "-b:v", self.video_bitrate,
            "-b:a", self.audio_bitrate,
            "-movflags", "+faststart",
            output_path,
        ]
        self._run(cmd, "cut_with_speed_shift")

    def _add_audio_mix(self, input_path: str, output_path: str):
        """
        Mix a very quiet ambient tone into the audio to break Content ID fingerprinting.

        How Content ID audio matching works:
          YouTube computes a spectral fingerprint of the audio waveform.
          Even a small inaudible tone mixed in changes the spectral signature
          enough that the fingerprint no longer matches the registered reference.

        We generate an A major chord (A3+E4+A4) at ~5% amplitude using FFmpeg's
        built-in aevalsrc filter — no external music files needed.
        """
        # A3(220Hz) + E4(330Hz) + A4(440Hz) = A major chord, very soft
        tone = (
            "aevalsrc=0.04*sin(220*2*PI*t)"
            "+0.03*sin(330*2*PI*t)"
            "+0.02*sin(440*2*PI*t)"
            ":s=44100:c=stereo"
        )
        fc = (
            f"[1:a]volume=0.05[tone];"
            f"[0:a][tone]amix=inputs=2:duration=shortest:weights=1 1[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-f", "lavfi", "-i", tone,
            "-filter_complex", fc,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "+faststart",
            output_path,
        ]
        self._run(cmd, "audio_fingerprint_break")

    def _make_vertical(self, input_path: str, output_path: str):
        """
        Convert ANY source to 1080x1920 (9:16) vertical.
        Strong anti-copyright stack:
          - hflip  (mirrors every pixel left-right)
          - zoom crop (scale 102% then crop — shifts all pixel coords)
          - eq  (boosts contrast + saturation slightly)
          - noise (adds subtle film grain — scrambles per-frame pixel hash)
        """
        stealth = (
            "hflip"
            ",scale=iw*1.02:ih*1.02"  # 2% zoom in
            ",crop=iw/1.02:ih/1.02"  # crop back to original size
            ",eq=contrast=1.05:saturation=1.1"
            ",noise=alls=8:allf=t"   # subtle film grain
        )

        if self.blur_background:
            fc = (
                f"[0:v]{stealth},"
                f"scale={self.width}:{self.height}"
                f":force_original_aspect_ratio=increase"
                f",crop={self.width}:{self.height}"
                f",boxblur=25:5[bg];"

                f"[0:v]{stealth},"
                f"scale=-2:{self.height}[fg];"

                f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
                f",setsar=1,fps={self.fps}[out]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-filter_complex", fc,
                "-map", "[out]",
                "-map", "0:a?",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                "-b:v", self.video_bitrate,
                "-b:a", self.audio_bitrate,
                "-movflags", "+faststart",
                output_path,
            ]
        else:
            vf = (
                f"{stealth},"
                f"scale={self.width}:{self.height}"
                f":force_original_aspect_ratio=increase"
                f",crop={self.width}:{self.height}"
                f",setsar=1,fps={self.fps}"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                "-b:v", self.video_bitrate,
                "-b:a", self.audio_bitrate,
                "-movflags", "+faststart",
                output_path,
            ]
        self._run(cmd, "make_vertical_9:16")

    def _burn_subtitles(self, input_path: str, srt_path: str, output_path: str):
        """
        Burn subtitles using ASS format for 100% reliable Windows compatibility.
        Converts SRT → ASS (styles embedded in file) then uses simple `ass=filename`
        filter — no Windows path/colon escaping issues at all.
        """
        srt_abs    = str(Path(srt_path).resolve())
        srt_dir    = str(Path(srt_abs).parent)
        ass_name   = Path(srt_abs).stem + '.ass'
        ass_full   = os.path.join(srt_dir, ass_name)
        input_abs  = str(Path(input_path).resolve())
        output_abs = str(Path(output_path).resolve())

        # Convert SRT → ASS with embedded styles
        with open(srt_abs, 'r', encoding='utf-8') as f:
            srt_content = f.read()
        ass_content = self._srt_to_ass(srt_content, self.width, self.height)
        with open(ass_full, 'w', encoding='utf-8') as f:
            f.write(ass_content)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_abs,
            "-vf", f"ass={ass_name}",   # filename only — cwd is srt_dir
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "copy",
            "-b:v", self.video_bitrate,
            "-movflags", "+faststart",
            output_abs,
        ]
        # Run from srt_dir — FFmpeg finds ass file by name, no path issues
        self._run(cmd, "burn_subtitles", cwd=srt_dir)

    @staticmethod
    def _srt_to_ass(srt_content: str, play_res_x: int = 1080, play_res_y: int = 1920) -> str:
        """
        Convert SRT text to ASS format with proper embedded styles.
        ASS embeds all style in the file header — no force_style quoting needed.
        Style: white italic bold Arial, lower-center position (like reference image).
        """
        import re as _re

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,55,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,1,0,0,100,100,0,0,1,3,2,2,10,10,700,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        def srt_ts_to_ass(ts: str) -> str:
            """Convert 00:00:01,000 → 0:00:01.00"""
            ts = ts.strip().replace(',', '.')
            parts = ts.split(':')
            h = int(parts[0])
            m = parts[1]
            s_cs = parts[2].split('.')
            s  = s_cs[0]
            cs = s_cs[1][:2] if len(s_cs) > 1 else '00'
            return f"{h}:{m}:{s}.{cs}"

        dialogue = []
        blocks = _re.split(r'\n\s*\n', srt_content.strip())
        for block in blocks:
            lines = block.strip().splitlines()
            if len(lines) < 2:
                continue
            ts_line = None
            text_start = 2
            for idx, line in enumerate(lines):
                if '-->' in line:
                    ts_line = line
                    text_start = idx + 1
                    break
            if not ts_line:
                continue
            arrow_parts = ts_line.split('-->')
            if len(arrow_parts) != 2:
                continue
            start_ass = srt_ts_to_ass(arrow_parts[0])
            end_ass   = srt_ts_to_ass(arrow_parts[1])
            text = r'\N'.join(lines[text_start:])
            dialogue.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}")

        return header + '\n'.join(dialogue) + '\n'

    def _generate_thumbnail(self, video_path: str, out_path: str):
        """Grab a frame at 2s as JPEG thumbnail."""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", "00:00:02",
            "-vframes", "1",
            "-q:v", "2",
            out_path,
        ]
        self._run(cmd, "thumbnail")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _run(cmd: List[str], label: str, cwd: str = None):
        """Run an FFmpeg command, raise RuntimeError on failure."""
        logger.debug(f"[{label}] cwd={cwd} " + " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        if r.returncode != 0:
            err = r.stderr[-800:] if r.stderr else "no stderr"
            logger.error(f"FFmpeg [{label}] failed:\n{err}")
            raise RuntimeError(f"FFmpeg [{label}] failed: {err[-300:]}")

    def _check_ffmpeg(self):
        """Verify FFmpeg is installed and on PATH."""
        try:
            r = subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            line = r.stdout.decode(errors="replace").split("\n")[0]
            logger.info(f"FFmpeg OK: {line}")
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise RuntimeError(
                "FFmpeg not found! Install from https://ffmpeg.org/download.html "
                "and add to PATH."
            )

    def get_video_info(self, video_path: str) -> dict:
        """Return metadata dict for a video file via ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            video_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {r.stderr}")
        data = json.loads(r.stdout)

        fmt  = data.get("format", {})
        vstr = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        astr = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})

        try:
            fps_val = eval(vstr.get("r_frame_rate", "0/1"))
        except Exception:
            fps_val = 0

        return {
            "duration":         float(fmt.get("duration", 0)),
            "size_bytes":       int(fmt.get("size", 0)),
            "size_gb":          round(int(fmt.get("size", 0)) / (1024**3), 2),
            "bitrate":          fmt.get("bit_rate", "unknown"),
            "format":           fmt.get("format_name", "unknown"),
            "width":            vstr.get("width"),
            "height":           vstr.get("height"),
            "fps":              fps_val,
            "video_codec":      vstr.get("codec_name"),
            "audio_codec":      astr.get("codec_name"),
            "audio_sample_rate": astr.get("sample_rate"),
        }
