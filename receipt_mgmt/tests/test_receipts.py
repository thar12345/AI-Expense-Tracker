from __future__ import annotations

from datetime import date, timedelta
from typing import Dict

import pytest
pytestmark = pytest.mark.django_db

from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from receipt_mgmt.models import Item, Receipt, Tag

User = get_user_model()

API_PREFIX = "/receipt-mgmt/"  # update if your router path changes


def _url(path: str) -> str:
    """Prepend the app prefix so we can hit unnamed paths."""
    return f"{API_PREFIX}{path.lstrip('/')}"

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _manual_payload(*, company: str, tx_date: date,
                    items: list[Dict] | None = None) -> Dict:
    """Return a *valid* JSON body accepted by /receipt/upload/manual/."""
    if items is None:
        items = [{"description": "Autogen item",
                  "price": "10.00", "total_price": "10.00"}]
    return {
        "company": company,
        "address": "123 Main St",
        "date": tx_date.isoformat(),
        "time": "12:00:00",
        "sub_total": "10.00",
        "tax": "1.30",
        "total": "11.30",
        "tip": "0.00",
        "receipt_type": Receipt.ReceiptType.GROCERIES,
        "item_count": len(items),
        "items": items,
        "receipt_currency_symbol": "$",
        "receipt_currency_code": "CAD",
    }


def _post_manual(client: APIClient, **kwargs) -> int:
    """POST to */receipt/upload/manual/* and return the created PK."""
    res = client.post(reverse("receipt-upload-manual"),
                      _manual_payload(**kwargs),
                      format="json")
    assert res.status_code == status.HTTP_201_CREATED
    # Endpoint wraps the serializer under "receipt"
    return res.data["receipt"]["id"]

# ---------------------------------------------------------------------------
# Fixtures – APIClient + authenticated user (Alice)
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client() -> APIClient:
    """Bare DRF client (no auth headers)."""
    return APIClient()


@pytest.fixture()
def user_payload():
    return {
        "email": "alice@example.com",
        "password": "StrongPassw0rd!",
        "first_name": "Alice",
        "last_name": "Doe",
    }


@pytest.fixture()
def signup(api_client, user_payload):
    """Hit `/signup/` to create Alice, returning (tokens, ORM user)."""
    res = api_client.post(reverse("signup"), user_payload, format="json")
    assert res.status_code in (200, 201)
    return res.data, User.objects.get(email=user_payload["email"].lower())


@pytest.fixture()
def auth_client(api_client, signup):
    """`APIClient` pre‑loaded with Alice's Bearer token."""
    tokens, user = signup
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    api_client.handler._force_user = user  # convenience for tests
    return api_client

# ---------------------------------------------------------------------------
# 1) /receipt/upload/manual/ – creation + auth guard
# ---------------------------------------------------------------------------

def test_upload_manual_receipt(auth_client):
    """Ensure a valid payload stores a `Receipt` for Alice (201)."""
    rcpt_id = _post_manual(auth_client, company="Walmart", tx_date=date.today())
    assert Receipt.objects.filter(id=rcpt_id).exists()


def test_upload_manual_requires_auth(api_client):
    """Unauthenticated POST should return **401 Unauthorized**."""
    res = api_client.post(reverse("receipt-upload-manual"),
                          _manual_payload(company="Fail", tx_date=date.today()),
                          format="json")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

# ---------------------------------------------------------------------------
# 2) /receipts/ & /receipts/<pk>/ – pagination, detail, delete
# ---------------------------------------------------------------------------

def test_receipt_list_detail_delete(auth_client):
    """Create one receipt, confirm list > detail > delete cycle works."""
    rcpt_id = _post_manual(auth_client, company="Target", tx_date=date.today())

    # List endpoint may be paginated; adapt accordingly
    res_list = auth_client.get(_url("receipts/"))
    results  = res_list.data.get("results", res_list.data)
    assert any(r["id"] == rcpt_id for r in results)

    # Detail endpoint
    assert auth_client.get(_url(f"receipts/{rcpt_id}/")).status_code == 200

    # Delete + verify 404 afterwards
    assert auth_client.delete(_url(f"receipts/{rcpt_id}/")).status_code == 204
    assert auth_client.get(_url(f"receipts/{rcpt_id}/")).status_code == 404

# ---------------------------------------------------------------------------
# 3) /receipts/by-vendor/ – vendor bucketing
# ---------------------------------------------------------------------------

