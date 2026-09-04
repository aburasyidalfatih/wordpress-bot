"""Turn evidence into concrete content actions.

Search Console is the only first-party performance data in AutoWP: real queries
that really produced impressions on the user's own site. It used to be collected,
scored and then only rendered in the UI. This module feeds it back into topic
selection and title generation, and works out which of three different actions a
given opportunity actually calls for.

Also holds content-gap analysis (competitor topics we have never written about)
and search-intent classification, both of which shape how an article is written.
"""

import re
import logging
from collections import Counter

logger = logging.getLogger(__name__)

# Each opportunity type needs a different response. Writing a brand new article
# for a low-CTR page that already ranks on page one wastes a credit and creates a
# competing page; the fix there is the title and meta, not more content.
ACTION_NEW_ARTICLE = 'new_article'
ACTION_REWRITE_META = 'rewrite_meta'
ACTION_REFRESH_CONTENT = 'refresh_content'

ACTION_BY_OPPORTUNITY = {
    'quick_win': ACTION_NEW_ARTICLE,
    'low_ctr': ACTION_REWRITE_META,
    'declining': ACTION_REFRESH_CONTENT,
}

ACTION_LABELS = {
    ACTION_NEW_ARTICLE: 'Buat artikel pendukung untuk memperkuat topik ini',
    ACTION_REWRITE_META: 'Tulis ulang title & meta description (jangan buat artikel baru)',
    ACTION_REFRESH_CONTENT: 'Perbarui artikel lama dan segarkan datanya',
}

# Intent shapes the article: a "how to" query wants steps, a "best/review" query
# wants comparison, a brand query wants a direct answer.
INTENT_PATTERNS = {
    'transactional': [
        r'\bbeli\b', r'\bharga\b', r'\bbiaya\b', r'\btarif\b', r'\bdiskon\b', r'\bmurah\b',
        r'\bbuy\b', r'\bprice\b', r'\bcost\b', r'\bcheap\b', r'\bdeal\b', r'\border\b',
    ],
    'commercial': [
        r'\bterbaik\b', r'\brekomendasi\b', r'\bbanding\b', r'\bvs\b', r'\breview\b',
        r'\bulasan\b', r'\balternatif\b',
        r'\bbest\b', r'\btop\s*\d', r'\bcompare\b', r'\bcomparison\b', r'\balternative\b',
    ],
    'informational': [
        r'\bapa\b', r'\bapakah\b', r'\bbagaimana\b', r'\bcara\b', r'\bkenapa\b', r'\bmengapa\b',
        r'\bpanduan\b', r'\bcontoh\b', r'\bpengertian\b', r'\btips\b',
        r'\bwhat\b', r'\bhow\b', r'\bwhy\b', r'\bguide\b', r'\bexample\b', r'\btutorial\b',
    ],
}

INTENT_GUIDANCE = {
    'transactional': {
        'id': 'Pembaca siap mengambil keputusan. Sertakan rincian biaya, syarat, dan langkah konkret berikutnya.',
        'en': 'The reader is ready to act. Include concrete costs, requirements and next steps.',
    },
    'commercial': {
        'id': 'Pembaca sedang membandingkan pilihan. Sajikan tabel perbandingan, kelebihan dan kekurangan yang jujur.',
        'en': 'The reader is comparing options. Provide a comparison table and honest pros and cons.',
    },
    'informational': {
        'id': 'Pembaca ingin memahami. Utamakan penjelasan bertahap, definisi yang jelas, dan contoh.',
        'en': 'The reader wants to understand. Lead with clear definitions, staged explanation and examples.',
    },
    'navigational': {
        'id': 'Pembaca mencari sesuatu yang spesifik. Jawab langsung di awal, jangan bertele-tele.',
        'en': 'The reader is looking for something specific. Answer directly up front.',
    },
}


def classify_intent(query):
    """Classify a search query into transactional / commercial / informational / navigational.

    Checked most-specific first: "harga tiket terbaik" is transactional, not commercial.
    """
    if not query:
        return 'informational'
    text = str(query).lower()
    for intent in ('transactional', 'commercial', 'informational'):
        for pattern in INTENT_PATTERNS[intent]:
            if re.search(pattern, text):
                return intent
    # Short queries with no question or comparison signal usually target a
    # specific page or brand.
    return 'navigational' if len(text.split()) <= 2 else 'informational'


