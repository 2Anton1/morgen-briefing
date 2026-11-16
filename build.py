#!/usr/bin/env python3
"""Morgen-Briefing: Skript -> ElevenLabs-Audio -> MP3 -> Podcast-Feed.

Aufruf:
  ELEVENLABS_API_KEY=... python3 build.py --script folgen/2026-11-17.md --title "Dienstag, 17. November"
  python3 build.py --script ... --title ... --dry-run   # Stille statt TTS, zum Testen

Skriptformat: Absätze, getrennt durch Leerzeilen. Ein Absatz, der mit "B:" beginnt,
wird mit der zweiten Stimme gesprochen (z. B. die ChatGPT-Perspektive), alle anderen
mit der Hauptstimme. "A:" am Absatzanfang ist optional.
"""
import argparse, datetime as dt, email.utils, html, json, os, pathlib, subprocess, sys, tempfile
import urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
EPISODES_JSON = ROOT / "episodes.json"
AUDIO_DIR = ROOT / "audio"
MAX_CHARS = 4000  # pro TTS-Anfrage, bleibt unter den API-Grenzen


def parse_segments(text):
    segs = []
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        voice = "A"
        if para[:2] in ("A:", "B:"):
            voice, para = para[0], para[2:].strip()
        if segs and segs[-1][0] == voice and len(segs[-1][1]) + len(para) < MAX_CHARS:
            segs[-1] = (voice, segs[-1][1] + "\n\n" + para)
        else:
            while len(para) > MAX_CHARS:  # sehr lange Absätze an Satzgrenzen teilen
                cut = para.rfind(". ", 0, MAX_CHARS) + 1 or MAX_CHARS
                segs.append((voice, para[:cut].strip()))
                para = para[cut:].strip()
            segs.append((voice, para))
    return segs


def tts(text, voice_id, out_path, key):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    body = json.dumps({
        "text": text,
        "model_id": CFG.get("model_id", "eleven_multilingual_v2"),
        "language_code": "de",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.15, "speed": CFG.get("speed", 1.05)},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out_path.write_bytes(r.read())
                return
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                continue
            sys.exit(f"TTS-Fehler {e.code}: {msg}")


def silence(seconds, out_path):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", str(seconds), "-b:a", "128k", str(out_path)], check=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def render_audio(segments, out_mp3, dry_run):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not dry_run and not key:
        sys.exit("ELEVENLABS_API_KEY fehlt")
    voices = {"A": CFG["voice_a"], "B": CFG.get("voice_b") or CFG["voice_a"]}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        gap = tmp / "gap.mp3"
        silence(0.6, gap)
        parts = []
        for i, (v, txt) in enumerate(segments):
            p = tmp / f"{i:03d}.mp3"
            if dry_run:
                silence(max(1, len(txt) / 15 / 10), p)  # grob 15 Zeichen/s, verkürzt
            else:
                tts(txt, voices[v], p, key)
            parts += [p, gap]
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-ac", "1", "-ar", "44100", "-b:a", "96k", str(out_mp3)], check=True)


def write_feed(episodes):
    base = CFG["base_url"].rstrip("/")
    items = []
    for ep in sorted(episodes, key=lambda e: e["date"], reverse=True):
        d = dt.datetime.fromisoformat(ep["date"] + "T06:00:00+01:00")
        secs = int(ep["duration"])
        items.append(f"""    <item>
      <title>{html.escape(ep['title'])}</title>
      <description>{html.escape(ep.get('summary', ''))}</description>
      <guid isPermaLink="false">morgen-briefing-{ep['date']}</guid>
      <pubDate>{email.utils.format_datetime(d)}</pubDate>
      <enclosure url="{base}/audio/{ep['file']}" length="{ep['bytes']}" type="audio/mpeg"/>
      <itunes:duration>{secs // 60}:{secs % 60:02d}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>""")
    now = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{html.escape(CFG['title'])}</title>
    <link>{base}/</link>
    <language>de-de</language>
    <description>{html.escape(CFG['description'])}</description>
    <itunes:author>{html.escape(CFG['author'])}</itunes:author>
    <itunes:image href="{base}/cover.png"/>
    <itunes:block>Yes</itunes:block>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="News"/>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""
    (ROOT / "feed.xml").write_text(feed, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = pathlib.Path(a.script).read_text(encoding="utf-8")
    segments = parse_segments(text)
    AUDIO_DIR.mkdir(exist_ok=True)
    fname = f"{a.date}.mp3"
    out = AUDIO_DIR / fname
    render_audio(segments, out, a.dry_run)

    episodes = json.loads(EPISODES_JSON.read_text()) if EPISODES_JSON.exists() else []
    episodes = [e for e in episodes if e["date"] != a.date]
    episodes.append({"date": a.date, "title": a.title, "summary": a.summary, "file": fname,
                     "bytes": out.stat().st_size, "duration": duration(out)})
    episodes.sort(key=lambda e: e["date"])
    keep = CFG.get("keep_episodes", 14)
    for old in episodes[:-keep]:  # Repo klein halten
        (AUDIO_DIR / old["file"]).unlink(missing_ok=True)
    episodes = episodes[-keep:]
    EPISODES_JSON.write_text(json.dumps(episodes, ensure_ascii=False, indent=1))
    write_feed(episodes)
    ep = episodes[-1]
    print(json.dumps({"file": f"audio/{fname}", "minutes": round(ep["duration"] / 60, 1),
                      "chars": len(text), "segments": len(segments)}))


if __name__ == "__main__":
    main()
