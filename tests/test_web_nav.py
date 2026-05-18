"""Flask web interface — landing navigation to every blueprint."""

from books import create_app
from books.interfaces.web.app import create_web_app


def _client():
    return create_web_app(create_app("sqlite://")).test_client()


def test_landing_links_to_every_blueprint_entry_point():
    body = _client().get("/").get_data(as_text=True)
    # Header nav (shared via base.html) reaches each blueprint's GET form.
    assert "/setup/parties" in body
    assert "/setup/accounts" in body
    assert "/invoicing/issue" in body
    assert "/reconciliation/import" in body


def test_landing_report_form_redirects_to_canonical_report_url():
    c = _client()
    resp = c.get(
        "/reports/reconciliation?account=Bank&period=2026-01",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Lands on the path-param report view, which renders even with no data.
    assert "Reconciliation — Bank 2026-01" in resp.get_data(as_text=True)
    assert resp.request.path == "/reports/reconciliation/Bank/2026-01"
