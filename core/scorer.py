"""
╔══════════════════════════════════════════════╗
║   ClippedAI — AI Highlight Scorer            ║
╚══════════════════════════════════════════════╝

Multi-factor scoring engine that identifies the most
compelling moments in a long video for YouTube Shorts.

Scoring factors:
  1. Sentence energy (exclamations, strong verbs, caps)
  2. Emotional keyword density
  3. Audio amplitude (RMS via librosa)
  4. Pacing (words per minute burst)
  5. Coherence (sentence completeness)
"""

import re
import math
import logging
import numpy as np
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─── Emotional / High-energy keywords ───────────────────────────────────────
ENERGY_KEYWORDS = {
    # Extreme positives
    "amazing", "incredible", "unbelievable", "insane", "crazy", "epic",
    "legendary", "goat", "perfect", "genius", "brilliant", "masterpiece",
    "best", "greatest", "wow", "omg", "mind-blowing", "outstanding",
    # Tension / conflict
    "never", "impossible", "secret", "shocking", "terrifying", "dangerous",
    "deadly", "critical", "urgent", "breaking", "exclusive", "revealed",
    "exposed", "truth", "lie", "fake", "real", "proof", "evidence",
    # Action
    "fight", "win", "lose", "defeat", "victory", "comeback", "explosion",
    "fire", "attack", "escape", "survive", "die", "kill", "destroy",
    # Social / viral
    "wait", "watch", "look", "see", "listen", "believe", "trust",
    "finally", "suddenly", "immediately", "just", "only",
}

NEGATIVE_KEYWORDS = {
    "um", "uh", "hmm", "anyway", "basically", "so", "like", "okay",
    "alright", "moving on", "next slide", "as I was saying",
}


@dataclass
class ScoredClip:
    """A candidate clip with scoring metadata."""
    start: float           # seconds
    end: float             # seconds
    score: float           # normalized 0.0–1.0
    text: str              # full transcript text
    segments: List[dict]   # original whisper segments
    title: str = ""        # auto-generated title
    breakdown: Dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        # Convert any numpy types to native Python for JSON serialization
        safe_breakdown = {k: float(v) if hasattr(v, 'item') else v
                          for k, v in self.breakdown.items()}
        return {
            "start": round(float(self.start), 2),
            "end": round(float(self.end), 2),
            "duration": round(float(self.duration), 2),
            "score": round(float(self.score), 4),
            "text": self.text[:200] + "..." if len(self.text) > 200 else self.text,
            "title": self.title,
            "breakdown": safe_breakdown,
        }


