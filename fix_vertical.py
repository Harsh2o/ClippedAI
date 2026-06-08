"""
ClippedAI — Fix Script (clean version)
Converts existing raw clips → 9:16 vertical + subtitles + thumbnails
"""
import os, sys, json, subprocess, shutil
from pathlib import Path

OUTPUT_DIR   = Path(r"c:\Users\hemla\Downloads\inter\ClippedAI\output\313ebc86")
TRANSCRIPT_F = Path(r"c:\Users\hemla\Downloads\inter\ClippedAI\uploads") / \
               "313ebc86_Dhurandhar 2 - The Revenge (2026) Bollywood Hindi Movie HD 720p ESub.transcript.json"

W, H  = 1080, 1920
FPS   = 30
VBIT  = "4M"
ABIT  = "192k"
STYLE = ("FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
         "OutlineColour=&H00000000,Outline=3,Shadow=2,Bold=1,"
         "MarginV=80,Alignment=2")

# ── helpers ────────────────────────────────────────────────────────────────────
def run(cmd, label):
    print(f"    [{label}]...", end=" ", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FAILED")
        print("   ", r.stderr[-400:])
        return False
    print("OK")
    return True

def fmt_srt(s):
    ms = int((s % 1)*1000); s=int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d},{ms:03d}"

def write_srt(segs, path, clip_start):
    lines, i = [], 1
    for seg in segs:
        t0 = max(0, seg["start"] - clip_start)
        t1 = max(t0+0.1, seg["end"] - clip_start)
        words = seg["text"].strip().split()
        text  = "\n".join(" ".join(words[j:j+7]) for j in range(0,len(words),7))
        lines += [str(i), f"{fmt_srt(t0)} --> {fmt_srt(t1)}", text, ""]
        i += 1
    Path(path).write_text("\n".join(lines), encoding="utf-8")

def escape_srt(path):
    """Proper Windows path escaping for FFmpeg subtitle filter."""
    fwd = Path(path).as_posix()          # C:/Users/.../file.srt
    parts = fwd.split(":", 1)
    if len(parts) == 2:
        return parts[0] + "\\:" + parts[1]
    return fwd

def get_duration(path):
    r = subprocess.run(["ffprobe","-v","quiet","-print_format","json",
                        "-show_format", str(path)], capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])

# ── load transcript ────────────────────────────────────────────────────────────
print("\n[INFO] Loading transcript...")
with open(TRANSCRIPT_F, "r", encoding="utf-8") as f:
    transcript = json.load(f)
segs      = transcript["segments"]
total_dur = transcript["duration"]
print(f"[INFO] {len(segs)} segments, video duration = {total_dur/60:.1f} min")

raw_clips = sorted(OUTPUT_DIR.glob("short_0*_raw.mp4"))
print(f"[INFO] Found {len(raw_clips)} raw clips\n")

