"""
╔══════════════════════════════════════════════╗
║   ClippedAI — Flask Web Server               ║
╚══════════════════════════════════════════════╝

Serves the web UI and orchestrates the full pipeline.
Uses Server-Sent Events (SSE) for real-time progress.
"""

import os
import json
import uuid
import queue
import logging
import threading
import time
import sys
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yaml
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, jsonify,
    send_file, Response, stream_with_context, session, redirect, url_for
)
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from authlib.integrations.flask_client import OAuth
import razorpay

# Load environment variables
load_dotenv()

from core.transcribe import TranscriptionEngine
from core.scorer import HighlightScorer
from core.processor import VideoProcessor
from core.uploader import YouTubeUploader

# ─── Setup ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback-dev-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "index"

# ─── Database Models ─────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    id = db.Column(db.String(255), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    profile_pic = db.Column(db.String(500))
    credits = db.Column(db.Integer, default=3)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# ─── OAuth Setup ─────────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ─── Razorpay Setup ──────────────────────────────────────────────────────────
razorpay_client = razorpay.Client(
    auth=(os.environ.get("RAZORPAY_KEY_ID", "dummy_key"), os.environ.get("RAZORPAY_KEY_SECRET", "dummy_secret"))
)

with app.app_context():
    db.create_all()

# ─── Config ─────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

UPLOAD_DIR = Path(CONFIG["paths"]["uploads_dir"])
OUTPUT_DIR = Path(CONFIG["paths"]["output_dir"])
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ─── Job State ───────────────────────────────────────────────────────────────
jobs: dict = {}          # job_id → { status, progress, results, ... }
job_queues: dict = {}    # job_id → Queue for SSE events


def emit(job_id: str, event: str, message: str, data: dict = None):
    """Push a progress event to the SSE queue for a job."""
    if job_id in job_queues:
        payload = {
            "event": event,
            "message": message,
            "timestamp": time.time(),
            "data": data or {}
        }
        job_queues[job_id].put(payload)
        # Also update job status
        if job_id in jobs:
            jobs[job_id]["last_event"] = event
            jobs[job_id]["last_message"] = message


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login")
def login():
    if not google.client_id or google.client_id == "your_google_client_id_here":
        # Fake login for dev if keys aren't set yet
        user = User.query.filter_by(email="founder@clippedai.com").first()
        if not user:
            user = User(id="dev123", email="founder@clippedai.com", name="Founder", credits=5)
            db.session.add(user)
            db.session.commit()
        login_user(user)
        return redirect(url_for("index"))
        
    redirect_uri = url_for("authorize", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/authorize")
def authorize():
    token = google.authorize_access_token()
    user_info = token.get("userinfo")
    
    if user_info:
        user = User.query.filter_by(email=user_info["email"]).first()
        if not user:
            # Create new user with 3 free credits
            user = User(
                id=user_info["sub"],
                email=user_info["email"],
                name=user_info["name"],
                profile_pic=user_info.get("picture"),
                credits=3
            )
            db.session.add(user)
            db.session.commit()
        
        login_user(user)
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/api/payment/create_order", methods=["POST"])
@login_required
def create_order():
    try:
        # 10 Credits for ₹190 (₹19 per video)
        amount = 19000  # Amount in paise (190 INR)
        
        # Dev Mode Fallback: if keys are dummy, don't call Razorpay API
        if os.environ.get("RAZORPAY_KEY_ID", "dummy_key") == "dummy_key":
            return jsonify({
                "order_id": f"dev_order_{int(time.time())}",
                "amount": amount,
                "key": "dummy_key"
            })

        data = {
            "amount": amount,
            "currency": "INR",
            "receipt": f"receipt_{current_user.id}_{int(time.time())}"
        }
        order = razorpay_client.order.create(data=data)
        return jsonify({
            "order_id": order["id"],
            "amount": amount,
            "key": os.environ.get("RAZORPAY_KEY_ID")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/payment/verify", methods=["POST"])
@login_required
def verify_payment():
    data = request.json
    try:
        # In a real app, you would verify the signature, but we'll bypass it for dev mode if the key is dummy
        if os.environ.get("RAZORPAY_KEY_ID") != "dummy_key" and os.environ.get("RAZORPAY_KEY_ID") is not None:
            razorpay_client.utility.verify_payment_signature(data)
            
        # Add 10 credits
        current_user.credits += 10
        db.session.commit()
        return jsonify({"status": "success", "credits": current_user.credits})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/upload", methods=["POST"])
def upload_video():
    """Accept video file upload."""
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Save the uploaded file
    job_id = str(uuid.uuid4())[:8]
    safe_name = f"{job_id}_{file.filename}"
    video_path = UPLOAD_DIR / safe_name
    file.save(str(video_path))

    # Get video info
    try:
        processor = VideoProcessor(CONFIG)
        info = processor.get_video_info(str(video_path))
    except Exception as e:
        info = {"error": str(e)}

    jobs[job_id] = {
        "job_id": job_id,
        "status": "uploaded",
        "video_path": str(video_path),
        "filename": file.filename,
        "video_info": info,
        "clips": [],
        "uploads": [],
        "created_at": time.time(),
    }

    logger.info(f"Job {job_id}: file uploaded → {video_path}")
    return jsonify({
        "job_id": job_id,
        "filename": file.filename,
        "video_info": info,
    })


@app.route("/api/start/<job_id>", methods=["POST"])
def start_processing(job_id: str):
    """Start the full processing pipeline for a job."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    if job["status"] == "processing":
        return jsonify({"error": "Already processing"}), 409

    # Read optional config overrides from request body
    body = request.get_json(silent=True) or {}
    override_config = CONFIG.copy()

    if "num_clips" in body:
        override_config.setdefault("scoring", {})["num_clips"] = int(body["num_clips"])
    if "model_size" in body:
        override_config.setdefault("whisper", {})["model"] = body["model_size"]
    if "auto_upload" in body:
        override_config.setdefault("youtube", {})["auto_upload"] = bool(body["auto_upload"])

    # Create SSE queue
    job_queues[job_id] = queue.Queue()
    job["status"] = "processing"
    job["config"] = override_config

    # Run pipeline in background thread
    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, job["video_path"], override_config),
        daemon=True
    )
    thread.start()

    return jsonify({"status": "started", "job_id": job_id})


@app.route("/api/events/<job_id>")
def sse_events(job_id: str):
    """Server-Sent Events endpoint for real-time progress."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    def generate():
        q = job_queues.get(job_id)
        if q is None:
            yield f"data: {json.dumps({'event': 'error', 'message': 'No event queue'})}\n\n"
            return

        while True:
            try:
                event = q.get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("event") in ("done", "error", "fatal_error"):
                    break
            except queue.Empty:
                # Send heartbeat
                yield f"data: {json.dumps({'event': 'heartbeat', 'message': '...'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/api/status/<job_id>")
def job_status(job_id: str):
    """Get current job status and results."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    job = jobs[job_id].copy()
    job.pop("config", None)  # don't expose full config
    return jsonify(job)


@app.route("/api/jobs")
def list_jobs():
    """List all jobs."""
    result = []
    for jid, job in jobs.items():
        result.append({
            "job_id": jid,
            "filename": job.get("filename"),
            "status": job.get("status"),
            "clips_count": len(job.get("clips", [])),
            "created_at": job.get("created_at"),
        })
    return jsonify(result)


@app.route("/api/download/<job_id>/<int:clip_index>")
def download_clip(job_id: str, clip_index: int):
    """Download a processed Short."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    clips = jobs[job_id].get("clips", [])
    clip = next((c for c in clips if c.get("clip_index") == clip_index), None)
    if not clip:
        return jsonify({"error": "Clip not found"}), 404
    video_path = clip.get("final_video")
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "Video file not found"}), 404
    return send_file(video_path, as_attachment=True)


