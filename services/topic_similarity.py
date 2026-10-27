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

Before any scoring the CORE topic is compared (core_topic_match). A title's
core is its framing-free head: the part before ':' (or " - ", " | ") when that
part names a topic, otherwise the whole title, without framing words
("panduan", "peta jalan", "blueprint", "siasat", "rules", years, numbers). Two
titles with the same core, or where one title's core is a whole part of the
other, are the same topic outright, whatever the niche weights or the model
say: "Peta Jalan Digitalisasi Pendidikan 2026: Rencana Aksi Sekolah" and
"Panduan Digitalisasi Pendidikan 2026: Rencana Aksi Guru" share the head
{digitalisasi, pendidikan}, as do "Family Budgeting Basics: X" and "Family
Budgeting Basics: Y". Niche words are exactly what such repeated heads are made
of, so without this check they were down-weighted into passing.
Shared vocabulary is not a shared core: "Emergency Fund Calculator" ({emergency,
fund, calculator}) and "Where to Keep Your Emergency Fund" ({keep, emergency,
fund}) answer different questions (how much to save vs. where to hold it), so
the core check lets the pair through and the scoring below decides (gray zone:
the model check; without a model the score still matches them, as before).

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

# Framing that only shapes a title, removed when the core topic is compared.
# Kept out of GENERIC_WORDS (which also feeds the lexical score and the
# research-topic relevance check) because some are topic words on other sites.
CORE_FRAMING_WORDS = frozenset("""
siasat taktis taktik blueprint arsitektur roadmap rules rule basics basic fundamentals fundamental
playbook framework masterclass handbook primer kiat jurus solusi cerdas analisis analysis explainer
tutorial opini opinion wawancara interview infografis infographic
""".split())
CORE_FRAMING_PHRASES = ('peta jalan', 'road map', 'langkah langkah', 'step by step', 'how to', 'studi kasus',
                        'case study', 'case studies', 'tanya jawab')

# Separators between a title's head and its subtitle: ':', or a spaced hyphen,
# en dash, em dash or bar.
_HEAD_SEPARATOR_RE = re.compile('\\s*(?::|\\s[-\u2013\u2014|]\\s)\\s*')

# A core needs this many words to stand for a topic: one word ("Kurikulum: ...",
# "Budget: ...") is a niche, not a topic.
MIN_CORE_WORDS = 2

# Score reported for a core-topic match (above DEFINITE_THRESHOLD).
CORE_MATCH_SCORE = 0.9

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


def _ascii_lower(text):
    text = html.unescape(str(text or ''))
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()


def core_tokens(text, language='id'):
    """Significant words of text without framing words or framing phrases."""
    lowered = ' '.join(_TOKEN_RE.findall(_ascii_lower(text)))
    for phrase in CORE_FRAMING_PHRASES:
        lowered = re.sub(rf'\b{phrase}\b', ' ', lowered)
    stem = _stem_en if language == 'en' else _stem_id
    framing = CORE_FRAMING_WORDS | {stem(word) for word in CORE_FRAMING_WORDS}
    return [token for token in significant_tokens(lowered, language) if token not in framing]


def _title_parts(title):
    """The head and subtitle(s) of a title, split on ':', ' - ', ' | '."""
    # Split before the ASCII fold, which drops the dashes.
    parts = _HEAD_SEPARATOR_RE.split(html.unescape(str(title or '')))
    return [_ascii_lower(part) for part in parts if part.strip()]


def title_core(title, language='id'):
    """The core topic of a title as a frozenset of words, or None when too short.

    The head before the first separator when it has MIN_CORE_WORDS core words
    (a published title prefix is what a series of articles repeats), else the
    whole title.
    """
    parts = _title_parts(title)
    if len(parts) > 1:
        head = frozenset(core_tokens(parts[0], language))
        if len(head) >= MIN_CORE_WORDS:
            return head
    whole = frozenset(core_tokens(title, language))
    return whole if len(whole) >= MIN_CORE_WORDS else None


def _distinct_subtitles(title_a, title_b, language='id'):
    """True when both titles have a subtitle and they share under half their core words."""
    words = []
    for title in (title_a, title_b):
        parts = _title_parts(title)
        if len(parts) < 2:
            return False
        subtitle = set(core_tokens(' '.join(parts[1:]), language))
        if not subtitle:
            return False
        words.append(subtitle)
    shared = len(words[0] & words[1])
    return shared / min(len(words[0]), len(words[1])) < 0.5


