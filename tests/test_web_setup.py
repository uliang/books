"""Flask web interface — setup blueprint (parties, accounts)."""

from books import create_app
from books.interfaces.web.app import create_web_app


def _client():
    return create_web_app(create_app("sqlite://")).test_client()


def test_register_party_then_it_shows_on_landing():
    c = _client()
    resp = c.post(
        "/setup/parties",
        data={"name": "Acme", "role": "customer"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Acme" in resp.get_data(as_text=True)


def test_create_account_then_it_shows_on_landing():
    c = _client()
    resp = c.post(
        "/setup/accounts",
        data={"code": "Bank", "name": "Bank", "type": "asset"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bank" in body