@app.route("/api/thumbnail/<job_id>/<int:clip_index>")
def get_thumbnail(job_id: str, clip_index: int):
    """Serve thumbnail image for a clip."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    clips = jobs[job_id].get("clips", [])
    clip = next((c for c in clips if c.get("clip_index") == clip_index), None)
    if not clip:
        return jsonify({"error": "Clip not found"}), 404
    thumb = clip.get("thumbnail")
    if not thumb or not os.path.exists(thumb):
        return jsonify({"error": "Thumbnail not found"}), 404
    return send_file(thumb, mimetype="image/jpeg")


@app.route("/api/youtube/auth", methods=["POST"])
def youtube_auth():
    """Trigger YouTube OAuth authentication."""
    try:
        uploader = YouTubeUploader(CONFIG)
        uploader.authenticate()
        return jsonify({"status": "authenticated", "authenticated": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/youtube/status")
def youtube_status():
    """Check if YouTube is authenticated."""
    uploader = YouTubeUploader(CONFIG)
    return jsonify({
        "authenticated": uploader.is_authenticated,
        "token_file": str(uploader.token_file),
    })


@app.route("/api/youtube/logout", methods=["POST"])
def youtube_logout():
    """Revoke YouTube OAuth token."""
    uploader = YouTubeUploader(CONFIG)
    uploader.revoke_token()
    return jsonify({"status": "logged_out"})


@app.route("/api/upload_to_youtube/<job_id>/<int:clip_index>", methods=["POST"])
def upload_clip_to_youtube(job_id: str, clip_index: int):
    """Upload a specific clip to YouTube."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    clips = jobs[job_id].get("clips", [])
    clip = next((c for c in clips if c.get("clip_index") == clip_index), None)
    if not clip or clip.get("status") != "success":
        return jsonify({"error": "Clip not ready"}), 404

    try:
        uploader = YouTubeUploader(CONFIG)
        result = uploader.upload(
            video_path=clip["final_video"],
            title=clip["title"],
            thumbnail_path=clip.get("thumbnail"),
        )
        # Store upload result
        if "uploads" not in jobs[job_id]:
            jobs[job_id]["uploads"] = []
        jobs[job_id]["uploads"].append(result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config")
def get_config():
    """Return current configuration (sanitized)."""
    safe = {
        "whisper": CONFIG.get("whisper", {}),
        "scoring": CONFIG.get("scoring", {}),
        "video": CONFIG.get("video", {}),
        "subtitles": CONFIG.get("subtitles", {}),
        "youtube": {k: v for k, v in CONFIG.get("youtube", {}).items()
                    if k != "description_template"},
    }
    return jsonify(safe)


# ─── Pipeline ────────────────────────────────────────────────────────────────

def _run_pipeline(job_id: str, video_path: str, config: dict):
    """
    Full ClippedAI pipeline running in a background thread.
    Emits SSE events throughout.
    """
    job = jobs[job_id]

    def cb(event: str, message: str, data: dict = None):
        emit(job_id, event, message, data)

    try:
        cb("start", "🚀 ClippedAI pipeline started!")

        # ── Step 1: Video Info ───────────────────────────────────────────
        cb("info", "📊 Analyzing video...")
        processor = VideoProcessor(config)
        info = processor.get_video_info(video_path)
        cb("info_done", f"📽️ Video: {info.get('width')}×{info.get('height')}, "
                        f"{info.get('duration', 0)/60:.1f} min", {"info": info})

        # ── Step 2: Transcription ────────────────────────────────────────
        whisper_cfg = config.get("whisper", {})
        engine = TranscriptionEngine(
            model_size=whisper_cfg.get("model", "base"),
            device=whisper_cfg.get("device", "cpu"),
            language=whisper_cfg.get("language"),
        )

        # Check for cached transcript
        transcript_path = str(Path(video_path).with_suffix(".transcript.json"))
        if os.path.exists(transcript_path):
            cb("transcribing", "📝 Loading cached transcript...")
            transcript = engine.load_transcript(transcript_path)
            cb("transcription_done", f"📝 Transcript loaded from cache ({len(transcript['segments'])} segments)")
        else:
            transcript = engine.transcribe(video_path, progress_callback=cb)
            engine.save_transcript(transcript, transcript_path)

        jobs[job_id]["transcript"] = {
            "language": transcript["language"],
            "duration": transcript["duration"],
            "segments_count": len(transcript["segments"]),
        }

        # ── Step 3: Highlight Scoring ────────────────────────────────────
        scorer = HighlightScorer(config.get("scoring", {}))
        clips = scorer.score(transcript, video_path=video_path, progress_callback=cb)

        cb("scoring_done", f"🎯 Found {len(clips)} top highlights!",
           {"clips": [c.to_dict() for c in clips]})

        # ── Step 4: Video Processing ─────────────────────────────────────
        job_output_dir = OUTPUT_DIR / job_id
        job_output_dir.mkdir(exist_ok=True)

        processed_clips = []
        total = len(clips)
        for i, clip in enumerate(clips):
            cb("processing", f"✂️ Processing clip {i+1}/{total}...")
            result = processor.process_clip(
                video_path=video_path,
                clip=clip,
                output_dir=str(job_output_dir),
                transcript=transcript,
                clip_index=i,
                progress_callback=cb,
            )
            processed_clips.append(result)
            jobs[job_id]["clips"] = processed_clips

            pct = int(((i + 1) / total) * 100)
            cb("clip_done", f"✅ Clip {i+1}/{total} ready!", {
                "clip": result,
                "progress_pct": pct
            })

        jobs[job_id]["clips"] = processed_clips
        success_count = sum(1 for c in processed_clips if c.get("status") == "success")

        # ── Step 5: Auto Upload (optional) ───────────────────────────────
        upload_results = []
        if config.get("youtube", {}).get("auto_upload", False):
            cb("uploading", "📤 Starting YouTube uploads...")
            uploader = YouTubeUploader(config)
            try:
                upload_results = uploader.upload_batch(
                    processed_clips,
                    progress_callback=cb,
                    delay_between=15,
                )
                jobs[job_id]["uploads"] = upload_results
                cb("uploads_done",
                   f"🎉 Uploaded {len(upload_results)} Shorts to YouTube!",
                   {"uploads": upload_results})
            except Exception as e:
                cb("upload_warning", f"⚠️ Upload skipped: {str(e)}")

        # ── Done ─────────────────────────────────────────────────────────
        jobs[job_id]["status"] = "done"
        cb("done",
           f"🎉 All done! {success_count} Shorts ready in output/{job_id}/",
           {
               "clips": processed_clips,
               "uploads": upload_results,
               "total_clips": success_count,
           })

    except Exception as e:
        logger.exception(f"Pipeline error for job {job_id}: {e}")
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        emit(job_id, "fatal_error", f"❌ Fatal error: {str(e)}")


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  ClippedAI -- YouTube Shorts Generator")
    print("  Open: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