def test_receipt_by_vendor_grouping(auth_client):
    """Two Alpha + one Omega => 2 buckets with preview lists."""
    for comp in ("Alpha", "Alpha", "Omega"):
        _post_manual(auth_client, company=comp, tx_date=date.today())

    res = auth_client.get(_url("receipts/by-vendor/"))
    assert res.status_code == 200
    by_company = {b["company"]: b for b in res.data}
    assert by_company["Alpha"]["receipts"] and by_company["Omega"]["receipts"]

# ---------------------------------------------------------------------------
# 4) /receipts/search/ – split smart search (companies vs. items)
# ---------------------------------------------------------------------------

def test_receipt_smart_search_company_bucket(auth_client):
    """Alpha in company name should surface under 'companies' bucket."""
    _post_manual(auth_client, company="Alpha Foods", tx_date=date.today())
    _post_manual(auth_client,
                 company="Beta",
                 tx_date=date.today(),
                 items=[{"description": "Banana chips", "price": "2.00", "total_price": "2.00"}])

    res = auth_client.get(reverse("receipt-smart-search") + "?search=Alpha")
    assert res.status_code == 200
    assert any(b["company"].startswith("Alpha") for b in res.data["companies"])

# ---------------------------------------------------------------------------
# 5) /receipts/ – ?date_period=30d filter
# ---------------------------------------------------------------------------

def test_receipt_list_date_period_filter(auth_client):
    """OldCo created 31 days ago should be filtered out by 30d preset."""
    old_id = _post_manual(auth_client, company="OldCo",
                          tx_date=date.today() - timedelta(days=31))
    _post_manual(auth_client, company="NewCo", tx_date=date.today())

    # Back‑date created_at so the filter has something to exclude
    Receipt.objects.filter(id=old_id).update(
        created_at=timezone.now() - timedelta(days=31)
    )

    res = auth_client.get(_url("receipts/?date_period=30d"))
    assert res.status_code == 200
    results   = res.data if isinstance(res.data, list) else res.data["results"]
    companies = {r["company"] for r in results}
    assert "NewCo" in companies and "OldCo" not in companies

# ---------------------------------------------------------------------------
# 6) Cross-user isolation
# ---------------------------------------------------------------------------
def test_receipts_are_user_scoped(auth_client, user_payload):
    """
    • Alice uploads a receipt  
    • Bob signs up with a *separate* client and must NOT see Alice's data  
    • Bob's direct GET/DELETE on Alice's PK must 404
    """
    # -- Alice (auth_client) creates a private receipt -----------------------
    alice_id = _post_manual(auth_client,
                            company="Secret",
                            tx_date=date.today())

    # -- Bob uses a brand-new client ----------------------------------------
    bob_client = APIClient()
    bob_payload = {**user_payload, "email": "bob@example.com"}
    res = bob_client.post(reverse("signup"), bob_payload, format="json")
    bob_tokens = res.data
    bob_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {bob_tokens['access_token']}"
    )

    # Bob's /receipts/ list should be empty (or at least not contain Alice's)
    res = bob_client.get(_url("receipts/"))
    results = res.data.get("results", res.data)
    assert all(r["id"] != alice_id for r in results)

    # Bob cannot access Alice's detail or delete it
    assert bob_client.get(_url(f"receipts/{alice_id}/")).status_code == 404
    assert bob_client.delete(_url(f"receipts/{alice_id}/")).status_code == 404

# ---------------------------------------------------------------------------
# 7) Validation errors - Manual Entry
# ---------------------------------------------------------------------------
def test_manual_upload_validation_error(auth_client):
    """
    When a required field is missing (blank company name),
    the serializer should reject the payload and /receipt/upload/manual/
    must respond with **HTTP 400 Bad Request** plus a helpful error message.
    """
    bad = _manual_payload(company="", tx_date=date.today())  # blank company
    res = auth_client.post(reverse("receipt-upload-manual"), bad, format="json")
    assert res.status_code == 400
    assert "company" in res.data["error"]  # serializer message surfaces

# ---------------------------------------------------------------------------
# 8) Filter by category
# ---------------------------------------------------------------------------

