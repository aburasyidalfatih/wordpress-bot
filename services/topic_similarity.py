"""Topic cannibalization checks: is a candidate title about the same thing as an
article the site already published?

Two articles answering the same search intent compete with each other in
Google and read as scaled, commodity content. The check runs before an article
is generated (research topics and queue titles) and once more on the generated
title.

Scoring works on the significant words of each title: stopwords (Indonesian and
English), format words ("panduan", "guide", "tips", "ultimate", years, numbers)
and simple inflections (plurals, -ing, -nya) are removed, so "Eliminate Family
Debt Fast: Ultimate 2026 Household Payoff Guide" is reduced to
{eliminate, family, debt, household, payoff}. Overlap with each published title
is then measured as a weighted containment/Jaccard mix, with a bonus when both
share an adjacent word pair (the head keyword, e.g. "household payoff") and a
penalty when they do not, plus a word-level SequenceMatcher ratio as a secondary
signal for near-identical wording. Words that appear in a large share of the
site's titles (the site's niche words, e.g. "sekolah" on a school site) count
for less and cannot form the head keyword on their own.

Clear cases are decided by score alone: DEFINITE_THRESHOLD and up is the same
topic, below BORDERLINE_THRESHOLD a different one; no model call is made. In
between, lexical overlap cannot tell "Keamanan Sekolah Dasar" from "Kantin
Sekolah Dasar", so one tiny model call (same search intent: yes/no) decides
when a generator is given. Without a generator, or when that call fails, the
score decides: SIMILAR_THRESHOLD and up counts as the same topic.
"""
import html
import logging
import re
import unicodedata
from difflib import SequenceMatcher

try:
    from rq.timeouts import JobTimeoutException
except ImportError:  # pragma: no cover - rq is a runtime dependency
    class JobTimeoutException(Exception):
        """Stand-in so the except clause below stays valid without rq."""

logger = logging.getLogger(__name__)

# Room for Gemini's thinking tokens, which count against max_output_tokens: a
# small budget can end before any visible answer is written.
AI_CHECK_MAX_TOKENS = 4096

# See the module docstring for how the three thresholds are used.
DEFINITE_THRESHOLD = 0.85
SIMILAR_THRESHOLD = 0.5
BORDERLINE_THRESHOLD = 0.34

# A shared adjacent pair of significant words (in either order) is the head
# keyword of both titles. Overlap without one is scattered words, not a topic.
BIGRAM_BONUS = 0.15
NO_PHRASE_FACTOR = 0.75

# At most this many model confirmations per check (gray-zone matches only).
MAX_AI_CONFIRMATIONS = 2

# Niche words: in a corpus of at least MIN_CORPUS_FOR_WEIGHTS titles, a word
# found in more than COMMON_WORD_SHARE of them counts with COMMON_WORD_WEIGHT.
MIN_CORPUS_FOR_WEIGHTS = 8
COMMON_WORD_SHARE = 0.3
COMMON_WORD_WEIGHT = 0.5

STOPWORDS = frozenset("""
a an the and or of to in on for with from by at as is are be been being was were your you yours our
we us my me i it its this that these those what why when where how who whom which whose vs versus
into onto about without within over under after before between during do does did can could should
would will shall may might must more most than then every all any each some no not nor so too very
new now just also only own same other such here there their them they he she his her if but via per
off up out
yang dan di ke dari untuk dengan atau pada dalam ini itu agar supaya bagi oleh sebagai adalah akan
para serta tanpa hingga sampai saat ketika apa bagaimana mengapa kenapa kapan dimana siapa anda kamu
kita kami jadi juga lebih paling secara tentang terhadap buat biar tak tidak bukan jangan harus bisa
dapat sudah belum baru telah sedang masih nya pun lah kah yuk ayo begini begitu sangat banyak
""".split())

# Words that frame an article rather than say what it is about.
GENERIC_WORDS = frozenset("""
guide guides tips tip tricks trick ways way steps step how best ultimate complete definitive essential
essentials simple easy easiest quick fast faster proven practical smart top secret secrets checklist
explained everything need know beginner beginners introduction overview strategies strategy methods
method ideas idea hacks hack things reasons review reviews today year years update updated edition
free bonus must actually really expert pro pros full
panduan tips trik cara langkah strategi metode rahasia ampuh jitu terbaik terbaru terlengkap lengkap
mudah praktis efektif cepat pemula penting wajib tahu ketahui kenali simak inilah berikut daftar
ulasan review contoh ide hal alasan tahun update edisi gratis pasti benar benar mengenal memahami
pahami
""".split())

_TOKEN_RE = re.compile(r'[a-z]+')
_DOUBLE_CONSONANT_RE = re.compile(r'([bdfgklmnprtvz])\1$')


def _stem_en(word):
    if len(word) > 4 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 5 and word.endswith('ing'):
        word = word[:-3]
        # planning -> plann -> plan
        if _DOUBLE_CONSONANT_RE.search(word) and not word.endswith(('ll', 'ss')):
            word = word[:-1]
        return word
    if len(word) > 4 and word.endswith(('ches', 'shes', 'sses', 'xes')):
        return word[:-2]
    if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def _stem_id(word):
    # Possessive/definite suffix: "keuangannya" -> "keuangan". "-lah"/"-kan"
    # are left alone: "sekolah" and "pendidikan" end the same way.
    if len(word) > 5 and word.endswith('nya'):
        return word[:-3]
    return word


