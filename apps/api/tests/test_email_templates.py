"""Tests for utils/email.py template rendering — specifically that
user-controlled values (full_name, server-built links) are HTML-escaped
before being interpolated into the email body, since they're inserted into
raw HTML strings rather than rendered through a templating engine that
escapes by default."""
from unittest.mock import patch

from utils.email import send_password_reset_email, send_welcome_email


def _sent_html(mock_post) -> str:
    return mock_post.call_args.kwargs["json"]["html"]


def test_welcome_email_escapes_html_in_full_name():
    crafted_name = '<img src=x onerror=alert(1)>'
    with patch("utils.email.requests.post") as mock_post:
        mock_post.return_value.ok = True
        send_welcome_email("user@example.com", crafted_name)

    html_body = _sent_html(mock_post)
    assert "<img src=x onerror=alert(1)>" not in html_body
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_body


def test_password_reset_email_escapes_reset_link():
    crafted_link = 'https://example.com/reset?token="><script>alert(1)</script>'
    with patch("utils.email.requests.post") as mock_post:
        mock_post.return_value.ok = True
        send_password_reset_email("user@example.com", crafted_link)

    html_body = _sent_html(mock_post)
    assert "<script>alert(1)</script>" not in html_body
    assert "&lt;script&gt;" in html_body