def test_receipt_filter_by_category(auth_client):
    """
    Upload two receipts with different categories (Groceries vs Dining Out) and make sure
    the ?category=Dining Out query returns only the Dining Out receipt.
    """
    # Groceries receipt
    _post_manual(
        auth_client,
        company="GroceryCo",
        tx_date=date.today(),
        items=[{"description": "Bread", "price": "2", "total_price": "2"}],
    )  # default receipt_type = Groceries

    # Dining Out receipt
    payload = _manual_payload(
        company="RestCo",
        tx_date=date.today(),
        items=[{"description": "Burger", "price": "5", "total_price": "5"}],
    )
    payload["receipt_type"] = 3  # 3 = Dining Out (integer value)
    res = auth_client.post(reverse("receipt-upload-manual"), payload, format="json")
    assert res.status_code == 201

    # Hit the endpoint with category alias - test both string and integer filtering
    res = auth_client.get(_url("receipts/?category=Dining Out"))  # String name
    assert res.status_code == 200

    results   = res.data if isinstance(res.data, list) else res.data["results"]
    companies = {r["company"] for r in results}

    assert companies == {"RestCo"}
    
    # Also test integer filtering
    res = auth_client.get(_url("receipts/?category=3"))  # Integer ID
    assert res.status_code == 200

    results   = res.data if isinstance(res.data, list) else res.data["results"]
    companies = {r["company"] for r in results}

    assert companies == {"RestCo"}

# ---------------------------------------------------------------------------
# 9) Filter by tags
# ---------------------------------------------------------------------------

def test_receipt_filter_by_tags(auth_client):
    """
    Attach a tag to one receipt and ensure ?tags=<id> returns only that receipt.
    """
    r1 = _post_manual(auth_client, company="TagMe", tx_date=date.today())
    r2 = _post_manual(auth_client, company="SkipMe", tx_date=date.today())

    # Add tag to r1 only
    tag_id = _add_tag(auth_client, r1, "Focus")
    res = auth_client.get(_url(f"receipts/?tags={tag_id}"))
    assert res.status_code == 200

    results = res.data.get("results", res.data)
    ids     = {r["id"] for r in results}
    assert ids == {r1}                 # r2 excluded


# ---------------------------------------------------------------------------
# 10) Tag endpoints – add → list → edit → remove → delete
# ---------------------------------------------------------------------------

def _create_tag(client: APIClient, receipt_id: int, name: str = "Groceries") -> int:
    """Helper: POST /tag/add/ and return the new Tag's PK."""
    res = client.post(reverse("tag-add"),
                      {"receipt_id": receipt_id, "name": name},
                      format="json")
    assert res.status_code == 200
    return res.data["tag"]["id"]          # response embeds TagSerializer

def test_tag_crud_lifecycle(auth_client):
    """
    • Add a new tag to a receipt  
    • Confirm /tag/listall/ returns it  
    • PATCH its name via /tag/edit-name/  
    • Remove it from the receipt via /tag/remove/  
    • Verify the tag was auto-deleted since it became orphaned
    """
    # --- 1) create a receipt Alice can tag ---------------------------------
    rcpt_id = _post_manual(auth_client, company="TagCorp", tx_date=date.today())

    # --- 2) ADD tag --------------------------------------------------------
    tag_id = _create_tag(auth_client, receipt_id=rcpt_id, name="Groceries")

    # --- 3) LISTALL should show exactly one tag ---------------------------
    res = auth_client.get(reverse("tag-listall"))
    assert res.status_code == 200 and len(res.data) == 1
    assert res.data[0]["name"] == "Groceries"

    # --- 4) EDIT tag name --------------------------------------------------
    res = auth_client.patch(reverse("tag-edit-name"),
                            {"tag_id": tag_id, "name": "Food"},
                            format="json")
    assert res.status_code == 200

    # verify new name shows up
    res = auth_client.get(reverse("tag-listall"))
    assert any(t["name"] == "Food" for t in res.data)

    # --- 5) REMOVE tag from receipt ---------------------------------------
    res = auth_client.post(reverse("tag-remove"),
                           {"receipt_id": rcpt_id, "tag_id": tag_id},
                           format="json")
    assert res.status_code == 200
    # receipt now has zero tags
    assert not Receipt.objects.get(id=rcpt_id).tags.exists()
    
    # Verify the tag was auto-deleted (tag_deleted should be True in response)
    assert res.data.get("tag_deleted") == True

    # --- 6) VERIFY tag was automatically deleted --------------------------
    # listall should now be empty since the orphaned tag was auto-deleted
    res = auth_client.get(reverse("tag-listall"))
    assert res.data == []
    
    # Manual delete should return 404 since tag is already gone
    res = auth_client.delete(reverse("tag-delete", args=[tag_id]))
    assert res.status_code == 404

# ---------------------------------------------------------------------------
# 11) Tag edge-cases (auth, validation, conflicts, isolation)
# ---------------------------------------------------------------------------

