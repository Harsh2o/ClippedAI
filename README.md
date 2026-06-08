# ✂️ ClippedAI — YouTube Shorts Auto-Generator

> **100% Local • Free Forever • No API Keys Required**

Turn any 2-hour+ movie, stream, or podcast into viral YouTube Shorts automatically using local AI.

---

## 🚀 What It Does

1. **📁 Upload** any long video (MP4, MKV, MOV, AVI, etc.)
2. **🎤 Transcribe** locally with OpenAI Whisper (no internet needed)
3. **🧠 AI Scores** every segment by energy, emotion, pacing, and audio
4. **✂️ Cuts** the best 30–58 second moments
5. **📐 Crops** to 9:16 vertical format with blurred background
6. **💬 Burns** stylized subtitles/captions into each clip
7. **📤 Uploads** automatically to YouTube via API (optional)

---

## ⚡ Quick Start

### Prerequisites

| Tool | Download |
|------|----------|
| **Python 3.9+** | [python.org](https://www.python.org/downloads/) |
| **FFmpeg** | [github.com/BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases) — get `ffmpeg-master-latest-win64-gpl.zip` |

### Installation

```bat
# 1. Run the setup script (installs everything)
setup.bat

# 2. Start the web UI
run_web.bat

# 3. Open in browser
http://localhost:5000
```

### CLI Usage

```bat
# Basic usage
venv\Scripts\python.exe main.py --video "movie.mp4"

# More options
venv\Scripts\python.exe main.py --video "movie.mp4" --clips 10 --model medium

# Auto-upload to YouTube
venv\Scripts\python.exe main.py --video "movie.mp4" --upload
```

---

## 🎛️ Configuration

Edit `config.yaml` to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `whisper.model` | `base` | `tiny/base/small/medium/large` |
| `scoring.num_clips` | `8` | How many Shorts to generate |
| `scoring.min_clip_duration` | `30s` | Minimum Short length |
| `scoring.max_clip_duration` | `58s` | Maximum Short length |
| `video.blur_background` | `true` | Blurred 16:9 bg behind portrait crop |
| `youtube.auto_upload` | `false` | Auto-upload after processing |
| `youtube.privacy` | `public` | `public/unlisted/private` |

---

## 📤 YouTube Auto-Upload Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → **APIs & Services → Enable APIs**
3. Search for **YouTube Data API v3** → Enable it
4. Go to **APIs & Services → Credentials**
5. Create **OAuth 2.0 Client ID** (Application type: **Desktop app**)
6. Download the JSON file → rename to `credentials.json`
7. Place it in the `client_secrets/` folder
8. In the web UI, click **"Connect YouTube"** → authenticate

> **Note**: Free YouTube API quota allows ~6 uploads/day.
> Apply for higher quota at Google Cloud Console if needed.

---

## 🤖 Whisper Model Sizes

| Model | Speed | Accuracy | VRAM/RAM |
|-------|-------|----------|----------|
| `tiny` | ~1 min | Basic | 1GB |
| `base` | ~5 min | Good | 1GB |
| `small` | ~10 min | Better | 2GB |
| `medium` | ~20 min | Great | 5GB |
| `large` | ~40 min | Best | 10GB |

---

## 📁 Output Structure

```
output/
└── <job_id>/
    ├── short_01_final.mp4     ← Vertical Short with captions
    ├── short_01.srt           ← Subtitle file
    ├── short_01_thumb.jpg     ← Thumbnail
    ├── short_02_final.mp4
    ...
    └── results.json           ← Metadata for all clips
```

---

## 🛠️ Tech Stack

- **Whisper** — Local speech-to-text
- **FFmpeg** — Video processing, cropping, subtitle burning
- **Flask** — Web UI server
- **librosa** — Audio energy analysis
- **Google API** — YouTube uploads

---

## 📜 License

MIT — Free to use, modify, and distribute.
