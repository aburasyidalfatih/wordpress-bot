"""Shared test fixtures."""
import sys

import pytest


@pytest.fixture(autouse=True)
def _no_real_claude_pause_store(monkeypatch):
    """Keep the Claude usage-limit pause (services.ai_providers) off the real Redis.

    Without this, every Claude call in a test would import core_extensions and
    talk to whatever Redis runs locally. Tests of the pause patch _pause_store
    themselves. Only patched when a test module already imported the provider
    layer, so this fixture imports nothing.
    """
    module = sys.modules.get('services.ai_providers')
    if module is not None and getattr(module, '__file__', None):
        monkeypatch.setattr(module, '_pause_store', lambda: None)
