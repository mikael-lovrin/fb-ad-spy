# -*- coding: utf-8 -*-
"""
Video ad analysis pipeline:
  1. Download the video file
  2. Extract audio via ffmpeg
  3. Transcribe with Whisper (local faster-whisper or OpenAI API)
  4. Analyze the transcript with Claude (VSL structure, hooks, CTAs)

Configuration via .env:
  USE_LOCAL_WHISPER=true   → faster-whisper (free, runs locally)
  USE_LOCAL_WHISPER=false  → OpenAI Whisper API (paid per minute)
"""

import logging
import subprocess
from pathlib import Path

import anthropic
import requests

from core.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, OPENAI_API_KEY,
    USE_LOCAL_WHISPER, WHISPER_MODEL_SIZE, TEMP_DIR,
)

logger = logging.getLogger(__name__)
_anthropic_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def _download_video(url: str, output_path: Path) -> None:
    """Stream-download a video to avoid memory issues with large files."""
    resp = requests.get(url, stream=True, timeout=60, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    """Extract audio track from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn", "-acodec", "libmp3lame", "-q:a", "4",
        "-y", str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")


def _transcribe_local(audio_path: Path) -> str:
    """Transcribe with faster-whisper (free, CPU-based)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "faster-whisper not installed. Run: pip install faster-whisper\n"
            "Or set USE_LOCAL_WHISPER=false in .env to use the OpenAI API instead."
        )

    logger.info(f"Loading Whisper model ({WHISPER_MODEL_SIZE}) locally...")
    model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), beam_size=5)
    return " ".join(seg.text for seg in segments).strip()


def _transcribe_openai(audio_path: Path) -> str:
    """Transcribe via OpenAI Whisper API (billed per audio minute)."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f)
    return result.text


def transcribe_audio(audio_path: Path) -> str:
    """Route to local Whisper or OpenAI API based on USE_LOCAL_WHISPER config."""
    if USE_LOCAL_WHISPER:
        return _transcribe_local(audio_path)
    return _transcribe_openai(audio_path)


def analyze_video_transcript(transcript: str) -> str:
    """
    Analyze a VSL transcript with Claude.
    Identifies DR script structure, hooks, mechanism, and CTA.
    """
    if not transcript.strip():
        return ""

    prompt = f"""You are a direct response marketing expert.
Analyze this video ad transcript and describe in paragraphs (no bullet lists):

1. Script structure: identify the sequence (e.g., problem → agitation → solution → guarantee → CTA)
2. Opening hook: what phrase or element opens the video to grab attention
3. Unique mechanism: the "trick", discovery, or mechanism the product uses as a differentiator
4. Main promises and benefits
5. Lead pain points addressed
6. Social proof, authority, or credibility elements used
7. CTA: where the video sends the viewer and what action it calls for
8. Assessment: does this script show patterns of a scaled VSL campaign?

Transcript:
{transcript}"""

    response = _get_anthropic().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def analyze_video_ad(video_source: str, ad_text: str = "") -> tuple[str, str]:
    """
    Full pipeline for a video ad.

    Args:
        video_source: Remote URL or local file path to the video.
        ad_text:      Optional ad copy text for additional context.

    Returns:
        (transcript, analysis) — both as plain strings.
    """
    if not video_source:
        return "", ""

    video_hash = abs(hash(video_source))
    video_path = TEMP_DIR / f"video_{video_hash}.mp4"
    audio_path = TEMP_DIR / f"audio_{video_hash}.mp3"

    try:
        # If it's already a local file, skip download
        if video_source.startswith("data/"):
            video_path = Path(video_source)
        else:
            logger.info(f"Downloading video: {video_source[:60]}...")
            _download_video(video_source, video_path)

        logger.info("Extracting audio...")
        _extract_audio(video_path, audio_path)

        logger.info("Transcribing audio...")
        transcript = transcribe_audio(audio_path)
        logger.info(f"Transcript length: {len(transcript)} chars")

        logger.info("Analyzing transcript with Claude...")
        analysis = analyze_video_transcript(transcript)

        return transcript, analysis

    except Exception as e:
        logger.error(f"Video analysis error: {e}")
        return "", f"Error: {e}"

    finally:
        # Clean up temp files (keep local downloaded files if in data/media/)
        for path in [audio_path]:
            if path.exists() and str(path).startswith(str(TEMP_DIR)):
                path.unlink()
        if not video_source.startswith("data/") and video_path.exists():
            video_path.unlink()
