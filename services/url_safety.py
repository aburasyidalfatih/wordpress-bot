"""Guard server-side HTTP fetches against SSRF.

User-supplied URLs (a WordPress base URL, for example) are fetched by the web
and worker containers. Without validation a user could point them at
internal services (postgres, redis, the cloud metadata endpoint, ...).
"""
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2000

# Names that resolve to internal services inside the docker network or the host.
BLOCKED_HOSTNAMES = {
    'localhost', 'localhost.localdomain', 'ip6-localhost', 'ip6-loopback',
    'postgres', 'redis', 'web', 'worker', 'db', 'traefik', 'dispatcher',
    'metadata', 'metadata.google.internal',
}
BLOCKED_HOSTNAME_SUFFIXES = ('.localhost', '.local', '.internal', '.localdomain', '.lan', '.home.arpa')

_NAT64_PREFIX = ipaddress.ip_network('64:ff9b::/96')


def is_public_ip(ip):
    """True only for globally routable unicast addresses."""
    if isinstance(ip, str):
        ip = ipaddress.ip_address(ip)
    if isinstance(ip, ipaddress.IPv6Address):
        # Addresses that embed an IPv4 address are judged by that address.
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return is_public_ip(ip.sixtofour)
        if ip.teredo is not None:
            return False
        if ip in _NAT64_PREFIX:
            return is_public_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        return False
    return ip.is_global


def _resolve(host, port):
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return {info[4][0] for info in infos}


def validate_public_http_url(url, resolve=True):
    """Validate a URL that the server is about to fetch.

    Returns ``(True, normalized_url)`` or ``(False, error_message)``. The
    normalized URL keeps scheme, host, port and path, drops the query string
    and fragment, and has no trailing slash, which suits a WordPress base URL.
    """
    if not isinstance(url, str):
        return False, 'URL harus berupa teks.'
    url = url.strip()
    if not url:
        return False, 'URL wajib diisi.'
    if len(url) > MAX_URL_LENGTH:
        return False, 'URL terlalu panjang.'
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        return False, 'URL mengandung karakter yang tidak valid.'

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False, 'Format URL tidak valid.'

    scheme = (parts.scheme or '').lower()
    if scheme not in ('http', 'https'):
        return False, 'URL harus diawali http:// atau https://.'
    if parts.username is not None or parts.password is not None or '@' in parts.netloc:
        return False, 'URL tidak boleh berisi kredensial.'

    host = (parts.hostname or '').rstrip('.').lower()
    if not host:
        return False, 'URL harus memiliki hostname.'

    literal_ip = None
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # not an IP literal, so a hostname

    if literal_ip is not None:
        if not is_public_ip(literal_ip):
            return False, 'URL mengarah ke alamat jaringan internal.'
        addresses = {str(literal_ip)}
    else:
        if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_HOSTNAME_SUFFIXES):
            return False, 'URL mengarah ke host internal.'
        if '.' not in host:
            # Single-label names resolve to docker services or LAN hosts.
            return False, 'Hostname harus berupa domain lengkap.'
        addresses = set()
        if resolve:
            try:
                addresses = _resolve(host, port or (443 if scheme == 'https' else 80))
            except (socket.gaierror, UnicodeError, OSError):
                return False, 'Hostname tidak dapat di-resolve.'
            if not addresses:
                return False, 'Hostname tidak dapat di-resolve.'

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split('%', 1)[0])
        except ValueError:
            return False, 'Hostname di-resolve ke alamat yang tidak valid.'
        if not is_public_ip(ip):
            return False, 'URL mengarah ke alamat jaringan internal.'

    netloc = f'[{host}]' if literal_ip is not None and literal_ip.version == 6 else host
    if port is not None:
        netloc = f'{netloc}:{port}'
    path = parts.path.rstrip('/')
    return True, urlunsplit((scheme, netloc, path, '', ''))
