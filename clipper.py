"""Clipping pipeline: video -> transcript -> highlight segments -> vertical captioned clips."""
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
MIN_CLIP = float(os.getenv("MIN_CLIP_SECONDS", "20"))
MAX_CLIP = float(os.getenv("MAX_CLIP_SECONDS", "59"))
MAX_CLIPS = int(os.getenv("MAX_CLIPS", "5"))

_model = None


def _whisper():
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, device="auto", compute_type="int8")
    return _model


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def transcribe(video: Path) -> tuple[list[Segment], list[Word]]:
    """Return sentence-level segments and word-level timestamps."""
    segs, _info = _whisper().transcribe(str(video), word_timestamps=True, vad_filter=True)
    segments, words = [], []
    for s in segs:
        segments.append(Segment(s.start, s.end, s.text.strip()))
        for w in (s.words or []):
            words.append(Word(w.start, w.end, w.word.strip()))
    return segments, words


# ---------- highlight selection ----------

def _llm_pick(segments: list[Segment], duration: float) -> list[dict] | None:
    """Ask Claude to choose self-contained, hook-driven clips. Returns None if unavailable."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    transcript = "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in segments)
    prompt = f"""You are an editor choosing clips for TikTok/Reels/YouTube Shorts from a video transcript.

Pick up to {MAX_CLIPS} clips. Rules:
- Each clip is {MIN_CLIP:.0f}-{MAX_CLIP:.0f} seconds long.
- Each must start on a strong hook (a bold claim, question, surprise, or story start) and end on a natural finish.
- Each must make sense without the rest of the video.
- Use start/end times that fall on segment boundaries shown below. Clips must not overlap.
- Rank by viral potential.

Return ONLY a JSON array: [{{"start": float, "end": float, "title": str, "reason": str}}]

Transcript (video length {duration:.0f}s):
{transcript}"""
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    return json.loads(m.group(0))


_HOOK = re.compile(r"\b(secret|never|always|mistake|why|how|truth|biggest|best|worst|"
                   r"actually|nobody|everyone|stop|learn|wrong|crazy|insane|\?)\b", re.I)


def _heuristic_pick(segments: list[Segment], duration: float) -> list[dict]:
    """Fallback: slide a window over segments and score by hook words and speech density."""
    candidates = []
    for i, first in enumerate(segments):
        end_idx = i
        while end_idx + 1 < len(segments) and segments[end_idx + 1].end - first.start <= MAX_CLIP:
            end_idx += 1
        last = segments[end_idx]
        length = last.end - first.start
        if length < MIN_CLIP:
            continue
        text = " ".join(s.text for s in segments[i:end_idx + 1])
        score = len(_HOOK.findall(text)) + 2 * len(_HOOK.findall(first.text)) + len(text.split()) / length
        candidates.append({"start": first.start, "end": last.end, "score": score,
                           "title": first.text[:60], "reason": "keyword/density score"})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    chosen = []
    for c in candidates:
        if all(c["end"] <= x["start"] or c["start"] >= x["end"] for x in chosen):
            chosen.append(c)
        if len(chosen) == MAX_CLIPS:
            break
    return sorted(chosen, key=lambda c: c["start"])


def pick_clips(segments: list[Segment], duration: float) -> list[dict]:
    picks = None
    try:
        picks = _llm_pick(segments, duration)
    except Exception:
        picks = None
    if not picks:
        picks = _heuristic_pick(segments, duration)
    if not picks:  # very short or silent video: take the whole thing
        picks = [{"start": 0, "end": min(duration, MAX_CLIP), "title": "Clip", "reason": "fallback"}]
    cleaned = []
    for p in picks[:MAX_CLIPS]:
        s = max(0.0, float(p["start"]))
        e = min(duration, float(p["end"]))
        if e - s >= 5:
            cleaned.append({**p, "start": s, "end": e})
    return cleaned


# ---------- captions ----------

def _ass_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(words: list[Word], start: float, end: float, path: Path) -> None:
    """Karaoke-style captions: ~3 words at a time, big, bottom-center-ish."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,84,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,2,2,60,60,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    in_clip = [w for w in words if w.start >= start and w.end <= end]
    lines = []
    for i in range(0, len(in_clip), 3):
        group = in_clip[i:i + 3]
        t0 = group[0].start - start
        t1 = group[-1].end - start
        text = " ".join(w.text for w in group).upper().replace("\\", "").replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},Default,,0,0,0,,{text}")
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


# ---------- rendering ----------

def render_clip(video: Path, words: list[Word], start: float, end: float, out: Path,
                captions: bool = True) -> None:
    """Cut, crop to 9:16 (center crop), scale to 1080x1920, burn captions."""
    vf = "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1"
    ass = out.with_suffix(".ass")
    if captions and words:
        build_ass(words, start, end, ass)
        # escape for ffmpeg filter syntax
        ass_path = str(ass).replace("\\", "/").replace(":", "\\:")
        vf += f",subtitles='{ass_path}'"
    run([
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(video), "-t", f"{end - start:.2f}",
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out),
    ])
    if ass.exists():
        ass.unlink()


def make_clips(video: Path, workdir: Path, captions: bool = True, progress=None) -> list[dict]:
    """Full pipeline. `progress` is an optional callable(str) for status updates."""
    say = progress or (lambda _m: None)
    workdir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video)
    say("Transcribing audio...")
    segments, words = transcribe(video)
    say("Finding the best moments...")
    picks = pick_clips(segments, duration)
    results = []
    for i, p in enumerate(picks, 1):
        say(f"Rendering clip {i}/{len(picks)}...")
        out = workdir / f"clip_{i}.mp4"
        render_clip(video, words, p["start"], p["end"], out, captions)
        results.append({**p, "path": out})
    return results
