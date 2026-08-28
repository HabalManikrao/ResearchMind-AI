import pytest

from app.security.net import UnsafeURLError, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com",
        "https://api.github.com/search",
        "https://export.arxiv.org/api/query",
    ],
)
def test_public_urls_allowed(url):
    validate_url(url)  # should not raise


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.1/x",
        "http://10.0.0.5",
        "http://192.168.1.1",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://[::1]/",
    ],
)
def test_unsafe_urls_blocked(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_missing_host_blocked():
    with pytest.raises(UnsafeURLError):
        validate_url("http:///nohost")
