"""Single-page fetcher; DNS is validated and the connection is pinned to an approved IP."""
from dataclasses import dataclass
import http.client
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup
from app.utils.validators import InvalidWebsite, resolve_public, validate_url

MAX_BYTES = 1_000_000
MAX_CHARS = 24_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10


class FetchError(Exception):
    pass


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip):
        super().__init__(host, port, timeout=TIMEOUT_SECONDS)
        self.ip = ip

    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, ip):
        super().__init__(host, port, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        raw = socket.create_connection((self.ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


@dataclass
class ExtractedPage:
    final_url: str
    title: str
    description: str
    text: str
    truncated: bool


def _fetch_once(url: str):
    parts, host, port = validate_url(url)
    ips = resolve_public(host, port)
    # Connect directly to the checked address, never through environment proxies or a second DNS lookup.
    cls = PinnedHTTPSConnection if parts.scheme.lower() == 'https' else PinnedHTTPConnection
    conn = cls(host, port, ips[0])
    try:
        path = urlunsplit(('', '', parts.path or '/', parts.query, ''))
        host_header = f'[{host}]' if ':' in host else host
        if parts.port is not None:
            host_header += f':{port}'
        conn.request('GET', path, headers={'Host': host_header, 'User-Agent': 'LinkAnalysisBot/1.0', 'Accept': 'text/html,application/xhtml+xml', 'Accept-Encoding': 'identity', 'Connection': 'close'})
        response = conn.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            location = response.getheader('Location')
            if not location:
                raise FetchError('Website redirect has no location.')
            return response.status, location, None
        if response.status >= 400:
            raise FetchError(f'Website returned HTTP {response.status}.')
        if response.status < 200 or response.status >= 300:
            raise FetchError(f'Unexpected website HTTP status {response.status}.')
        content_type = response.getheader('Content-Type', '').lower()
        if not any(content_type.startswith(x) for x in ('text/html', 'application/xhtml+xml')):
            raise FetchError('Website did not return HTML content.')
        if response.getheader('Content-Encoding', 'identity').lower() not in ('identity', ''):
            raise FetchError('Compressed website responses are not supported.')
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise FetchError('Website HTML exceeds the 1 MB limit.')
        charset = response.headers.get_content_charset() or 'utf-8'
        try:
            return response.status, None, raw.decode(charset, errors='replace')
        except LookupError:
            return response.status, None, raw.decode('utf-8', errors='replace')
    except (OSError, http.client.HTTPException, UnicodeError) as exc:
        raise FetchError('Could not safely fetch the website (network or TLS error).') from exc
    finally:
        conn.close()


def extract_website(url: str) -> ExtractedPage:
    current = url
    for n in range(MAX_REDIRECTS + 1):
        status, location, html = _fetch_once(current)
        if location is not None:
            if n == MAX_REDIRECTS:
                raise FetchError('Too many website redirects.')
            current = urljoin(current, location)
            continue
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.get_text(' ', strip=True)[:300] if soup.title else ''
        desc_tag = soup.find('meta', attrs={'name': re.compile(r'^description$', re.I)})
        desc = str(desc_tag.get('content', ''))[:500] if desc_tag else ''
        for tag in soup(['script', 'style', 'noscript', 'svg', 'canvas', 'iframe', 'nav', 'footer', 'header']):
            tag.decompose()
        lines = [re.sub(r'\s+', ' ', line).strip() for line in soup.get_text('\n').splitlines()]
        seen, unique = set(), []
        for line in lines:
            if line and line not in seen:
                seen.add(line)
                unique.append(line)
        content = '\n'.join(unique)
        if len(content) < 100:
            raise FetchError('Insufficient readable page content; this page may require JavaScript or block automated access.')
        return ExtractedPage(current, title, desc, content[:MAX_CHARS], len(content) > MAX_CHARS)
    raise FetchError('Too many redirects.')
