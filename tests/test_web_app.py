"""Flask web interface — landing page skeleton (Task 1)."""

from books import create_app
from books.interfaces.web.app import create_web_app


def _client():
    return create_web_app(create_app("sqlite://")).test_client()


def test_landing_page_renders_and_lists_empty_state():
    resp = _client().get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "books" in body
    assert "No parties yet" in body
    assert "No accounts yet" in body
