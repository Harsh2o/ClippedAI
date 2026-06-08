"""
╔══════════════════════════════════════════════╗
║   ClippedAI — CLI Entry Point                ║
╚══════════════════════════════════════════════╝

Usage:
  python main.py --video path/to/video.mp4
  python main.py --video path/to/video.mp4 --clips 10 --model medium
  python main.py --video path/to/video.mp4 --upload
"""

import argparse
import logging
import sys
import os
import json
from pathlib import Path

import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("clippedai.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("clippedai")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def print_banner():
    print("\n" + "═" * 65)
    print("  ╔═╗╦  ╦╔═╔═╗╔═╗╔╦╗╔═╗╦")
    print("  ║  ║  ║╠═╠═╝╠═╝ ║ ╠═ ║")
    print("  ╚═╝╩═╝╩╩ ╩  ╩   ╩ ╚═╝╩")
    print("  YouTube Shorts Auto-Generator  🎬")
    print("═" * 65 + "\n")


def print_event(event: str, message: str):
    icons = {
        "start": "🚀", "info": "📊", "transcribing": "🎤",
        "transcription_done": "✅", "scoring": "🧠", "scoring_done": "🎯",
        "processing": "✂️", "clip_done": "✅", "uploading": "📤",
        "upload_done": "✅", "done": "🎉", "error": "❌", "fatal_error": "💥",
        "warning": "⚠️",
    }
    icon = icons.get(event, "•")
    print(f"  {icon}  {message}")


def main():
    print_banner()

    parser = argparse.ArgumentParser(
        description="ClippedAI — Automatically generate YouTube Shorts from long videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --video movie.mp4
  python main.py --video movie.mp4 --clips 5 --model small
  python main.py --video movie.mp4 --upload --privacy unlisted
  python main.py --web        # Start web UI instead
        """
    )

    parser.add_argument("--video", type=str, help="Path to input video file")
    parser.add_argument("--clips", type=int, help="Number of Shorts to generate (default: from config)")
    parser.add_argument("--model", choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model size (default: base)")
    parser.add_argument("--min-dur", type=int, help="Minimum clip duration in seconds")
    parser.add_argument("--max-dur", type=int, help="Maximum clip duration in seconds")
    parser.add_argument("--upload", action="store_true", help="Auto-upload to YouTube after processing")
    parser.add_argument("--privacy", choices=["public", "unlisted", "private"],
                        default=None, help="YouTube privacy setting")
    parser.add_argument("--output", type=str, default=None, help="Output directory")
    parser.add_argument("--no-blur", action="store_true", help="Disable blurred background")
    parser.add_argument("--web", action="store_true", help="Start the web UI (Flask)")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config file path")
    parser.add_argument("--skip-transcription", action="store_true",
                        help="Use cached transcript if available")

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Apply CLI overrides
    if args.clips:
        config.setdefault("scoring", {})["num_clips"] = args.clips
    if args.model:
        config.setdefault("whisper", {})["model"] = args.model
    if args.min_dur:
        config.setdefault("scoring", {})["min_clip_duration"] = args.min_dur
    if args.max_dur:
        config.setdefault("scoring", {})["max_clip_duration"] = args.max_dur
    if args.upload:
        config.setdefault("youtube", {})["auto_upload"] = True
    if args.privacy:
        config.setdefault("youtube", {})["privacy"] = args.privacy
    if args.output:
        config.setdefault("paths", {})["output_dir"] = args.output
    if args.no_blur:
        config.setdefault("video", {})["blur_background"] = False

    # ── Web mode ────────────────────────────────────────────────────────────
    if args.web:
        print("  🌐  Starting web UI at http://localhost:5000")
        print("  Press Ctrl+C to stop\n")
        from app import app
        app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
        return

    # ── CLI mode ─────────────────────────────────────────────────────────────
    if not args.video:
        parser.print_help()
        print("\n  ⚠️  Please provide --video or use --web for the web UI")
        sys.exit(1)

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"\n  ❌  Video not found: {args.video}")
        sys.exit(1)

    print(f"  📁  Input: {video_path.name}")
    print(f"  🤖  Whisper model: {config['whisper']['model']}")
    print(f"  📊  Target clips: {config['scoring']['num_clips']}")
    print(f"  ⏱️   Clip length: {config['scoring']['min_clip_duration']}–{config['scoring']['max_clip_duration']}s")
    print()

    # Import pipeline modules
    from core.transcribe import TranscriptionEngine
    from core.scorer import HighlightScorer
    from core.processor import VideoProcessor

    output_dir = Path(config["paths"]["output_dir"]) / video_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Transcription ────────────────────────────────────────────────────────
    whisper_cfg = config["whisper"]
    engine = TranscriptionEngine(
        model_size=whisper_cfg.get("model", "base"),
        device=whisper_cfg.get("device", "cpu"),
        language=whisper_cfg.get("language"),
    )

    transcript_path = str(video_path.with_suffix(".transcript.json"))
    if args.skip_transcription and os.path.exists(transcript_path):
        print_event("transcribing", "Loading cached transcript...")
        transcript = engine.load_transcript(transcript_path)
        print_event("transcription_done", f"Loaded: {len(transcript['segments'])} segments")
    else:
        transcript = engine.transcribe(str(video_path), progress_callback=print_event)
        engine.save_transcript(transcript, transcript_path)

    # ── Scoring ───────────────────────────────────────────────────────────────
    scorer = HighlightScorer(config["scoring"])
    clips = scorer.score(transcript, video_path=str(video_path), progress_callback=print_event)

    print(f"\n  {'─'*55}")
    print(f"  TOP HIGHLIGHTS:")
    for i, clip in enumerate(clips):
        print(f"  [{i+1}] {clip.start/60:.1f}m–{clip.end/60:.1f}m  "
              f"score={clip.score:.3f}  \"{clip.title[:50]}\"")
    print(f"  {'─'*55}\n")

    # ── Processing ────────────────────────────────────────────────────────────
    processor = VideoProcessor(config)
    processed = []
    for i, clip in enumerate(clips):
        print_event("processing", f"Processing clip {i+1}/{len(clips)}...")
        result = processor.process_clip(
            video_path=str(video_path),
            clip=clip,
            output_dir=str(output_dir),
            transcript=transcript,
            clip_index=i,
            progress_callback=print_event,
        )
        processed.append(result)

    # ── Summary ───────────────────────────────────────────────────────────────
    success = [c for c in processed if c.get("status") == "success"]
    print(f"\n  {'═'*55}")
    print(f"  ✅  {len(success)}/{len(clips)} Shorts generated!")
    print(f"  📁  Saved to: {output_dir}")
    for c in success:
        print(f"     • {Path(c['final_video']).name}  ({c.get('size_mb', '?')} MB)")

    # ── YouTube Upload ────────────────────────────────────────────────────────
    if config.get("youtube", {}).get("auto_upload", False):
        print(f"\n  {'─'*55}")
        print_event("uploading", "Uploading to YouTube...")
        from core.uploader import YouTubeUploader
        uploader = YouTubeUploader(config)
        results = uploader.upload_batch(success, progress_callback=print_event)
        print(f"\n  📤  Uploaded {len(results)} Shorts:")
        for r in results:
            if r.get("url"):
                print(f"     🔗  {r['url']}")

    # Save results JSON
    results_path = output_dir / "results.json"
    with open(results_path, "w") as f:
        json.dump(processed, f, indent=2)
    print(f"\n  📋  Results saved: {results_path}")
    print(f"  {'═'*55}\n")


if __name__ == "__main__":
    main()