def intent_guidance(intent, language='id'):
    entry = INTENT_GUIDANCE.get(intent) or INTENT_GUIDANCE['informational']
    return entry.get('en' if language == 'en' else 'id', '')


def plan_from_opportunities(opportunities, limit=10):
    """Attach a recommended action and intent to each Search Console opportunity."""
    planned = []
    for opp in opportunities or []:
        action = ACTION_BY_OPPORTUNITY.get(opp.get('type'), ACTION_NEW_ARTICLE)
        intent = classify_intent(opp.get('query'))
        planned.append({
            **opp,
            'action': action,
            'action_label': ACTION_LABELS[action],
            'intent': intent,
        })
    planned.sort(key=lambda item: item.get('score', 0), reverse=True)
    return planned[:limit]


def topic_candidates_from_opportunities(opportunities, limit=8):
    """Queries worth writing a new article for, best first.

    Only quick wins become new articles. low_ctr and declining are handled by
    editing what already exists.
    """
    candidates = []
    seen = set()
    for opp in plan_from_opportunities(opportunities, limit=len(opportunities or [])):
        if opp['action'] != ACTION_NEW_ARTICLE:
            continue
        query = (opp.get('query') or '').strip()
        key = query.lower()
        if not query or key in seen:
            continue
        seen.add(key)
        candidates.append({
            'query': query,
            'impressions': opp.get('impressions'),
            'position': opp.get('position'),
            'score': opp.get('score'),
            'intent': opp.get('intent'),
        })
        if len(candidates) >= limit:
            break
    return candidates


def keyword_demand_map(current_metrics):
    """Impressions per query, used as a free first-party proxy for search volume.

    Keyword tools are paid; Search Console impressions are real demand data for
    queries this site already appears for, which is exactly the subset that matters.
    """
    demand = {}
    for row in current_metrics or []:
        query = (row.get('query') or '').strip().lower()
        if not query:
            continue
        demand[query] = demand.get(query, 0) + float(row.get('impressions') or 0)
    return demand


def annotate_keywords_with_demand(keywords, demand_map):
    """Attach known impression counts to researched keywords.

    Returns dicts so downstream code can rank by real demand rather than treating
    every autocomplete suggestion as equally valuable.
    """
    annotated = []
    for kw in keywords or []:
        text = kw.get('keyword') if isinstance(kw, dict) else str(kw)
        if not text:
            continue
        impressions = demand_map.get(text.strip().lower())
        annotated.append({
            'keyword': text,
            'impressions': round(impressions) if impressions is not None else None,
            'has_demand_data': impressions is not None,
            'intent': classify_intent(text),
        })
    # Keywords with measured demand first, ordered by that demand.
    annotated.sort(key=lambda k: (k['has_demand_data'], k['impressions'] or 0), reverse=True)
    return annotated


_STOPWORDS = {
    'yang', 'dan', 'untuk', 'dengan', 'dari', 'pada', 'adalah', 'atau', 'dalam',
    'ini', 'itu', 'akan', 'bisa', 'dapat', 'agar', 'oleh', 'juga', 'saja',
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'you', 'your',
    'how', 'what', 'why', 'can', 'will', 'all', 'best', 'about',
}


def _topic_tokens(text):
    words = re.findall(r'\w+', (text or '').lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def find_content_gaps(competitor_outlines, existing_titles, limit=8):
    """Competitor subtopics we have never written about.

    Both inputs are already stored: competitor headings come from research,
    existing titles from post_logs. Comparing them is essentially free and
    surfaces concrete article ideas grounded in what actually ranks.
    """
    covered = Counter()
    for title in existing_titles or []:
        covered.update(_topic_tokens(title))

    gaps = []
    seen = set()
    for competitor in competitor_outlines or []:
        for heading in competitor.get('headers') or []:
            heading = ' '.join(str(heading).split()).strip()
            key = heading.lower()
            if not heading or key in seen or len(heading.split()) < 3:
                continue
            tokens = _topic_tokens(heading)
            if not tokens:
                continue
            # Considered covered when most of its distinctive words already
            # appear across our published titles.
            overlap = sum(1 for t in tokens if covered.get(t)) / len(tokens)
            if overlap >= 0.5:
                continue
            seen.add(key)
            gaps.append({
                'topic': heading,
                'source': competitor.get('title') or competitor.get('url'),
                'coverage': round(overlap, 2),
                'intent': classify_intent(heading),
            })
            if len(gaps) >= limit:
                return gaps
    return gaps
