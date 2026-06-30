#!/usr/bin/env python3
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from database import Database, WordPressSite
from config import Config
from trending_research import TrendingResearch

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def resolve_site(db, user_id=None, site_id=None):
    with db.get_session() as session:
        query = session.query(WordPressSite).filter_by(is_active=True)
        if site_id:
            query = query.filter_by(id=site_id)
        if user_id:
            query = query.filter_by(user_id=user_id)
        site = query.order_by(WordPressSite.created_at.asc()).first()
        if not site:
            return None
        return {
            "id": site.id,
            "user_id": site.user_id,
            "site_name": site.site_name,
            "language": site.language or "id",
            "selected_categories": site.selected_categories or [],
        }


def run_manual_research(user_id=None, site_id=None):
    db = Database(Config.DATABASE_URL)
    trending = TrendingResearch()

    site = resolve_site(db, user_id=user_id, site_id=site_id)
    if not site:
        print("[ERROR] Tidak ada website aktif yang cocok. Gunakan --user-id dan/atau --site-id.")
        return 1

    selected_categories = site["selected_categories"]
    if not selected_categories:
        print(f"[ERROR] Website '{site['site_name']}' belum memiliki selected_categories.")
        return 1

    print(f"Starting research for {len(selected_categories)} categories on {site['site_name']}...\n")

    results = []
    for category in selected_categories:
        category_name = category["name"]
        print(f"Researching: {category_name}")

        try:
            trending_data = trending.get_trending_topics(category_name, limit=15, language=site["language"])
            suggestions = trending.suggest_article_topics(category_name, count=10, language=site["language"])

            db.save_research_data(
                user_id=site["user_id"],
                site_id=site["id"],
                category=category_name,
                trending=trending_data.get("trending_now", []) if trending_data else [],
                rising=trending_data.get("related_rising", []) if trending_data else [],
                top=trending_data.get("related_top", []) if trending_data else [],
                suggestions=suggestions,
            )

            results.append({
                "category": category_name,
                "trending_count": len(trending_data.get("trending_now", [])) if trending_data else 0,
                "rising_count": len(trending_data.get("related_rising", [])) if trending_data else 0,
                "top_count": len(trending_data.get("related_top", [])) if trending_data else 0,
                "suggestions_count": len(suggestions),
            })

            print(f"   [OK] Found {len(suggestions)} suggested topics")
        except Exception as e:
            logger.exception("Research failed for %s", category_name)
            print(f"   [ERROR] {e}")

    print("\n" + "=" * 60)
    print("RESEARCH SUMMARY")
    print("=" * 60)
    for result in results:
        print(f"\n{result['category']}")
        print(f"   Trending Now: {result['trending_count']} topics")
        print(f"   Rising: {result['rising_count']} topics")
        print(f"   Popular: {result['top_count']} topics")
        print(f"   Suggestions: {result['suggestions_count']} topics")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run manual research for a WordPress site.")
    parser.add_argument("--user-id", type=int, help="Owner user ID")
    parser.add_argument("--site-id", type=int, help="WordPress site ID")
    args = parser.parse_args()
    raise SystemExit(run_manual_research(user_id=args.user_id, site_id=args.site_id))
