"""Single-page fetcher; DNS is validated and the connection is pinned to an approved IP."""
from dataclasses import dataclass
import json
import http.client
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup
from app.utils.validators import InvalidWebsite, resolve_public, validate_url

MAX_BYTES = 1_000_000
# Social pages often contain large client-side state; still enforce a strict bound.
MAX_SOCIAL_BYTES = 3_000_000
SOCIAL_HOSTS = {'instagram.com', 'www.instagram.com', 'youtube.com', 'www.youtube.com', 'm.youtube.com', 'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'facebook.com', 'www.facebook.com', 'm.facebook.com'}
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
    source_kind: str = 'website'


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
        byte_limit = MAX_SOCIAL_BYTES if host.lower() in SOCIAL_HOSTS else MAX_BYTES
        raw = response.read(byte_limit + 1)
        if len(raw) > byte_limit:
            raise FetchError(f'Website HTML exceeds the {byte_limit // 1_000_000} MB limit.')
        charset = response.headers.get_content_charset() or 'utf-8'
        try:
            return response.status, None, raw.decode(charset, errors='replace')
        except LookupError:
            return response.status, None, raw.decode('utf-8', errors='replace')
    except (OSError, http.client.HTTPException, UnicodeError) as exc:
        raise FetchError('Could not safely fetch the website (network or TLS error).') from exc
    finally:
        conn.close()


def _instagram_profile_name(url: str):
    """Recognize only individual profile URLs on exact Instagram hostnames."""
    parts, host, _ = validate_url(url)
    if host.lower() not in {'instagram.com', 'www.instagram.com'}:
        return None
    path = parts.path.strip('/')
    if not re.fullmatch(r'[A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?', path) or '..' in path:
        return None
    reserved = {'accounts', 'about', 'developer', 'developers', 'direct', 'explore',
                'p', 'reel', 'reels', 'stories', 'tv', 'web', 'legal', 'api'}
    return None if path.lower() in reserved else path


def _instagram_embed(username: str):
    """Extract only public profile-embed data, without cookies or authentication.

    Instagram may block requests, remove embeds, or change its undocumented JSON.
    We never follow embed redirects to login pages or unrelated domains.
    """
    embed_url = f'https://www.instagram.com/{username}/embed/'
    try:
        _, location, html = _fetch_once(embed_url)
    except FetchError:
        return None
    if location is not None or not html:
        return None
    # The public embed may contain a JSON-encoded contextJSON string.
    # Parse as JSON only; never evaluate JavaScript or fetch URLs in the document.
    for match in re.finditer(r'"contextJSON"\s*:\s*', html):
        try:
            encoded, _ = json.JSONDecoder().raw_decode(html, match.end())
            if not isinstance(encoded, str):
                continue
            obj = json.loads(encoded)
            context = obj.get('context', {})
            if not isinstance(context, dict) or str(context.get('username', '')).lower() != username.lower():
                continue
            name = context.get('full_name')
            if not isinstance(name, str) or not name.strip():
                name = username
            captions = []
            truncated = False
            media = context.get('graphql_media', [])
            if not isinstance(media, list):
                media = []
            for entry in media[:12]:
                if not isinstance(entry, dict):
                    continue
                post = entry.get('shortcode_media') or {}
                if not isinstance(post, dict):
                    continue
                owner = post.get('owner') or {}
                if not isinstance(owner, dict) or str(owner.get('username', '')).lower() != username.lower():
                    continue
                edges = (post.get('edge_media_to_caption') or {}).get('edges') or []
                if not isinstance(edges, list):
                    continue
                for edge in edges[:1]:
                    if not isinstance(edge, dict):
                        continue
                    node = edge.get('node') or {}
                    caption = node.get('text') if isinstance(node, dict) else None
                    if isinstance(caption, str) and caption.strip():
                        if len(caption) > 2000:
                            truncated = True
                        captions.append(caption.strip()[:2000])
            if not captions:
                continue  # A handle alone does not support business analysis.
            text = ('Instagram public profile: ' + name.strip() + ' (@' + username + ')\n'
                    + 'The following text consists of public post captions; posts may promote third parties.\n\n'
                    + '\n\n'.join('Post caption: ' + item for item in captions))
            if len(text) < 100:
                continue
            truncated = truncated or len(text) > MAX_CHARS
            return ExtractedPage(embed_url, name.strip()[:300], '', text[:MAX_CHARS], truncated,
                                 source_kind='instagram_public_embed')
        except (ValueError, TypeError, AttributeError):
            continue
    return None


def extract_website(url: str) -> ExtractedPage:
    username = _instagram_profile_name(url)
    if username:
        embedded = _instagram_embed(username)
        if embedded:
            return embedded
    current = url
    for n in range(MAX_REDIRECTS + 1):
        status, location, html = _fetch_once(current)
        if location is not None:
            if n == MAX_REDIRECTS:
                raise FetchError('Too many website redirects.')
            destination = urljoin(current, location)
            # A login wall is not evidence about the requested Instagram profile.
            parts = urlsplit(destination)
            if username and (parts.hostname or '').lower() in {'instagram.com', 'www.instagram.com'} and parts.path.startswith('/accounts/login'):
                raise FetchError('Instagram profile data is unavailable. Its public embed was inaccessible or had no usable captions; login pages cannot be analyzed.')
            current = destination
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
        host = (urlsplit(current).hostname or '').lower()
        # YouTube's visible shell is often just navigation; favor actual channel metadata.
        youtube_shell = host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'} and 'how youtube works' in content.lower()
        if len(content) < 100 or youtube_shell:
            # Social metadata can provide limited real evidence without rendering JS.
            # Exclude generic YouTube boilerplate and never imply it is a full profile.
            generic = ('enjoy the videos and music you love', 'log in or sign up', 'see photos and videos from')
            useful = title and len(desc.strip()) >= 40 and not any(x in desc.lower() for x in generic)
            if host in SOCIAL_HOSTS and useful:
                source = f'Page title: {title}\nPage description: {desc}'
                return ExtractedPage(current, title, desc, source, False, source_kind='social_metadata')
            raise FetchError('Insufficient readable page content; this page may require JavaScript or block automated access.')
        return ExtractedPage(current, title, desc, content[:MAX_CHARS], len(content) > MAX_CHARS)
    raise FetchError('Too many redirects.')