class HighlightScorer:
    """
    Scores all possible clip windows in a transcript and returns
    the best N non-overlapping clips.
    """

    def __init__(self, config: dict):
        self.min_dur = config.get("min_clip_duration", 30)
        # MUST be strictly under 60s for YouTube Shorts revenue-share policy
        self.max_dur = config.get("max_clip_duration", 59)
        self.num_clips = config.get("num_clips", 8)
        self.overlap_threshold = config.get("overlap_threshold", 15)

    def score(
        self,
        transcript: dict,
        video_path: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> List[ScoredClip]:
        """
        Main scoring pipeline. Returns top N clips sorted by score (descending).
        """
        segments = transcript["segments"]
        duration = transcript["duration"]

        if progress_callback:
            progress_callback("scoring", "AI is analyzing highlights...")

        logger.info(f"Scoring {len(segments)} segments over {duration:.0f}s video")

        # Load audio for energy analysis if possible
        audio_rms = self._load_audio_energy(video_path) if video_path else None

        # Slide a window through all segments
        candidates = []
        i = 0
        while i < len(segments):
            window_segs = []
            window_dur = 0.0
            j = i

            # Build window up to max duration STRICTLY
            while j < len(segments) and window_dur < self.max_dur:
                seg = segments[j]
                seg_dur = seg["end"] - seg["start"]
                # Strict cutoff: do not exceed max_dur
                if window_dur + seg_dur > self.max_dur:
                    break
                window_segs.append(seg)
                window_dur = segments[j]["end"] - segments[i]["start"]
                j += 1

            if window_dur >= self.min_dur and window_segs:
                clip_start = window_segs[0]["start"]
                clip_end = min(window_segs[-1]["end"], clip_start + self.max_dur)
                clip_end = max(clip_start + self.min_dur, clip_end)

                text = " ".join(s["text"] for s in window_segs)
                score, breakdown = self._score_window(
                    window_segs, text, clip_start, clip_end, audio_rms, duration
                )

                candidates.append(ScoredClip(
                    start=clip_start,
                    end=clip_end,
                    score=score,
                    text=text,
                    segments=window_segs,
                    breakdown=breakdown,
                ))

            i += max(1, len(window_segs) // 2)  # 50% stride

        if not candidates:
            logger.warning("No candidates found, using equal-interval fallback")
            return self._fallback_clips(transcript)

        # Sort by score
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Remove overlapping clips (greedy)
        selected = self._deduplicate(candidates)

        # Cloud AI Hook Detection (Groq)
        import os
        api_key = os.environ.get("GROQ_API_KEY")
        if api_key and api_key != "your_groq_api_key_here":
            logger.info("Using Groq API for hook detection and title generation")
            if progress_callback:
                progress_callback("scoring", "Using Groq AI to detect viral hooks...")
            try:
                from groq import Groq
                client = Groq(api_key=api_key)
                
                for idx, clip in enumerate(selected):
                    prompt = f"Analyze this video clip transcript and evaluate its potential as a viral YouTube Short. Provide a viral title (under 50 chars, 1 emoji) and a virality score from 0.0 to 1.0.\n\nTranscript: {clip.text}\n\nReturn ONLY a valid JSON object in this exact format: {{\"title\": \"Viral Title Here 🔥\", \"score\": 0.95}}"
                    
                    response = client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model="llama3-8b-8192",
                        temperature=0.7,
                        max_tokens=60,
                        response_format={"type": "json_object"}
                    )
                    
                    import json
                    res_json = json.loads(response.choices[0].message.content)
                    clip.title = res_json.get("title", self._generate_title(clip, idx))
                    # Blend the Groq score with the local score
                    groq_score = float(res_json.get("score", clip.score))
                    clip.score = (clip.score * 0.3) + (groq_score * 0.7)
                    clip.breakdown["groq_virality_score"] = groq_score
                    
                # Re-sort after Groq scoring
                selected.sort(key=lambda c: c.score, reverse=True)
                
            except Exception as e:
                logger.error(f"Groq API error: {e}")
                # Fallback to local
                for idx, clip in enumerate(selected):
                    clip.title = self._generate_title(clip, idx)
        else:
            # Add auto-generated titles (Local Fallback)
            for idx, clip in enumerate(selected):
                clip.title = self._generate_title(clip, idx)

        if progress_callback:
            progress_callback(
                "scoring_done",
                f"Found {len(selected)} top highlights!"
            )

        logger.info(f"Selected {len(selected)} clips")
        return selected

    # ─── Scoring Functions ─────────────────────────────────────────────────

    def _score_window(
        self,
        segs: list,
        text: str,
        start: float,
        end: float,
        audio_rms: Optional[np.ndarray],
        total_duration: float,
    ) -> tuple:
        """Compute composite score for a window of segments."""

        text_lower = text.lower()
        words = re.findall(r'\b\w+\b', text_lower)
        num_words = max(1, len(words))
        duration = max(1, end - start)

        # 1. Energy keyword score (0–1)
        energy_hits = sum(1 for w in words if w in ENERGY_KEYWORDS)
        negative_hits = sum(1 for w in words if w in NEGATIVE_KEYWORDS)
        keyword_score = min(1.0, (energy_hits - negative_hits * 0.3) / max(1, num_words / 10))
        keyword_score = max(0.0, keyword_score)

        # 2. Sentence energy score (punctuation, caps)
        exclamations = text.count("!") + text.count("?")
        caps_ratio = sum(1 for c in text if c.isupper()) / max(1, len(text))
        sentence_score = min(1.0, exclamations * 0.15 + caps_ratio * 2.0)

        # 3. Pacing score (words per minute burst)
        wpm = (num_words / duration) * 60
        # Ideal for Shorts: 120–180 WPM
        if 120 <= wpm <= 180:
            pacing_score = 1.0
        elif wpm < 120:
            pacing_score = max(0.0, wpm / 120)
        else:
            pacing_score = max(0.0, 1.0 - (wpm - 180) / 180)

        # 4. Coherence score (complete sentences)
        sentence_endings = text.count(".") + text.count("!") + text.count("?")
        coherence_score = min(1.0, sentence_endings / max(1, duration / 10))

        # 5. Audio energy score
        if audio_rms is not None:
            sr_approx = len(audio_rms) / total_duration
            seg_start_idx = int(start * sr_approx)
            seg_end_idx = int(end * sr_approx)
            seg_start_idx = max(0, min(seg_start_idx, len(audio_rms) - 1))
            seg_end_idx = max(seg_start_idx + 1, min(seg_end_idx, len(audio_rms)))
            clip_rms = audio_rms[seg_start_idx:seg_end_idx]
            global_mean = np.mean(audio_rms) + 1e-9
            audio_score = min(1.0, float(np.mean(clip_rms)) / global_mean)
        else:
            audio_score = 0.5

        # 6. Position bonus (avoid first/last 5% of video — often intro/outro)
        mid_ratio = (start / total_duration)
        if 0.05 <= mid_ratio <= 0.90:
            position_score = 1.0
        else:
            position_score = 0.4

        # ─── Weighted composite ─────────────────────────────────
        weights = {
            "keyword": 0.30,
            "sentence": 0.20,
            "pacing": 0.15,
            "coherence": 0.15,
            "audio": 0.15,
            "position": 0.05,
        }
        composite = (
            keyword_score * weights["keyword"] +
            sentence_score * weights["sentence"] +
            pacing_score * weights["pacing"] +
            coherence_score * weights["coherence"] +
            audio_score * weights["audio"] +
            position_score * weights["position"]
        )

        breakdown = {
            "keyword": round(float(keyword_score), 3),
            "sentence_energy": round(float(sentence_score), 3),
            "pacing": round(float(pacing_score), 3),
            "coherence": round(float(coherence_score), 3),
            "audio_energy": round(float(audio_score), 3),
            "position": round(float(position_score), 3),
            "wpm": round(float(wpm), 1),
            "energy_keywords_found": int(energy_hits),
        }

        return round(float(composite), 4), breakdown

    def _load_audio_energy(self, video_path: str) -> Optional[np.ndarray]:
        """Extract RMS energy curve from video audio track."""
        try:
            import librosa
            import tempfile
            import subprocess
            import os

            # Extract audio to temp wav
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-ac", "1", "-ar", "16000",
                 "-vn", tmp_path],
                capture_output=True, check=True
            )

            y, sr = librosa.load(tmp_path, sr=16000, mono=True)
            frame_length = 2048
            hop_length = 512
            rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
            os.unlink(tmp_path)
            return rms

        except Exception as e:
            logger.warning(f"Audio energy extraction failed (scoring will use text only): {e}")
            return None

    def _deduplicate(self, candidates: List[ScoredClip]) -> List[ScoredClip]:
        """Greedy deduplication — remove clips that overlap more than threshold."""
        selected = []
        for clip in candidates:
            if len(selected) >= self.num_clips:
                break
            overlap = False
            for sel in selected:
                # Check overlap
                latest_start = max(clip.start, sel.start)
                earliest_end = min(clip.end, sel.end)
                if earliest_end - latest_start > self.overlap_threshold:
                    overlap = True
                    break
            if not overlap:
                selected.append(clip)
        return selected

    def _fallback_clips(self, transcript: dict) -> List[ScoredClip]:
        """Equal-interval fallback when scoring fails."""
        duration = transcript["duration"]
        clips = []
        interval = duration / (self.num_clips + 1)
        for i in range(self.num_clips):
            start = interval * (i + 0.5)
            end = min(start + self.max_dur, duration)
            segs = [s for s in transcript["segments"]
                    if s["start"] >= start and s["end"] <= end + 5]
            text = " ".join(s["text"] for s in segs)
            clips.append(ScoredClip(
                start=start, end=end,
                score=0.5 - i * 0.05,
                text=text, segments=segs,
            ))
        return clips

    def _generate_title(self, clip: ScoredClip, idx: int) -> str:
        """Generate a viral, hook-style title from the clip text."""
        text = clip.text.strip()
        # Find the most energetic sentence
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        if not sentences:
            return f"Best Moment #{idx + 1} 🤯"

        # Score each sentence by keyword hits
        best = max(sentences, key=lambda s: sum(
            1 for w in s.lower().split() if w in ENERGY_KEYWORDS
        ))

        # Add a viral hook prefix if it makes sense
        hooks = ["Wait for it...", "This is hilarious 😂", "Bro really said...", "I can't believe this 💀", "That moment when..."]
        import random
        hook = random.choice(hooks)

        # Truncate and format
        best = best[:40].strip() # Keep it short for mobile
        if not best.endswith(('.', '!', '?')):
            best += "..."
            
        final_title = f"{hook} {best}"
        if len(final_title) > 60:
            final_title = final_title[:57] + "..."
            
        # Ensure there's an emoji
        if not any(e in final_title for e in ['😂', '💀', '🤯', '😭', '🔥']):
            final_title += " 😂"

        return final_title.strip()
