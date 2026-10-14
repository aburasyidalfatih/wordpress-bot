"""Shared stubs for the article quality and job lock tests (no test cases here).

Job tests that are about other steps patch both model calls out with
quality_stub_patches(jobs): no brief, and every article passes the assessment
unchanged, so the history note gains PASSING_NOTE.

LockRedis is the research tests' FakeRedis plus the Lua scripts of
services.job_locks, emulated in Python (they are recognised by identity).
"""
from unittest.mock import Mock, patch

from services import job_locks
from services.article_quality import CRITERIA, Assessment, QualityOutcome
from test_research_backend_support import FakeRedis

PASSING = Assessment({criterion: 5 for criterion in CRITERIA}, 'Bagus')
PASSING_NOTE = 'Kualitas AI: 5,0/5 (tanpa revisi).'


def approve_quality(generator, article, **kwargs):
    return QualityOutcome(article, PASSING, PASSING)


def quality_stub_patches(jobs):
    return [
        patch.object(jobs, 'build_content_brief', Mock(return_value=None)),
        patch.object(jobs, 'improve_article', Mock(side_effect=approve_quality)),
    ]


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


class LockRedis(FakeRedis):
    """FakeRedis that also runs the job_locks scripts."""

    def __init__(self):
        super().__init__()
        self.scripts = []

    def _owned_by(self, key, owner):
        value = _text(self.get(key))
        return value is not None and (value == owner or value.startswith(owner + '|'))

    def eval(self, script, numkeys, *args):
        keys, argv = args[:numkeys], [str(a) for a in args[numkeys:]]
        if script is job_locks.COMPARE_AND_SET_LUA:
            self.scripts.append('cas')
            if _text(self.get(keys[0])) == argv[0]:
                self.set(keys[0], argv[1], ex=int(argv[2]))
                return 1
            return 0
        if script is job_locks.OWNER_EXPIRE_LUA:
            self.scripts.append('expire')
            return int(self._owned_by(keys[0], argv[0]) and self.expire(keys[0], int(argv[1])))
        if script is job_locks.OWNER_DELETE_LUA:
            self.scripts.append('delete')
            return self.delete(keys[0]) if self._owned_by(keys[0], argv[0]) else 0
        return super().eval(script, numkeys, *args)