def significant_tokens(title, language='id'):
    """Ordered significant words of a title (see the module docstring)."""
    text = html.unescape(str(title or ''))
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()
    stem = _stem_en if language == 'en' else _stem_id
    tokens = []
    for word in _TOKEN_RE.findall(text):  # digits and punctuation are dropped here
        if len(word) < 2 or word in STOPWORDS or word in GENERIC_WORDS:
            continue
        word = stem(word)
        if word in STOPWORDS or word in GENERIC_WORDS:
            continue
        tokens.append(word)
    return tokens


def _bigrams(tokens):
    return {frozenset((a, b)) for a, b in zip(tokens, tokens[1:]) if a != b}


def _token_weights(token_lists):
    """Down-weight the site's niche words (see COMMON_WORD_SHARE)."""
    count = len(token_lists)
    if count < MIN_CORPUS_FOR_WEIGHTS:
        return {}
    frequency = {}
    for tokens in token_lists:
        for token in set(tokens):
            frequency[token] = frequency.get(token, 0) + 1
    return {token: COMMON_WORD_WEIGHT for token, df in frequency.items() if df / count > COMMON_WORD_SHARE}


def similarity_score(tokens_a, tokens_b, weights=None):
    """0..1 similarity of two significant-token lists."""
    set_a, set_b = set(tokens_a), set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    if set_a == set_b:
        return 1.0
    shared = set_a & set_b
    # One shared word ("budget", "sekolah") is a niche, not a topic.
    if len(shared) < 2:
        return 0.0
    weights = weights or {}

    def weight(tokens):
        return sum(weights.get(token, 1.0) for token in tokens)

    shared_weight = weight(shared)
    containment = shared_weight / min(weight(set_a), weight(set_b))
    jaccard = shared_weight / weight(set_a | set_b)
    score = 0.6 * containment + 0.4 * jaccard
    # The head keyword needs at least one word that is not a niche word.
    if any(any(weights.get(token, 1.0) >= 1.0 for token in pair)
           for pair in _bigrams(tokens_a) & _bigrams(tokens_b)):
        score += BIGRAM_BONUS
    else:
        score *= NO_PHRASE_FACTOR
    # Word-level: character-level ratios are inflated by shared niche suffixes.
    sequence = SequenceMatcher(None, list(tokens_a), list(tokens_b)).ratio()
    return min(1.0, max(score, sequence if sequence >= 0.8 else 0.0))


def _same_intent_by_ai(generator, candidate, existing, language):
    """True/False from the model, or None when it could not answer."""
    # Local import: only borderline matches need it.
    from services.article_review import extract_json_object

    prompt = (
        "Do these two article titles target the same search intent, so that one article would "
        "fully satisfy someone searching for the other and both would compete for the same "
        "Google queries? Different sub-topics, audiences or problems are NOT the same intent.\n"
        f"Language of the site: {'English' if language == 'en' else 'Indonesian'}.\n"
        f"Title A: {str(candidate)[:300]}\n"
        f"Title B: {str(existing)[:300]}\n"
        'Answer with JSON only: {"same_intent": true} or {"same_intent": false}'
    )
    try:
        reply = generator.generate_text(prompt, max_tokens=AI_CHECK_MAX_TOKENS)
        data = extract_json_object(reply)
    except JobTimeoutException:
        raise  # the RQ job ran out of time: not a reason to fall back
    except Exception as e:
        logger.warning(f"Topic similarity AI check failed: {e}")
        return None
    value = data.get('same_intent') if isinstance(data, dict) else None
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ('true', 'false', 'yes', 'no'):
        return value.strip().lower() in ('true', 'yes')
    logger.warning(f"Topic similarity AI check gave no usable answer: {str(reply)[:200]!r}")
    return None


def find_similar_published(candidate, published_titles, *, language='id', generator=None):
    """The published title `candidate` would cannibalize, as (title, score), or None.

    Scores at or above DEFINITE_THRESHOLD match outright. Gray-zone scores
    (BORDERLINE_THRESHOLD up to DEFINITE_THRESHOLD) are put to the model via
    generator.generate_text, at most MAX_AI_CONFIRMATIONS times per check; when
    no generator is given, the budget is spent or the model cannot answer, they
    match only from SIMILAR_THRESHOLD up.
    """
    candidate_tokens = significant_tokens(candidate, language)
    if not candidate_tokens:
        return None
    published = []
    seen = set()
    for title in published_titles or []:
        title = html.unescape(str(title or '')).strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        published.append((title, significant_tokens(title, language)))
    weights = _token_weights([tokens for _, tokens in published])

    scored = sorted(
        ((similarity_score(candidate_tokens, tokens, weights), title) for title, tokens in published),
        key=lambda pair: pair[0], reverse=True,
    )
    confirmations = 0
    for score, title in scored:
        if score < BORDERLINE_THRESHOLD:
            break
        if score < DEFINITE_THRESHOLD and generator is not None and confirmations < MAX_AI_CONFIRMATIONS:
            confirmations += 1
            same_intent = _same_intent_by_ai(generator, candidate, title, language)
            if same_intent is not None:
                logger.info(f"AI same-intent check '{candidate}' ~ '{title}' (score {score:.2f}): {same_intent}")
                if same_intent:
                    return title, round(score, 3)
                continue
            logger.warning(
                f"AI same-intent check unavailable for '{candidate}' ~ '{title}'; falling back to the "
                f"score ({score:.2f}, similar from {SIMILAR_THRESHOLD})."
            )
        if score >= SIMILAR_THRESHOLD:
            return title, round(score, 3)
    return None
