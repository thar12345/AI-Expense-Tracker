"""pytest suite for **email_mgmt**
==============================================================
Exercises all JSON endpoints under ``email_mgmt.urls``:

| Test fn                                 | Verb | Path                                | Purpose |
|-----------------------------------------|------|-------------------------------------|---------|
| test_email_webhook_success              | POST | /emails/create/                     | Happy-path SendGrid ingest |
| test_email_webhook_user_not_found       | POST | idem                                | 404 when squirll_id missing |
| test_email_webhook_missing_fields       | POST | idem                                | 400 validation guard |
| test_email_endpoints_require_auth       | GET  | /emails/, /emails/by-vendor/ …      | 401 on unauth |
| test_email_list_and_detail              | GET  | /emails/, /emails/<pk>/             | List contains created mail; detail OK |
| test_email_company_buckets              | GET  | /emails/by-vendor/                  | Grouping + counts |
| test_email_filter_by_category           | GET  | /emails/?category=marketing         | Category filter |
| test_email_filter_date_period           | GET  | /emails/?date_period=30d            | Preset date filter |
| test_email_filter_date_range            | GET  | /emails/?date_after&date_before     | Explicit range |
| test_email_ordering_created_at          | GET  | /emails/?ordering=created_at        | Asc / desc order |
| test_email_cross_user_isolation         | GET  | /emails/                            | Alice vs Bob data-leak check |
"""
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

from email_mgmt.models import Email

User = get_user_model()

API_PREFIX = "/email-mgmt/"                 # router mount


def _url(path: str) -> str:
    return f"{API_PREFIX}{path.lstrip('/')}"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _email_payload(*, to_addr: str, sender: str = "Store <sales@shop.com>",
                   subject: str = "Your receipt", html: str | None = None,
                   marketing: bool = False) -> Dict:
    """Build a minimal multipart payload accepted by /emails/create/."""
    html_part = html or "<p>Thanks for shopping!</p>"
    return {
        "to": to_addr,
        "from": sender,
        "subject": subject,
        "html": html_part,
        "text": "plain text body",
        "headers": "X-Test: 1",
        "attachments": "0",
    }


def _post_email(client: APIClient, to_addr: str, **overrides) -> int:
    """POST to the webhook and return new Email.pk."""
    payload = _email_payload(to_addr=to_addr, **overrides)
    res = client.post(reverse("email_mgmt:create-email"), payload, format="multipart")
    assert res.status_code == status.HTTP_201_CREATED
    return res.data["email_id"]


# --------------------------------------------------------------------------- #
# Fixtures – APIClient + authenticated “Alice”                               #
# --------------------------------------------------------------------------- #

@pytest.fixture()
def api_client() -> APIClient:
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
    res = api_client.post(reverse("signup"), user_payload, format="json")
    assert res.status_code in (200, 201)
    user = User.objects.get(email=user_payload["email"].lower())
    # squirll_id must match the webhook “to” field
    user.squirll_id = user.email
    user.save(update_fields=["squirll_id"])
    return res.data, user


@pytest.fixture()
def auth_client(api_client, signup):
    tokens, user = signup
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    api_client.handler._force_user = user
    return api_client


# --------------------------------------------------------------------------- #
# 1) Webhook upload                                                           #
# --------------------------------------------------------------------------- #

def test_email_webhook_success(api_client, signup):
    """Valid multipart payload → 201 + Email saved."""
    _, user = signup
    pk = _post_email(api_client, to_addr=user.squirll_id)
    assert Email.objects.filter(id=pk, user=user).exists()


def test_email_webhook_user_not_found(api_client):
    """Unknown squirll_id → 404."""
    res = api_client.post(
        reverse("email_mgmt:create-email"),
        _email_payload(to_addr="nosuch@domain.com"),
        format="multipart"
    )
    assert res.status_code == 404


def test_email_webhook_missing_fields(api_client, signup):
    """Missing 'from' or 'subject' → 400."""
    _, user = signup
    bad = _email_payload(to_addr=user.squirll_id)
    bad.pop("from")
    res = api_client.post(reverse("email_mgmt:create-email"), bad, format="multipart")
    assert res.status_code == 400


# --------------------------------------------------------------------------- #
# 2) Auth-guard for list endpoints                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", ["emails/", "emails/by-vendor/"])
def test_email_endpoints_require_auth(api_client, path):
    assert api_client.get(_url(path)).status_code == 401


# --------------------------------------------------------------------------- #
# 3) List + Detail                                                            #
# --------------------------------------------------------------------------- #
'''checks that once an e-mail is ingested by the webhook, an authenticated user can see it in the normal inbox list and open its detail view.'''
def test_email_list_and_detail(auth_client):
    user = auth_client.handler._force_user
    pk = _post_email(APIClient(), to_addr=user.squirll_id)  # webhook is unauth

    res = auth_client.get(_url("emails/"))
    results = res.data.get("results", res.data)
    assert any(e["id"] == pk for e in results)

    assert auth_client.get(_url(f"emails/{pk}/")).status_code == 200


