"""Which web research engine SEOResearch gets for an AI config.

Claude web research (services.claude_research) when there is an Anthropic key
and Claude is not paused; Gemini with Google Search grounding
(services.gemini_research) when Claude is unavailable and there is a Gemini
key; with both, Claude first and Gemini for the same research when Claude
cannot run (rejected key, usage limit). None means classic research only.

The engine modules are imported only when their key is present: they pull in
SDKs and seo_research.
"""
import logging

from services.ai_providers import claude_auth_paused, claude_usage_paused

logger = logging.getLogger(__name__)

# ClaudeWebResearch.last_failure values that make Gemini run for the same call
# (claude_research.FAILURE_AUTH / FAILURE_USAGE_LIMIT). Other failures (time
# budget spent, an unusable reply) are not retried: Claude already used its
# time budget, and the classic providers take over.
FALLBACK_FAILURES = ('auth', 'usage_limit')


class FallbackWebResearch:
    """Claude web research, with Gemini web research for the same call when
    Claude cannot run. Same interface as the engines; model, label and
    source_key describe the engine that ran last, which is what SEOResearch
    reads after research()."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self.active = primary
        self.last_error = None

    @property
    def model(self):
        return getattr(self.active, 'model', None)

    @property
    def source_key(self):
        return getattr(self.active, 'source_key', None)

    @property
    def label(self):
        return getattr(self.active, 'label', None)

    def research(self, topic, language='id', **options):
        self.active = self.primary
        result = self.primary.research(topic, language, **options)
        self.last_error = getattr(self.primary, 'last_error', None)
        failure = getattr(self.primary, 'last_failure', None)
        if result is not None or failure not in FALLBACK_FAILURES:
            return result
        logger.info(f"Claude web research unavailable for '{topic}' ({failure}); using Gemini web research.")
        self.active = self.fallback
        result = self.fallback.research(topic, language, **options)
        self.last_error = getattr(self.fallback, 'last_error', None)
        return result


def _claude_engine(config):
    api_key = str(config.get('anthropic_api_key') or '').strip()
    if not api_key:
        return None
    if claude_usage_paused() or claude_auth_paused(api_key):
        logger.info("Claude web research is paused (usage limit or rejected key); not using it.")
        return None
    try:
        from services.claude_research import from_config
        return from_config(config)
    except Exception as e:
        logger.warning(f"Claude web research unavailable: {e}")
        return None


def _gemini_engine(config):
    if not str(config.get('gemini_api_key') or '').strip():
        return None
    try:
        from services.gemini_research import from_config
        return from_config(config)
    except Exception as e:
        logger.warning(f"Gemini web research unavailable: {e}")
        return None


def research_engine_from_config(config):
    """The web research engine for the effective AI config (load_config()), or None.

    Claude when it has a key and is not paused (usage limit, rejected key);
    else Gemini when it has a key; with both, a FallbackWebResearch that tries
    Claude first. Each engine also honours its kill switch
    (CLAUDE_WEB_RESEARCH, GEMINI_WEB_RESEARCH).
    """
    if not isinstance(config, dict):
        return None
    claude = _claude_engine(config)
    gemini = _gemini_engine(config)
    if claude is not None and gemini is not None:
        return FallbackWebResearch(claude, gemini)
    return claude or gemini
