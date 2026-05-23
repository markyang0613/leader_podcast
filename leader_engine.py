import feedparser
from groq import Groq
import edge_tts
import asyncio
import os
import tempfile
import time
from datetime import datetime
from dotenv import load_dotenv
from utils import upload_to_r2, update_rss_feed

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Supported languages: code → { display name, JUNO voice, ALEX voice }
LANGUAGES = {
    "en": {"name": "English",  "juno": "en-US-JennyNeural",    "alex": "en-US-GuyNeural"},
    "es": {"name": "Spanish",  "juno": "es-ES-ElviraNeural",   "alex": "es-ES-AlvaroNeural"},
    "ja": {"name": "Japanese", "juno": "ja-JP-NanamiNeural",   "alex": "ja-JP-KeitaNeural"},
    "zh": {"name": "Chinese",  "juno": "zh-CN-XiaoxiaoNeural", "alex": "zh-CN-YunxiNeural"},
    "fr": {"name": "French",   "juno": "fr-FR-DeniseNeural",   "alex": "fr-FR-HenriNeural"},
    "ko": {"name": "Korean",   "juno": "ko-KR-HyunsuMultilingualNeural", "alex": "ko-KR-InJoonNeural", "gtts_lang": "ko"},
}


# 1. EXTRACT: Get news from TLDR
def get_tldr_news():
    url = "https://bullrich.dev/tldr-rss/tech.rss"
    feed = feedparser.parse(url)
    print(f"Fetched {len(feed.entries)} entries from TLDR.")
    return [{"title": e.title, "summary": e.summary} for e in feed.entries[:3]]


# 2. TRANSFORM: Generate dialogue script via Groq (Llama 3.3 70B)
def generate_podcast_script(articles, language="English"):
    news_context = "\n".join([f"- {a['title']}: {a['summary']}" for a in articles])

    prompt = f"""You are a scriptwriter for 'LEADER' (Lazy Reader), a daily tech podcast.
Write a 2-minute back-and-forth dialogue in {language} between:
- JUNO: a curious student, asks questions, reacts with enthusiasm
- ALEX: a knowledgeable tech expert, explains clearly and concisely

Cover these 3 news stories naturally in conversation:
{news_context}

Format every line exactly as:
JUNO: <line>
ALEX: <line>

No stage directions, no intro music cues, no other characters. Start immediately with JUNO's opening line."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    return response.choices[0].message.content


# 3. LOAD: Synthesize audio and return raw bytes
async def _synthesize_script(script, juno_voice, alex_voice):
    lines = [l.strip() for l in script.strip().split("\n") if l.strip()]
    all_audio = b""
    tmp = tempfile.mkdtemp()

    for i, line in enumerate(lines):
        if line.upper().startswith("JUNO:"):
            voice, text = juno_voice, line[5:].strip()
        elif line.upper().startswith("ALEX:"):
            voice, text = alex_voice, line[5:].strip()
        else:
            continue
        if not text:
            continue

        tmp_path = os.path.join(tmp, f"{i}.mp3")
        for attempt in range(3):
            try:
                await edge_tts.Communicate(text, voice).save(tmp_path)
                break
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

        with open(tmp_path, "rb") as f:
            all_audio += f.read()
        os.remove(tmp_path)

    os.rmdir(tmp)
    return all_audio


def create_podcast_audio(script, juno_voice, alex_voice):
    return asyncio.run(_synthesize_script(script, juno_voice, alex_voice))


# gTTS fallback: used when edge-tts is blocked (e.g. Korean voices on GitHub Actions IPs).
# Both JUNO and ALEX lines get a single Google TTS voice — no voice distinction,
# but the Korean audio is still fully usable.
async def _synthesize_script_gtts(script, lang_code):
    from gtts import gTTS

    lines = [l.strip() for l in script.strip().split("\n") if l.strip()]
    all_audio = b""

    for line in lines:
        if line.upper().startswith("JUNO:"):
            text = line[5:].strip()
        elif line.upper().startswith("ALEX:"):
            text = line[5:].strip()
        else:
            continue
        if not text:
            continue

        tmp_path = tempfile.mktemp(suffix=".mp3")
        try:
            tts_obj = gTTS(text, lang=lang_code)
            await asyncio.to_thread(tts_obj.save, tmp_path)
            with open(tmp_path, "rb") as f:
                all_audio += f.read()
        except (ValueError, AssertionError) as e:
            print(f"   DEBUG gTTS skip ({text[:40]!r}): {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return all_audio


def create_podcast_audio_gtts(script, lang_code):
    return asyncio.run(_synthesize_script_gtts(script, lang_code))


if __name__ == "__main__":
    print("1. Fetching news...")
    news = get_tldr_news()

    bucket = os.getenv("R2_BUCKET_NAME", "leader-podcast")
    date_str = datetime.now().strftime("%Y-%m-%d")
    ep_title = f"LEADER Daily Brief - {datetime.now().strftime('%B %d, %Y')}"
    ep_description = " | ".join(a["title"] for a in news)

    versions = {}
    en_file_size = 0

    for code, cfg in LANGUAGES.items():
        try:
            print(f"2. Generating {cfg['name']} script...")
            script = generate_podcast_script(news, language=cfg["name"])

            print(f"3. Synthesizing {cfg['name']} audio...")
            try:
                audio = create_podcast_audio(script, cfg["juno"], cfg["alex"])
            except Exception as tts_err:
                if "gtts_lang" not in cfg:
                    raise
                print(f"   edge-tts failed ({tts_err}), using gTTS fallback...")
                print(f"   DEBUG script[:200]: {script[:200]!r}")
                print(f"   DEBUG hex: {script[:100].encode('unicode_escape').decode()}")
                audio = create_podcast_audio_gtts(script, cfg["gtts_lang"])

            filename = f"daily_brief_{code}.mp3"
            with open(filename, "wb") as f:
                f.write(audio)

            s3_path = f"podcasts/{date_str}_tech_{code}.mp3"
            print(f"4. Uploading {cfg['name']} to R2...")
            public_url = upload_to_r2(filename, bucket, s3_path)
            versions[code] = public_url

            if code == "en":
                en_file_size = os.path.getsize(filename)

            os.remove(filename)
        except Exception as e:
            print(f"   WARNING: {cfg['name']} failed ({e}), skipping.")

        time.sleep(5)

    if "en" not in versions:
        raise RuntimeError("English episode failed — cannot update feed without a primary URL.")

    print("5. Updating RSS feed...")
    feed_url = update_rss_feed(
        bucket, versions["en"], ep_title, ep_description, en_file_size, versions
    )

    print(f"6. Done! English episode: {versions['en']}")
    print(f"   RSS feed:              {feed_url}")
    print(f"   Languages: {', '.join(versions.keys())}")
