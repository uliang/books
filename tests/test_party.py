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
