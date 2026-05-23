import boto3
import os
import json
from datetime import datetime
from email.utils import formatdate


def _get_s3_client():
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def upload_to_r2(file_name, bucket_name, s3_path=None):
    s3 = _get_s3_client()
    if s3_path is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        s3_path = f"podcasts/{date_str}_tech.mp3"
    s3.upload_file(file_name, bucket_name, s3_path)
    public_base = os.getenv("R2_PUBLIC_URL_BASE", "").rstrip("/")
    return f"{public_base}/{s3_path}"


def update_rss_feed(bucket_name, episode_url, title, description, file_size, versions=None):
    s3 = _get_s3_client()
    public_base = os.getenv("R2_PUBLIC_URL_BASE", "").rstrip("/")

    try:
        obj = s3.get_object(Bucket=bucket_name, Key="episodes.json")
        episodes = json.loads(obj["Body"].read())
    except Exception:
        episodes = []

    entry = {
        "title": title,
        "description": description,
        "url": episode_url,
        "pub_date": formatdate(),
        "file_size": file_size,
    }
    if versions:
        entry["versions"] = versions
    episodes.insert(0, entry)

    feed_xml = _build_rss(episodes, public_base)

    s3.put_object(
        Bucket=bucket_name,
        Key="episodes.json",
        Body=json.dumps(episodes),
        ContentType="application/json",
    )
    s3.put_object(
        Bucket=bucket_name,
        Key="feed.xml",
        Body=feed_xml.encode("utf-8"),
        ContentType="application/rss+xml",
    )

    return f"{public_base}/feed.xml"


def _build_rss(episodes, public_base):
    items = ""
    for ep in episodes:
        items += f"""
    <item>
      <title>{ep['title']}</title>
      <description><![CDATA[{ep['description']}]]></description>
      <pubDate>{ep['pub_date']}</pubDate>
      <guid isPermaLink="true">{ep['url']}</guid>
      <enclosure url="{ep['url']}" length="{ep['file_size']}" type="audio/mpeg"/>
      <itunes:duration>120</itunes:duration>
    </item>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>LEADER - Lazy Reader Daily Tech Brief</title>
    <description>Your daily AI-generated tech news podcast. Catch up on what matters in tech in under 3 minutes.</description>
    <link>{public_base}</link>
    <language>en-us</language>
    <itunes:author>LEADER Podcast</itunes:author>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="Technology"/>
    <itunes:image href="{public_base}/cover.png"/>
{items}
  </channel>
</rss>"""