# ――― helpers ―――----------------------------------------------------------------
def _add_tag(client: APIClient, receipt_id: int, name: str = "Travel") -> int:
    res = client.post(reverse("tag-add"),
                      {"receipt_id": receipt_id, "name": name},
                      format="json")
    assert res.status_code == 200
    return res.data["tag"]["id"]

# 11-A  Auth guard ----------------------------------------------------------------
@pytest.mark.parametrize(
    "method, url_name, kwargs",
    [
        ("get",    "tag-listall",     {}),
        ("post",   "tag-add",         {"json": {"receipt_id": 1, "name": "X"}}),
        ("post",   "tag-remove",      {"json": {"receipt_id": 1, "tag_id": 1}}),
        ("patch",  "tag-edit-name",   {"json": {"tag_id": 1, "name": "Y"}}),
        ("delete", "tag-delete",      {"args": [1]}),
    ],
)
def test_tag_endpoints_require_auth(api_client, method, url_name, kwargs):
    """Every tag endpoint must reject unauthenticated requests with 401."""
    url = reverse(url_name, args=kwargs.get("args", []))
    func = getattr(api_client, method)
    res  = func(url, kwargs.get("json", {}), format="json")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

# 11-B  Missing-field validation ---------------------------------------------------
def test_tag_add_missing_fields(auth_client):
    """POST /tag/add/ without `name` or `receipt_id` → 400."""
    rcpt = _post_manual(auth_client, company="Tagless", tx_date=date.today())
    res1 = auth_client.post(reverse("tag-add"), {"receipt_id": rcpt}, format="json")
    res2 = auth_client.post(reverse("tag-add"), {"name": "X"}, format="json")
    assert res1.status_code == res2.status_code == 400

# 11-C  Duplicate-name conflict on edit -------------------------------------------
def test_tag_edit_name_duplicate_conflict(auth_client):
    """Renaming to an existing tag owned by the same user should 409."""
    rcpt = _post_manual(auth_client, company="Dup", tx_date=date.today())
    t1   = _add_tag(auth_client, rcpt, "Food")
    _add_tag(auth_client, rcpt, "Travel")
    res = auth_client.patch(reverse("tag-edit-name"),
                            {"tag_id": t1, "name": "Travel"},
                            format="json")
    assert res.status_code == status.HTTP_409_CONFLICT

# 11-D  Remove tag not on receipt --------------------------------------------------
def test_tag_remove_not_associated(auth_client):
    """Removing a tag that isn't linked to the receipt should 400."""
    rcpt1 = _post_manual(auth_client, company="R1", tx_date=date.today())
    rcpt2 = _post_manual(auth_client, company="R2", tx_date=date.today())
    tag_id = _add_tag(auth_client, rcpt1, "Loose")
    res = auth_client.post(reverse("tag-remove"),
                           {"receipt_id": rcpt2, "tag_id": tag_id},
                           format="json")
    assert res.status_code == 400  # not associated

# 11-E  Cross-user isolation for tag ops ------------------------------------------
def test_tag_cross_user_isolation_on_delete(auth_client, user_payload):
    """
    Bob should NOT be able to delete Alice's tag even if he knows the ID.
    """
    # Alice
    rcpt = _post_manual(auth_client, company="AliceInc", tx_date=date.today())
    tag_id = _add_tag(auth_client, rcpt, "Secret")

    # Bob
    bob_client = APIClient()
    bob_payload = {**user_payload, "email": "bob2@example.com"}
    bob_tokens = bob_client.post(reverse("signup"), bob_payload, format="json").data
    bob_client.credentials(HTTP_AUTHORIZATION=f"Bearer {bob_tokens['access_token']}")

    res = bob_client.delete(reverse("tag-delete", args=[tag_id]))
    assert res.status_code == 404  # tag not found for Bob

# 11-F  Adding same tag to another receipt reuses existing Tag row -----------------
def test_tag_add_reuses_existing(auth_client):
    """
    Adding 'Travel' to two receipts should create exactly ONE Tag row (M2M reused).
    """
    r1 = _post_manual(auth_client, company="R1", tx_date=date.today())
    r2 = _post_manual(auth_client, company="R2", tx_date=date.today())
    _add_tag(auth_client, r1, "Travel")
    _add_tag(auth_client, r2, "Travel")          # should reuse

    from receipt_mgmt.models import Tag
    assert Tag.objects.filter(user=auth_client.handler._force_user,
                              name="Travel").count() == 1