def core_signature(title, language='id'):
    """(core, keys) of a title, computed once when it is compared many times.

    core is title_core(); keys are the word sets another title's core can match:
    the whole title's core and the core of each of its parts.
    """
    keys = set()
    for text in [title] + _title_parts(title):
        core = frozenset(core_tokens(text, language))
        if len(core) >= MIN_CORE_WORDS:
            keys.add(core)
    return title_core(title, language), frozenset(keys)


def signatures_match(signature_a, signature_b):
    """core_topic_match on two core_signature() results."""
    (core_a, keys_a), (core_b, keys_b) = signature_a, signature_b
    if core_a is None or core_b is None:
        return False
    return core_a == core_b or core_a in keys_b or core_b in keys_a


def core_topic_match(title_a, title_b, language='id'):
    """True when both titles are about the same core topic (see the module docstring).

    Same core, or one title's core is a whole part of the other: "Digitalisasi
    Pendidikan 2026" vs "Peta Jalan Digitalisasi Pendidikan 2026: Rencana Aksi",
    or "From Paycheck Pressure to Peace: Family Budgeting Basics" vs "Family
    Budgeting Basics: Reclaim Household Cash Flow".
    """
    return signatures_match(core_signature(title_a, language), core_signature(title_b, language))


def restates_category(title, category, language='id'):
    """True when the title's core is just the category's head term ("Digitalisasi
    Pendidikan 2026: ..." in category "Digitalisasi Pendidikan"). A one-word
    category has no core and never matches."""
    category_core = title_core(category, language)
    return category_core is not None and title_core(title, language) == category_core


def drop_core_repeats(candidates, existing_titles, *, language='id', category=None):
    """Candidates whose core topic repeats neither an existing title, nor an
    earlier kept candidate, nor (with category) just the category's head term.

    Candidates are strings or dicts with a 'topic'/'title'; order is kept.
    Returns (kept, dropped) as lists of the original items.
    """
    existing = [core_signature(title, language) for title in existing_titles or [] if title]
    kept, dropped = [], []
    for item in candidates or []:
        text = item.get('topic') or item.get('title') if isinstance(item, dict) else item
        text = str(text or '').strip()
        if not text:
            dropped.append(item)
            continue
        signature = core_signature(text, language)
        if (category and restates_category(text, category, language)) or any(
                signatures_match(signature, other) for other in existing):
            dropped.append(item)
            continue
        kept.append(item)
        existing.append(signature)
    return kept, dropped


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


def find_similar_published(candidate, published_titles, *, language='id', generator=None, corpus=None):
    """The published title `candidate` would cannibalize, as (title, score), or None.

    corpus: titles the niche-word weights are computed from, when matching only
    against a few of them (e.g. the titles published since a check ran);
    defaults to published_titles.

    A published title with the same core topic (core_topic_match) matches
    first, without a model call, with a score of at least CORE_MATCH_SCORE.
    Otherwise scores at or above DEFINITE_THRESHOLD match outright. Gray-zone scores
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
    if corpus is None:
        weights = _token_weights([tokens for _, tokens in published])
    else:
        corpus_titles = {html.unescape(str(t or '')).strip().lower() for t in list(corpus) + [t for t, _ in published]}
        weights = _token_weights([significant_tokens(t, language) for t in corpus_titles if t])

    candidate_signature = core_signature(candidate, language)
    confirmations = 0
    ai_cleared = set()  # titles the model already judged to be a different intent
    for title, tokens in published:
        if signatures_match(candidate_signature, core_signature(title, language)):
            score = max(similarity_score(candidate_tokens, tokens, weights), CORE_MATCH_SCORE)
            # A shared "Head: subtitle" core is usually a repeat, but a planned
            # series ("Manajemen Keuangan Sekolah: RAPBS" / "...: Laporan BOS")
            # is not. When both subtitles say clearly different things, the
            # model decides; similar subtitles are blocked without asking.
            if (generator is not None and confirmations < MAX_AI_CONFIRMATIONS
                    and _distinct_subtitles(candidate, title, language)):
                confirmations += 1
                same_intent = _same_intent_by_ai(generator, candidate, title, language)
                if same_intent is False:
                    logger.info(f"Core topic of '{candidate}' matches '{title}', but the AI sees a different intent.")
                    ai_cleared.add(title)
                    continue
            logger.info(f"Core topic of '{candidate}' repeats published '{title}'.")
            return title, round(score, 3)

    scored = sorted(
        ((similarity_score(candidate_tokens, tokens, weights), title) for title, tokens in published),
        key=lambda pair: pair[0], reverse=True,
    )
    for score, title in scored:
        if score < BORDERLINE_THRESHOLD:
            break
        if title in ai_cleared:
            continue
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
