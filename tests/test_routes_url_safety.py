import socket
import unittest
from unittest.mock import patch

from services import url_safety
from services.url_safety import is_public_ip, validate_public_http_url


def fake_dns(*addresses):
    """Patch getaddrinfo to resolve every host to the given addresses."""
    def getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ':' in a else socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, port))
                for a in addresses]
    return patch.object(url_safety.socket, 'getaddrinfo', side_effect=getaddrinfo)


class ValidatePublicHttpUrlTests(unittest.TestCase):
    def test_public_url_is_normalized(self):
        with fake_dns('93.184.216.34'):
            ok, result = validate_public_http_url('  HTTPS://Example.com/blog/?utm=1#top ')
        self.assertTrue(ok)
        self.assertEqual(result, 'https://example.com/blog')

    def test_port_is_kept_and_trailing_slash_removed(self):
        with fake_dns('93.184.216.34'):
            ok, result = validate_public_http_url('http://example.com:8080/')
        self.assertTrue(ok)
        self.assertEqual(result, 'http://example.com:8080')

    def test_rejects_non_http_schemes(self):
        for url in ('ftp://example.com', 'file:///etc/passwd', 'gopher://example.com', 'example.com'):
            ok, _ = validate_public_http_url(url)
            self.assertFalse(ok, url)

    def test_rejects_non_string_and_empty(self):
        for url in (None, 123, '', '   '):
            ok, _ = validate_public_http_url(url)
            self.assertFalse(ok, repr(url))

    def test_rejects_credentials_in_url(self):
        with fake_dns('93.184.216.34'):
            ok, _ = validate_public_http_url('https://user:pass@example.com')
        self.assertFalse(ok)

    def test_rejects_internal_hostnames_without_dns(self):
        with patch.object(url_safety.socket, 'getaddrinfo') as resolver:
            for url in ('http://localhost', 'http://LOCALHOST:5000', 'http://postgres:5432',
                        'http://redis:6379', 'http://web', 'http://worker:8000',
                        'http://foo.localhost', 'http://metadata.google.internal'):
                ok, _ = validate_public_http_url(url)
                self.assertFalse(ok, url)
            resolver.assert_not_called()

    def test_rejects_single_label_hosts(self):
        ok, _ = validate_public_http_url('http://intranet/')
        self.assertFalse(ok)
        # Decimal-encoded 127.0.0.1 is also a single label.
        ok, _ = validate_public_http_url('http://2130706433/')
        self.assertFalse(ok)

    def test_rejects_private_ip_literals(self):
        for url in ('http://127.0.0.1', 'http://10.0.0.5', 'http://172.16.3.4', 'http://192.168.1.1',
                    'http://169.254.169.254/latest/meta-data', 'http://0.0.0.0', 'http://100.64.0.1',
                    'http://224.0.0.1', 'http://[::1]', 'http://[fe80::1]', 'http://[fc00::1]',
                    'http://[::]', 'http://[::ffff:127.0.0.1]', 'http://[::ffff:10.0.0.1]'):
            ok, _ = validate_public_http_url(url)
            self.assertFalse(ok, url)

    def test_public_ip_literals_are_allowed(self):
        ok, result = validate_public_http_url('http://8.8.8.8/wp')
        self.assertTrue(ok)
        self.assertEqual(result, 'http://8.8.8.8/wp')
        ok, result = validate_public_http_url('https://[2606:4700:4700::1111]:8443/')
        self.assertTrue(ok)
        self.assertEqual(result, 'https://[2606:4700:4700::1111]:8443')

    def test_rejects_domain_resolving_to_private_address(self):
        for address in ('127.0.0.1', '10.1.2.3', '169.254.169.254', '::1', '::ffff:192.168.0.1'):
            with fake_dns(address):
                ok, _ = validate_public_http_url('https://evil.example.com')
            self.assertFalse(ok, address)

    def test_rejects_when_any_resolved_address_is_private(self):
        with fake_dns('93.184.216.34', '10.0.0.1'):
            ok, _ = validate_public_http_url('https://mixed.example.com')
        self.assertFalse(ok)

    def test_rejects_unresolvable_host(self):
        with patch.object(url_safety.socket, 'getaddrinfo', side_effect=socket.gaierror('nope')):
            ok, _ = validate_public_http_url('https://does-not-exist.example')
        self.assertFalse(ok)

    def test_rejects_invalid_port(self):
        ok, _ = validate_public_http_url('http://example.com:99999')
        self.assertFalse(ok)


class IsPublicIpTests(unittest.TestCase):
    def test_embedded_ipv4_is_checked(self):
        self.assertFalse(is_public_ip('::ffff:127.0.0.1'))
        self.assertFalse(is_public_ip('2002:7f00:1::'))      # 6to4 of 127.0.0.1
        self.assertFalse(is_public_ip('64:ff9b::a00:1'))     # NAT64 of 10.0.0.1
        self.assertTrue(is_public_ip('::ffff:8.8.8.8'))

    def test_global_addresses(self):
        self.assertTrue(is_public_ip('1.1.1.1'))
        self.assertTrue(is_public_ip('2606:4700:4700::1111'))


if __name__ == '__main__':
    unittest.main()