results = []
for i, raw in enumerate(raw_clips):
    n          = i + 1
    vertical   = OUTPUT_DIR / f"short_{n:02d}_vertical.mp4"
    srt_path   = OUTPUT_DIR / f"short_{n:02d}.srt"
    final      = OUTPUT_DIR / f"short_{n:02d}_final.mp4"
    thumb      = OUTPUT_DIR / f"short_{n:02d}_thumb.jpg"

    print(f"{'─'*55}")
    print(f" Clip {n}/{len(raw_clips)}: {raw.name}")

    # skip if final already correct 9:16 and large enough (>10MB)
    if final.exists() and final.stat().st_size > 10_000_000:
        r2   = subprocess.run(["ffprobe","-v","quiet","-print_format","json",
                               "-show_streams", str(final)], capture_output=True, text=True)
        info = json.loads(r2.stdout)
        vs   = next((s for s in info.get("streams",[]) if s.get("codec_type")=="video"), {})
        if vs.get("width") == W and vs.get("height") == H:
            print(f"  Already {W}x{H} ({round(final.stat().st_size/1e6,1)} MB) — skipping")
            results.append({"n": n, "status": "ok", "file": str(final),
                             "dim": f"{W}x{H}", "mb": round(final.stat().st_size/1e6,1)})
            continue
        else:
            print(f"  Final exists but wrong size ({vs.get('width')}x{vs.get('height')}) — reprocessing")

    clip_dur   = get_duration(raw)
    # Estimate position in original video (evenly spaced)
    clip_start = (total_dur / (len(raw_clips) + 1)) * (i + 0.5)
    clip_end   = clip_start + clip_dur
    print(f"  Duration={clip_dur:.1f}s  est. start={clip_start/60:.1f}min")

    # ── Step 1: 9:16 vertical with blur background ─────────────────────────
    fc = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase"
        f",crop={W}:{H},boxblur=25:5[bg];"
        f"[0:v]scale=-2:{H}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}[out]"
    )
    ok = run([
        "ffmpeg","-y","-i",str(raw),
        "-filter_complex", fc,
        "-map","[out]","-map","0:a?",
        "-c:v","libx264","-preset","fast",
        "-c:a","aac",
        "-b:v",VBIT,"-b:a",ABIT,
        "-movflags","+faststart",
        str(vertical)
    ], "9:16 vertical")

    if not ok:
        results.append({"n": n, "status": "error", "step": "vertical"})
        continue

    # ── Step 2: Subtitles ──────────────────────────────────────────────────
    clip_segs = [s for s in segs if s["start"] >= clip_start-2 and s["end"] <= clip_end+2]
    if not clip_segs:
        clip_segs = sorted(segs, key=lambda s: abs(s["start"]-clip_start))[:10]
    write_srt(clip_segs, srt_path, clip_start)
    print(f"    [srt] {len(clip_segs)} subtitle lines written")

    # ── Step 3: Burn subtitles ─────────────────────────────────────────────
    ok2 = run([
        "ffmpeg","-y","-i",str(vertical),
        "-vf", f"subtitles='{escape_srt(srt_path)}':force_style='{STYLE}'",
        "-c:v","libx264","-preset","fast",
        "-c:a","aac",
        "-b:v",VBIT,"-b:a",ABIT,
        "-movflags","+faststart",
        str(final)
    ], "burn subtitles")

    if not ok2:
        print("  Subtitle burn failed — saving without subtitles")
        shutil.copy(str(vertical), str(final))

    # ── Step 4: Thumbnail ──────────────────────────────────────────────────
    run(["ffmpeg","-y","-i",str(final),"-ss","00:00:02",
         "-vframes","1","-q:v","2", str(thumb)], "thumbnail")

    # cleanup vertical temp
    if vertical.exists():
        vertical.unlink()

    # verify
    r2   = subprocess.run(["ffprobe","-v","quiet","-print_format","json",
                            "-show_streams",str(final)], capture_output=True, text=True)
    info = json.loads(r2.stdout)
    vs   = next((s for s in info["streams"] if s.get("codec_type")=="video"), {})
    mb   = round(final.stat().st_size/1e6, 1)
    dim  = f"{vs.get('width','?')}x{vs.get('height','?')}"
    print(f"  => {final.name}  {dim}  {mb} MB")
    results.append({"n": n, "status": "ok", "file": str(final), "dim": dim, "mb": mb})

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print("FINAL RESULTS:")
all_ok = True
for r in results:
    ok = r["status"] == "ok"
    if not ok: all_ok = False
    tag = "OK  " if ok else "FAIL"
    extra = f"{r['dim']}  {r['mb']} MB" if ok else f"step={r.get('step','?')}"
    print(f"  [{tag}] short_{r['n']:02d}_final.mp4  {extra}")

print(f"{'='*55}")
if all_ok:
    print(f"\nAll {len(results)} Shorts are 9:16 and ready!")
    print(f"Folder: {OUTPUT_DIR}\n")
else:
    print("\nSome clips failed — check errors above.\n")
