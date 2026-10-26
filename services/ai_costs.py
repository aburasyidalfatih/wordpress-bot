"""Estimated AI cost per call and per article job, for logs only.

Providers report their token usage here (record_usage); an article job opens a
ledger (track_costs) and names the pipeline step it is in (cost_stage), so one
summary line per article says what research, brief, writing, assessment,
rewrite, fact-check, image and similarity checks cost. Nothing here affects
credits or pricing.

The ledger lives in a ContextVar: calls on the job's thread are attributed to
the current stage. Work done on other threads (Claude web research runs on a
worker thread) is added explicitly with add_cost.

Prices are USD per million tokens for the default models only; any other model
(and Gemini / OpenAI, whose prices are not tracked in this repo) is recorded
with its token counts and an unknown cost.
"""
import contextvars
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# USD per million tokens. Cache writes are 1.25x input (5-minute cache).
CLAUDE_PRICES = {
    'claude-opus-5-5': {'input': 4.0, 'output': 20.0, 'cache_read': 0.20, 'cache_write': 5.0},
    'claude-sonnet-5-5': {'input': 2.0, 'output': 10.0, 'cache_read': 0.20, 'cache_write': 2.5},
    'claude-haiku-5-5': {'input': 0.10, 'output': 0.50, 'cache_read': 0.01, 'cache_write': 0.125},
}
# Order in the summary line; any other stage is appended after these.
STAGE_LABELS = (
    ('riset', 'riset'),
    ('cek kemiripan', 'cek kemiripan'),
    ('brief', 'brief'),
    ('tulis', 'tulis'),
    ('nilai', 'nilai'),
    ('revisi', 'revisi'),
    ('cek fakta', 'cek fakta'),
    ('gambar', 'gambar'),
)
OTHER_STAGE = 'lainnya'


def token_cost_usd(model, usage):
    """Estimated USD for usage ({input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens}) on model, or None when the model is not priced."""
    prices = CLAUDE_PRICES.get(str(model or ''))
    if not prices or not isinstance(usage, dict):
        return None
    total = (int(usage.get('input_tokens') or 0) * prices['input']
             + int(usage.get('output_tokens') or 0) * prices['output']
             + int(usage.get('cache_read_input_tokens') or 0) * prices['cache_read']
             + int(usage.get('cache_creation_input_tokens') or 0) * prices['cache_write'])
    return total / 1_000_000


class CostLedger:
    """Per-stage totals of one job: estimated USD, calls, calls with unknown cost, tokens."""

    def __init__(self):
        self.stages = {}

    def add(self, stage, cost=None, tokens=0):
        entry = self.stages.setdefault(stage or OTHER_STAGE, {'usd': 0.0, 'calls': 0, 'unpriced': 0, 'tokens': 0})
        entry['calls'] += 1
        entry['tokens'] += int(tokens or 0)
        if cost is None:
            entry['unpriced'] += 1
        else:
            entry['usd'] += float(cost)

    @property
    def total(self):
        return sum(entry['usd'] for entry in self.stages.values())

    @property
    def unpriced_calls(self):
        return sum(entry['unpriced'] for entry in self.stages.values())

    def summary(self, label):
        """'Biaya AI artikel <label>: riset $0.62, ..., total $1.26' (always lists the main stages)."""
        known = [stage for stage, _ in STAGE_LABELS]
        parts = []
        for stage, text in STAGE_LABELS:
            if stage in self.stages or stage in ('riset', 'brief', 'tulis', 'nilai', 'revisi', 'cek fakta'):
                parts.append(f"{text} ${self.stages.get(stage, {}).get('usd', 0.0):.2f}")
        for stage, entry in self.stages.items():
            if stage not in known:
                parts.append(f"{stage} ${entry['usd']:.2f}")
        line = f"Biaya AI artikel {label}: {', '.join(parts)}, total ${self.total:.2f}"
        if self.unpriced_calls:
            line += f" (+{self.unpriced_calls} panggilan tanpa tarif: Gemini/OpenAI/gambar)"
        return line


_ledger = contextvars.ContextVar('ai_cost_ledger', default=None)
_stage = contextvars.ContextVar('ai_cost_stage', default=None)


@contextmanager
def track_costs():
    """Open a ledger for the calls made in this context; yields it."""
    ledger = CostLedger()
    token = _ledger.set(ledger)
    try:
        yield ledger
    finally:
        _ledger.reset(token)


@contextmanager
def cost_stage(name):
    """Attribute the AI calls made inside to stage `name`."""
    token = _stage.set(name)
    try:
        yield
    finally:
        _stage.reset(token)


def current_stage():
    return _stage.get()


def add_cost(stage, cost, tokens=0):
    """Add a cost measured elsewhere (e.g. on another thread) to the open ledger."""
    ledger = _ledger.get()
    if ledger is not None:
        ledger.add(stage, cost, tokens)


def record_usage(provider, model, usage):
    """Record one provider call (usage may be None) in the open ledger, if any.

    Returns the estimated USD cost, or None when it is unknown.
    """
    cost = token_cost_usd(model, usage) if provider == 'anthropic' else None
    ledger = _ledger.get()
    if ledger is not None:
        tokens = sum(int((usage or {}).get(field) or 0) for field in (
            'input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
        ledger.add(_stage.get(), cost, tokens)
    return cost
