"""Party (generic) — master data, referenced elsewhere by PartyId.

Customer/supplier/contractor are roles on a Party (CONTEXT).
"""

from books.party.service import PartyService
from books.platform.db import Database


def test_registered_party_is_retrievable_by_id():
    party = PartyService(Database())

    acme = party.register_party(name="Acme", role="customer")

    assert acme.id is not None
    assert acme.name == "Acme"
    assert party.get(acme.id).name == "Acme"


def test_list_returns_all_registered_parties_in_insertion_order():
    from books.party.service import PartyService
    from books.platform.db import Database

    svc = PartyService(Database("sqlite://"))

    assert svc.list() == []

    a = svc.register_party(name="Acme", role="customer")
    b = svc.register_party(name="Beta", role="supplier")

    parties = svc.list()
    assert [p.id for p in parties] == [a.id, b.id]
    assert [p.name for p in parties] == ["Acme", "Beta"]
    assert [p.role for p in parties] == ["customer", "supplier"]
