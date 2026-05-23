import feedparser
from groq import Groq
import edge_tts
import asyncio
import os
import tempfile
from datetime import datetime
from dotenv import load_dotenv
from utils import upload_to_r2, update_rss_feed

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

JUNO_VOICE = os.getenv("JUNO_VOICE", "en-US-JennyNeural")   # curious student
ALEX_VOICE = os.getenv("ALEX_VOICE", "en-US-GuyNeural")     # tech expert


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

    print("DEBUG: Requesting script from Groq...")
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    return response.choices[0].message.content


# 3. LOAD: Synthesize audio with two distinct edge-tts voices
async def _synthesize_script(script):
    lines = [l.strip() for l in script.strip().split("\n") if l.strip()]
    all_audio = b""
    tmp = tempfile.mkdtemp()

    for i, line in enumerate(lines):
        if line.upper().startswith("JUNO:"):
            voice, text = JUNO_VOICE, line[5:].strip()
        elif line.upper().startswith("ALEX:"):
            voice, text = ALEX_VOICE, line[5:].strip()
        else:
            continue
        if not text:
            continue

        tmp_path = os.path.join(tmp, f"{i}.mp3")
        await edge_tts.Communicate(text, voice).save(tmp_path)

        with open(tmp_path, "rb") as f:
            all_audio += f.read()
        os.remove(tmp_path)

    os.rmdir(tmp)
    return all_audio


def create_podcast_audio(script):
    print("Synthesizing voice...")
    audio = asyncio.run(_synthesize_script(script))
    with open("daily_brief.mp3", "wb") as f:
        f.write(audio)
    print("Success! daily_brief.mp3 is ready.")


if __name__ == "__main__":
    print("1. Fetching news...")
    news = get_tldr_news()

    print("2. Creating script (Groq / Llama 3.3 70B)...")
    script = generate_podcast_script(news, language="English")
    print("DEBUG: Script received.")

    print("3. Synthesizing voice (edge-tts)...")
    create_podcast_audio(script)
    print("DEBUG: Audio file saved.")

    print("4. Uploading to Cloudflare R2...")
    bucket = os.getenv("R2_BUCKET_NAME", "leader-podcast")
    file_size = os.path.getsize("daily_brief.mp3")
    public_url = upload_to_r2("daily_brief.mp3", bucket)

    date_str = datetime.now().strftime("%B %d, %Y")
    ep_title = f"LEADER Daily Brief - {date_str}"
    ep_description = " | ".join(a["title"] for a in news)

    print("5. Updating RSS feed...")
    feed_url = update_rss_feed(bucket, public_url, ep_title, ep_description, file_size)

    print(f"6. Podcast is live at:  {public_url}")
    print(f"   RSS feed:             {feed_url}")
