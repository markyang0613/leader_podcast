import feedparser
import google.generativeai as genai
from elevenlabs.client import ElevenLabs
from elevenlabs import save
import os
from dotenv import load_dotenv
from utils import upload_to_s3

# 1. SETUP KEYS (Create a .env file with these)
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
el_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

genai.configure(api_key=api_key)

url = "https://bullrich.dev/tldr-rss/tech.rss" 
feed = feedparser.parse(url)
print(f"Success! Found {len(feed.entries)} entries.")
if len(feed.entries) > 0:
    for i, entry in enumerate(feed.entries[:3]):
        print(f"{i+1}. Headline: {entry.title}")

# 2. EXTRACT: Get news from TLDR
def get_tldr_news():
    # Using the unbundled RSS utility you found!
    
    # Get top 3 articles to keep the podcast brief
    articles = [{"title": e.title, "summary": e.summary} for e in feed.entries[:3]]
    return articles

# 3. TRANSFORM: Generate Dialogue Script
def generate_podcast_script(articles, language="English"):
    model = genai.GenerativeModel('gemini-3-flash')
    
    news_context = "\n".join([f"- {a['title']}: {a['summary']}" for a in articles])
    
    prompt = f"""
    You are a scriptwriter for 'LEADER' (Lazy Reader). 
    Convert this news into a 2-minute back-and-forth conversation...
    """
    
    # Move these lines HERE (indented)
    print("DEBUG: Requesting script from Gemini...")
    response = model.generate_content(prompt, request_options={"timeout": 60})
    
    return response.text



# 4. LOAD: Generate Audio (ElevenLabs)
def create_podcast_audio(script):
    print("Synthesizing voice...")
    audio = el_client.text_to_speech.convert(
        text=script,
        # Updated to the current 2026 ID for Alice
        voice_id="Xb7hH8MSUJpSbSDYk0k2", 
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128"
    )
    
    save(audio, "daily_brief.mp3")
    print("Success! daily_brief.mp3 is ready.")



if __name__ == "__main__":
    print("1. Fetching news...")
    news = get_tldr_news()
    
    print("2. Creating script (Gemini)...")
    script = generate_podcast_script(news, language="English") 
    print("DEBUG: Gemini Script received.") # <--- NEW
    
    print("3. Synthesizing voice (ElevenLabs)...")
    create_podcast_audio(script)
    print("DEBUG: Audio file saved.") # <--- NEW
    
    print("4. Uploading to AWS S3...")
    public_url = upload_to_s3("daily_brief.mp3", "leader-podcast-audio-storage")
    print(f"5. Podcast is live at: {public_url}")