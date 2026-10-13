"""The Research page treats Search Console as additive: a failure in its metric
store must degrade to "no opportunities" with a message, not take the page down."""
import importlib
import logging
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from sqlalchemy.exc import OperationalError


def load_research_module():
    """Import routes.research with core_extensions stubbed out."""
    core = types.ModuleType('core_extensions')
    core.db = None
    core.q = None
    core.trending = None
    core.redis_conn = None
    core.logger = logging.getLogger('test-research')
    core.load_config = lambda *a, **k: {}
    core.require_jwt = lambda f: f
    with patch.dict(sys.modules, {'core_extensions': core}):
        for name in ('routes.research', 'routes.prompts', 'rate_limit'):
            sys.modules.pop(name, None)
        module = importlib.import_module('routes.research')
    for name in ('routes.research', 'routes.prompts', 'rate_limit'):
        sys.modules.pop(name, None)
    return module


research = load_research_module()


class FailingDb:
    @contextmanager
    def get_session(self):
        raise OperationalError('SELECT 1', {}, Exception('relation does not exist'))
        yield  # pragma: no cover


class SearchConsoleIsolationTests(unittest.TestCase):
    def test_metric_store_failure_returns_empty_opportunities_with_message(self):
        with patch.object(research, 'db', FailingDb()):
            metrics, opportunities, error = research._load_search_console_opportunities(1, 2)
        self.assertEqual(metrics, [])
        self.assertEqual(opportunities, [])
        self.assertTrue(error)


if __name__ == '__main__':
    unittest.main()
