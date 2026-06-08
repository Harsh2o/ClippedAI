"""
ClippedAI — Auto Upload All 5 Shorts to YouTube
Reads existing final clips and uploads them one by one.
"""
import os, sys, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["PYTHONUTF8"] = "1"

import yaml
from core.uploader import YouTubeUploader

# ── Config ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(r"c:\Users\hemla\Downloads\inter\ClippedAI\output\313ebc86")
CONFIG_F   = Path(r"c:\Users\hemla\Downloads\inter\ClippedAI\config.yaml")

with open(CONFIG_F, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Override to public uploads
config["youtube"]["privacy"] = "public"

# ── Find all final clips ────────────────────────────────────────────────────────
finals = sorted(OUTPUT_DIR.glob("short_0*_final.mp4"))
thumbs = {p.stem.replace("_final",""): p for p in OUTPUT_DIR.glob("short_0*_thumb.jpg")}

print(f"\n{'='*60}")
print(f"  ClippedAI — YouTube Auto Uploader")
print(f"  Found {len(finals)} Shorts to upload")
print(f"{'='*60}\n")

if not finals:
    print("ERROR: No final clips found in:", OUTPUT_DIR)
    sys.exit(1)

# ── Titles for each clip (can be customised) ──────────────────────────────────
titles = [
    "Dhurandhar 2 Best Scene Part 1",
    "Dhurandhar 2 Best Scene Part 2",
    "Dhurandhar 2 Best Scene Part 3",
    "Dhurandhar 2 Best Scene Part 4",
    "Dhurandhar 2 Best Scene Part 5",
]

description = (
    "Watch the best moments from Dhurandhar 2 - The Revenge (2026)!\n\n"
    "#Shorts #Bollywood #Dhurandhar2 #HindiMovie #Viral #YouTubeShorts"
)

tags = ["Shorts", "YouTubeShorts", "Bollywood", "Dhurandhar2",
        "HindiMovie", "Viral", "2026", "BollywoodShorts"]

# ── Authenticate ───────────────────────────────────────────────────────────────
print("[1/2] Authenticating with YouTube...")
uploader = YouTubeUploader(config)

def progress(event, msg):
    print(f"  [{event}] {msg}")

uploader.authenticate(progress_callback=progress)
print("  OK — Authenticated!\n")

# ── Upload each clip ───────────────────────────────────────────────────────────
print(f"[2/2] Uploading {len(finals)} Shorts...\n")

results = []
for i, clip_path in enumerate(finals):
    n     = i + 1
    title = titles[i] if i < len(titles) else f"Dhurandhar 2 Highlight #{n}"
    stem  = clip_path.stem.replace("_final", "")
    thumb = thumbs.get(stem)

    print(f"  {'─'*55}")
    print(f"  Uploading Short {n}/{len(finals)}: {clip_path.name}")
    print(f"  Title : {title} #Shorts")
    print(f"  Size  : {clip_path.stat().st_size / 1e6:.1f} MB")
    if thumb:
        print(f"  Thumb : {thumb.name}")

    try:
        result = uploader.upload(
            video_path=str(clip_path),
            title=title,
            description=description,
            tags=tags,
            thumbnail_path=str(thumb) if thumb else None,
            progress_callback=progress,
        )
        results.append({"n": n, "status": "ok", "url": result.get("url"), "video_id": result.get("video_id")})
        print(f"\n  LIVE: {result['url']}\n")

    except Exception as e:
        print(f"\n  FAILED: {e}\n")
        results.append({"n": n, "status": "error", "error": str(e)})

    # Wait 15s between uploads to avoid quota limits
    if i < len(finals) - 1:
        print(f"  Waiting 15s before next upload...")
        time.sleep(15)

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("  UPLOAD RESULTS:")
print(f"{'='*60}")
for r in results:
    if r["status"] == "ok":
        print(f"  [OK] Short {r['n']}: {r.get('url', '?')}")
    else:
        print(f"  [FAIL] Short {r['n']}: {r.get('error','?')}")

ok_count = sum(1 for r in results if r["status"] == "ok")
print(f"\n  {ok_count}/{len(finals)} Shorts uploaded successfully!")
print(f"{'='*60}\n")

# Save results
out = OUTPUT_DIR / "upload_results.json"
with open(out, "w") as f:
    json.dump(results, f, indent=2)
print(f"  Results saved to: {out}\n")
