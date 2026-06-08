"""
╔══════════════════════════════════════════════╗
║   ClippedAI — YouTube Auto-Uploader          ║
╚══════════════════════════════════════════════╝

Uploads processed Shorts to YouTube via Data API v3.
Uses OAuth 2.0 — you authenticate once in a browser,
token is saved locally and reused automatically.

Setup:
  1. Go to: https://console.cloud.google.com/
  2. Create a project → Enable YouTube Data API v3
  3. Create OAuth 2.0 credentials (Desktop app type)
  4. Download as credentials.json → put in client_secrets/
"""

import os
import json
import logging
import time
import mimetypes
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# YouTube API scopes needed
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

# Category IDs (YouTube)
CATEGORIES = {
    "Entertainment": "24",
    "People & Blogs": "22",
    "Sports": "17",
    "Gaming": "20",
    "Education": "27",
    "Film & Animation": "1",
    "Music": "10",
    "News & Politics": "25",
    "Howto & Style": "26",
}


class YouTubeUploader:
    """Manages YouTube OAuth and video uploads."""

    def __init__(self, config: dict):
        yt = config.get("youtube", {})
        paths = config.get("paths", {})

        self.auto_upload = yt.get("auto_upload", False)
        self.privacy = yt.get("privacy", "public")
        self.category_id = str(yt.get("category_id", "22"))
        self.default_tags = yt.get("default_tags", ["Comedy", "TVShow", "Funny"])
        self.title_suffix = yt.get("title_suffix", "") # Removed #Shorts from title to save space for hooks
        self.description_template = yt.get(
            "description_template",
            "What do you think about this? Let us know in the comments! 👇\n\nDon't forget to subscribe for more hilarious moments!\n\n#Shorts #Comedy #TVShows"
        )

        self.credentials_file = paths.get("credentials_file", "client_secrets/credentials.json")
        self.token_file = paths.get("token_file", "client_secrets/token.json")

        self._youtube = None

    @property
    def is_authenticated(self) -> bool:
        return os.path.exists(self.token_file)

    def authenticate(self, progress_callback: Optional[Callable] = None) -> bool:
        """
        Run OAuth flow. Opens browser on first run.
        Token saved to disk for future use.
        """
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None

            # Load saved token
            if os.path.exists(self.token_file):
                creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)

            # Refresh or re-authenticate
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not os.path.exists(self.credentials_file):
                        raise FileNotFoundError(
                            f"YouTube credentials not found: {self.credentials_file}\n"
                            "Please download your OAuth credentials from Google Cloud Console "
                            "and save as client_secrets/credentials.json"
                        )
                    if progress_callback:
                        progress_callback("auth", "Opening browser for YouTube authentication...")

                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # Save token
                os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
                with open(self.token_file, "w") as f:
                    f.write(creds.to_json())
                logger.info(f"Token saved to: {self.token_file}")

            self._youtube = build("youtube", "v3", credentials=creds)
            logger.info("YouTube API authenticated successfully")

            if progress_callback:
                progress_callback("auth_done", "YouTube authentication successful!")

            return True

        except ImportError:
            raise ImportError(
                "YouTube upload libraries not installed.\n"
                "Run: pip install google-api-python-client google-auth-oauthlib"
            )
        except Exception as e:
            logger.error(f"YouTube authentication failed: {e}")
            raise

    def upload(
        self,
        video_path: str,
        title: str,
        description: Optional[str] = None,
        tags: Optional[list] = None,
        thumbnail_path: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """
        Upload a video to YouTube and return the video URL.

        Args:
            video_path: Path to the .mp4 file to upload
            title: Video title (will have #Shorts appended if not present)
            description: Video description
            tags: List of hashtags/tags
            thumbnail_path: Optional custom thumbnail image
            progress_callback: Function(event, message) for status updates

        Returns:
            dict with video_id, url, title, status
        """
        if self._youtube is None:
            self.authenticate(progress_callback)

        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        # Ensure title fits within YouTube's limit (100 chars max)
        if self.title_suffix and self.title_suffix not in title:
            title = (title + self.title_suffix)[:100]
        else:
            title = title[:100]

        if description is None:
            description = self.description_template

        # Use exactly 3-5 tags in the metadata (avoid keyword stuffing)
        all_tags = list(set((tags or []) + self.default_tags))[:5]

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": all_tags,
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": self.privacy,
                "selfDeclaredMadeForKids": False,
            }
        }

        # Detect mime type
        mime_type = mimetypes.guess_type(video_path)[0] or "video/mp4"

        media = MediaFileUpload(
            video_path,
            mimetype=mime_type,
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
        )

        if progress_callback:
            progress_callback("uploading", f"Uploading: {title}")

        request = self._youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        retry = 0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if progress_callback:
                        progress_callback("upload_progress", f"Upload {pct}%")
            except Exception as e:
                if retry < 5:
                    wait = 2 ** retry
                    logger.warning(f"Upload chunk failed (retry {retry}), waiting {wait}s: {e}")
                    time.sleep(wait)
                    retry += 1
                else:
                    raise

        video_id = response["id"]
        url = f"https://www.youtube.com/shorts/{video_id}"

        # Set custom thumbnail if provided
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                self._youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path)
                ).execute()
                logger.info(f"Thumbnail set for video {video_id}")
            except Exception as e:
                logger.warning(f"Failed to set thumbnail: {e}")

        result = {
            "video_id": video_id,
            "url": url,
            "title": title,
            "privacy": self.privacy,
            "status": "uploaded",
        }

        if progress_callback:
            progress_callback("upload_done", f"Uploaded! {url}")

        logger.info(f"Upload complete: {url}")
        return result

    def upload_batch(
        self,
        clips: list,
        progress_callback: Optional[Callable] = None,
        delay_between: int = 10,
    ) -> list:
        """
        Upload multiple Shorts with a delay between each to avoid quota limits.

        Args:
            clips: List of dicts from VideoProcessor.process_clip()
            delay_between: Seconds to wait between uploads (default 10s)
        """
        results = []
        successful = [c for c in clips if c.get("status") == "success"]

        for i, clip in enumerate(successful):
            logger.info(f"Uploading Short {i + 1}/{len(successful)}: {clip['title']}")
            try:
                result = self.upload(
                    video_path=clip["final_video"],
                    title=clip["title"],
                    thumbnail_path=clip.get("thumbnail"),
                    progress_callback=progress_callback,
                )
                result["clip_index"] = clip["clip_index"]
                results.append(result)

                if i < len(successful) - 1:
                    # No delay — upload immediately
                    pass

            except Exception as e:
                logger.error(f"Upload failed for clip {i + 1}: {e}")
                results.append({
                    "clip_index": clip["clip_index"],
                    "status": "upload_failed",
                    "error": str(e),
                })

        return results

    def revoke_token(self):
        """Revoke YouTube OAuth token (logout)."""
        if os.path.exists(self.token_file):
            os.remove(self.token_file)
            self._youtube = None
            logger.info("YouTube token revoked")
