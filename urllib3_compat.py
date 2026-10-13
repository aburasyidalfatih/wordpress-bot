"""pytrends still passes the removed urllib3 Retry(method_whitelist=...) argument.

Importing this module (before pytrends) maps it to allowed_methods. Idempotent.
"""
import urllib3.util.retry

_Retry = urllib3.util.retry.Retry

if not getattr(_Retry.__init__, '_method_whitelist_compat', False):
    _original_init = _Retry.__init__

    def _patched_init(self, *args, **kwargs):
        if 'method_whitelist' in kwargs:
            kwargs['allowed_methods'] = kwargs.pop('method_whitelist')
        _original_init(self, *args, **kwargs)

    _patched_init._method_whitelist_compat = True
    _Retry.__init__ = _patched_init
