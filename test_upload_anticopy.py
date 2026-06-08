"""
ClippedAI — Anti-Copyright Test & Upload
Takes one raw clip, applies stealth filters (mirror + color tweak + crop),
burns subtitles, and uploads directly to YouTube!
"""
import os, sys, json, subprocess, time
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(r"c:\Users\hemla\Downloads\inter\ClippedAI")
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["PYTHONUTF8"] = "1"

import yaml
from core.uploader import YouTubeUploader

DIR      = PROJECT_ROOT / "output" / "313ebc86"
RAW      = DIR / "short_01_raw.mp4"
SRT      = DIR / "short_01.srt"
TEMP_V   = DIR / "temp_anticopy_vertical.mp4"
FINAL    = DIR / "short_01_anticopyright.mp4"
CONFIG_F = PROJECT_ROOT / "config.yaml"

W, H = 1080, 1920
FPS  = 30
STYLE = ("FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
         "OutlineColour=&H00000000,Outline=3,Shadow=2,Bold=1,"
         "MarginV=80,Alignment=2")

def run(cmd, label):
    print(f"[{label}] Running...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAILED!\n{r.stderr[-500:]}")
        sys.exit(1)
    print(f"[{label}] Done!")

def escape_srt(path):
    fwd = Path(path).as_posix()
    parts = fwd.split(":", 1)
    return parts[0] + "\\:" + parts[1] if len(parts) == 2 else fwd

print("="*60)
print("  Applying Anti-Copyright Filters to Clip 1...")
print("="*60)

# 1. Anti-Copyright Vertical Conversion (Mirror + Color Tweak + Blur)
fc = (
    f"[0:v]hflip,eq=contrast=1.05:saturation=1.1,"
    f"scale={W}:{H}:force_original_aspect_ratio=increase,"
    f"crop={W}:{H},boxblur=25:5[bg];"
    
    f"[0:v]hflip,eq=contrast=1.05:saturation=1.1,"
    f"scale=-2:{H}[fg];"
    
    f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}[out]"
)

run([
    "ffmpeg", "-y", "-i", str(RAW),
    "-filter_complex", fc,
    "-map", "[out]", "-map", "0:a",
    "-c:v", "libx264", "-preset", "fast",
    "-c:a", "aac", "-b:v", "4M", "-b:a", "192k",
    "-movflags", "+faststart", str(TEMP_V)
], "Anti-Copyright Filter (Mirror + Colors)")

# 2. Burn Subtitles (They will be readable since they are applied AFTER mirror!)
run([
    "ffmpeg", "-y", "-i", str(TEMP_V),
    "-vf", f"subtitles='{escape_srt(SRT)}':force_style='{STYLE}'",
    "-c:v", "libx264", "-preset", "fast",
    "-c:a", "aac", "-b:v", "4M", "-b:a", "192k",
    "-movflags", "+faststart", str(FINAL)
], "Burn Subtitles")

# Cleanup temp
if TEMP_V.exists(): TEMP_V.unlink()

# 3. Upload to YouTube
print("\n" + "="*60)
print("  Uploading Anti-Copyright Short to YouTube...")
print("="*60)

with open(CONFIG_F, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Force public
config["youtube"]["privacy"] = "public"

uploader = YouTubeUploader(config)
uploader.authenticate()

result = uploader.upload(
    video_path=str(FINAL),
    title="Dhurandhar 2 - Epic Moment (Mirrored Test) #Shorts",
    description="Testing anti-copyright bypass with mirroring and color adjustments.",
    tags=["Shorts", "Testing", "Bypass", "Bollywood", "Dhurandhar2"],
    thumbnail_path=None
)

print("\n" + "="*60)
print(f"🎉 SUCCESS! Video is live here:")
print(f"👉 {result['url']}")
print("="*60 + "\n")
