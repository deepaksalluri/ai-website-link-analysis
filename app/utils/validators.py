import ipaddress
import socket
from urllib.parse import urlsplit


class InvalidWebsite(ValueError):
    pass


def validate_url(url: str):
    if not url or url != url.strip() or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise InvalidWebsite('URL contains invalid whitespace or control characters.')
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise InvalidWebsite('Invalid URL or port.') from None
    if parts.scheme.lower() not in ('http', 'https') or not host or parts.username is not None or parts.password is not None:
        raise InvalidWebsite('Use an http(s) URL with a hostname and without credentials.')
    if port not in (None, 80, 443):
        raise InvalidWebsite('Only ports 80 and 443 are allowed.')
    if '%' in host or '\\' in url or any(c.isspace() for c in url):
        raise InvalidWebsite('Invalid hostname or URL characters.')
    try:
        ascii_host = host.encode('idna').decode('ascii').lower().rstrip('.')
    except UnicodeError:
        raise InvalidWebsite('Invalid hostname.') from None
    if not ascii_host or ascii_host == 'localhost' or ascii_host.endswith(('.localhost', '.local', '.internal')):
        raise InvalidWebsite('Local hostnames are not allowed.')
    return parts, ascii_host, port or (443 if parts.scheme.lower() == 'https' else 80)


def resolve_public(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise InvalidWebsite('Hostname could not be resolved.') from None
    addresses = list(dict.fromkeys(item[4][0] for item in records))
    if not addresses:
        raise InvalidWebsite('Hostname could not be resolved.')
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
            # IPv4-mapped IPv6 inherits the mapped IPv4 address's classification.
            if getattr(ip, 'ipv4_mapped', None):
                ip = ip.ipv4_mapped
            if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local:
                raise InvalidWebsite('Hostname resolves to a non-public network address.')
        except ValueError:
            raise InvalidWebsite('Invalid resolved address.') from None
    return addresses