# --------------------------------------------------------------------------- #
# 4) Company-bucket view                                                      #
# --------------------------------------------------------------------------- #
    """
    Verify /emails/by-vendor/ groups messages by the derived *company* field.

    Scenario
    --------
    • Ingest three emails for Alice via the webhook:
        - Two from Amazon (different senders → same company bucket)
        - One from eBay
    • Call GET /emails/by-vendor/
    • Expect exactly two buckets – “Amazon” and “eBay”.

    If the view mistakenly fails to aggregate by company (or leaks unrelated
    data), the set comparison below will fail.
    """
def test_email_company_buckets(auth_client):
    user = auth_client.handler._force_user
    _post_email(APIClient(), to_addr=user.squirll_id, sender="Amazon <noreply@amazon.com>")
    _post_email(APIClient(), to_addr=user.squirll_id, sender="Amazon <promo@amazon.com>")
    _post_email(APIClient(), to_addr=user.squirll_id, sender="eBay <sales@ebay.com>")

    res = auth_client.get(_url("emails/by-vendor/"))
    assert res.status_code == 200
    companies = {b["company"] for b in res.data}
    assert companies == {"Amazon", "eBay"}


# --------------------------------------------------------------------------- #
# 5) Filters                                                                  #
# --------------------------------------------------------------------------- #

def test_email_filter_by_category(auth_client):
    user = auth_client.handler._force_user
    _post_email(APIClient(), to_addr=user.squirll_id, subject="SALE 50% off")       # likely marketing
    _post_email(APIClient(), to_addr=user.squirll_id, subject="Your order receipt") # message

    res = auth_client.get(_url("emails/?category=marketing"))
    assert res.status_code == 200
    results = res.data.get("results", res.data)
    assert all(e["category"] == Email.MARKETING for e in results)


def test_email_filter_date_period(auth_client):
    user = auth_client.handler._force_user
    old_pk = _post_email(APIClient(), to_addr=user.squirll_id, subject="Old mail")
    Email.objects.filter(id=old_pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )
    _post_email(APIClient(), to_addr=user.squirll_id, subject="New mail")

    res = auth_client.get(_url("emails/?date_period=30d"))
    results = res.data.get("results", res.data)
    ids = {e["id"] for e in results}
    assert old_pk not in ids


def test_email_filter_date_range(auth_client):
    user = auth_client.handler._force_user
    _post_email(APIClient(), to_addr=user.squirll_id, subject="2023-01",
                html="<p>d</p>")
    mid_pk = _post_email(APIClient(), to_addr=user.squirll_id, subject="2023-06")
    _post_email(APIClient(), to_addr=user.squirll_id, subject="2023-12")

    Email.objects.filter(id__in=[mid_pk]).update(
        created_at=date(2023, 6, 1)
    )

    res = auth_client.get(_url("emails/?date_after=2023-05-01&date_before=2023-07-01"))
    results = res.data.get("results", res.data)
    assert {e["id"] for e in results} == {mid_pk}


# --------------------------------------------------------------------------- #
# 6) Ordering                                                                 #
# --------------------------------------------------------------------------- #

def test_email_ordering_created_at(auth_client):
    user = auth_client.handler._force_user
    pk_old = _post_email(APIClient(), to_addr=user.squirll_id, subject="Old")
    Email.objects.filter(id=pk_old).update(
        created_at=timezone.now() - timedelta(days=1)
    )
    pk_new = _post_email(APIClient(), to_addr=user.squirll_id, subject="New")

    asc  = auth_client.get(_url("emails/?ordering=created_at")).data["results"]
    desc = auth_client.get(_url("emails/?ordering=-created_at")).data["results"]

    assert asc[0]["id"] == pk_old
    assert desc[0]["id"] == pk_new


# --------------------------------------------------------------------------- #
# 7) Cross-user isolation                                                     #
# --------------------------------------------------------------------------- #

def test_email_cross_user_isolation(auth_client, user_payload):
    alice = auth_client.handler._force_user
    pk = _post_email(APIClient(), to_addr=alice.squirll_id)

    # Bob
    bob_client = APIClient()
    bob_payload = {**user_payload, "email": "bob@example.com"}
    res = bob_client.post(reverse("signup"), bob_payload, format="json")
    bob_user = User.objects.get(email="bob@example.com")
    bob_user.squirll_id = bob_user.email
    bob_user.save(update_fields=["squirll_id"])
    bob_tokens = res.data
    bob_client.credentials(HTTP_AUTHORIZATION=f"Bearer {bob_tokens['access_token']}")

    # Bob should not see Alice’s email
    res = bob_client.get(_url("emails/"))
    assert all(e["id"] != pk for e in res.data.get("results", res.data))
    assert bob_client.get(_url(f"emails/{pk}/")).status_code == 404
