from pathlib import Path

from django.utils.cache import patch_vary_headers


class PrivateAPIHeaders:
    """Keep authenticated records out of shared/browser response caches."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path == '/api' or request.path.startswith('/api/'):
            response['Cache-Control'] = 'private, no-store'
            patch_vary_headers(response, ['Cookie'])
        response.setdefault('X-Frame-Options', 'DENY')
        response.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        return response


def static_headers(headers, path, url):
    # Hashed assets can be cached; the entry document must pick up each release.
    if Path(path).name == 'index.html':
        headers['Cache-Control'] = 'no-cache'
