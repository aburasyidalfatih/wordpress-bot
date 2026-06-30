#!/usr/bin/env python3
"""Post the latest successful article for a site to Threads."""

import argparse
import html
import os
import re
import sys

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database, PostLog, WordPressSite
from config import Config

load_dotenv()


def clean_text(text):
    text = html.unescape(re.sub(r"<[^<]+?>", "", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def extract_caption(post_url, title):
    try:
        response = requests.get(post_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()

        article_content = soup.find("article") or soup.find("div", class_="entry-content")
        if article_content:
            for paragraph in article_content.find_all("p"):
                text = clean_text(paragraph.get_text(separator=" ", strip=True))
                if len(text) > 50:
                    sentences = re.split(r"(?<=[.!?])\s+", text)
                    return " ".join(sentences[:3])[:430].strip()
    except Exception as exc:
        print(f"[WARN] Could not fetch article content: {exc}")

    return title[:430]


def resolve_site(session, user_id=None, site_id=None):
    query = session.query(WordPressSite).filter_by(is_active=True)
    if site_id:
        query = query.filter_by(id=site_id)
    if user_id:
        query = query.filter_by(user_id=user_id)
    return query.order_by(WordPressSite.created_at.asc()).first()


def resolve_log(session, user_id, site_id, log_id=None):
    query = session.query(PostLog).filter_by(user_id=user_id, site_id=site_id, success=True)
    if log_id:
        query = query.filter_by(id=log_id)
    return query.order_by(PostLog.created_at.desc()).first()


def post_to_threads(user_id=None, site_id=None, log_id=None):
    db = Database(Config.DATABASE_URL)

    with db.get_session() as session:
        site = resolve_site(session, user_id=user_id, site_id=site_id)
        if not site:
            print("[ERROR] No active site found.")
            return 1

        if not site.threads_enabled or not site.threads_user_id or not site.threads_access_token:
            print("[ERROR] Threads integration is not enabled or configured for this site.")
            return 1

        log = resolve_log(session, site.user_id, site.id, log_id=log_id)
        if not log or not log.post_url:
            print("[ERROR] No successful post with URL found for this site.")
            return 1

        threads_user_id = site.threads_user_id
        access_token = site.threads_access_token
        language = site.language or "id"
        title = log.title
        post_url = log.post_url

    read_more = "Read more:" if language == "en" else "Baca selengkapnya:"
    caption = extract_caption(post_url, title)
    text = f"{caption}\n\n{read_more}\n{post_url}"
    if len(text) > 500:
        text = f"{caption[:430]}...\n\n{post_url}"

    print("=" * 60)
    print("POSTING TO THREADS")
    print("=" * 60)
    print(f"Title: {title}")
    print(f"URL: {post_url}")
    print(f"Caption length: {len(text)}")

    response = requests.post(
        f"https://graph.threads.net/v1.0/{threads_user_id}/threads",
        params={
            "media_type": "TEXT",
            "text": text,
            "access_token": access_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    creation_id = response.json().get("id")
    if not creation_id:
        print(f"[ERROR] Threads create response did not include creation id: {response.text}")
        return 1

    response = requests.post(
        f"https://graph.threads.net/v1.0/{threads_user_id}/threads_publish",
        params={
            "creation_id": creation_id,
            "access_token": access_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    published_id = response.json().get("id")
    print(f"[OK] Published to Threads: {published_id}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Post the latest successful AutoWP article to Threads.")
    parser.add_argument("--user-id", type=int, help="Owner user ID")
    parser.add_argument("--site-id", type=int, help="WordPress site ID")
    parser.add_argument("--log-id", type=int, help="Specific post log ID")
    args = parser.parse_args()
    raise SystemExit(post_to_threads(user_id=args.user_id, site_id=args.site_id, log_id=args.log_id))
