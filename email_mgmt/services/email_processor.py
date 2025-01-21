import logging
import re
from email import message_from_string
from email.utils import parseaddr
from typing import Any, Dict
import tldextract

from ..models import Email
from ..serializers import EmailSerializer
from ..signals import email_received

logger = logging.getLogger(__name__)

# Regex patterns
RE_PROMO_HEADER = re.compile(r"list-(unsubscribe|id)", re.I)
RE_PROMO_SUBJECT = re.compile(
    r"(newsletter|coupon|% off|special offer|clearance|deal(?:s)?|sale\s+ends)", re.I
)
RE_TRANSACTIONAL = re.compile(
    r"(invoice|receipt|order|shipped|paid|payment|booking|ticket|statement)",
    re.I,
)

ESP_FPS = ("mailchimp", "constantcontact", "klaviyo")

# ── Promo / transactional decision ───────────────────────────────
def is_marketing(raw_headers: str, subject: str) -> bool:
    """
    Returns True for marketing / promotions.
    Strategy:
      1.  If List-Unsubscribe or List-ID → promo.
      2.  If X-Mailer shows known ESP → promo.
      3.  Strong promo keywords in subject or first line of body → promo
          UNLESS transactional keywords also present.
    """

    # normalise literal \r\n for parser
    hdrs = raw_headers.replace("\\r\\n", "\r\n")
    try:
        msg = message_from_string(hdrs)
    except Exception:
        msg = {}

    # 1) Explicit bulk headers
    if any(h in msg for h in ("list-unsubscribe", "list-id")):
        return True

    # 2) ESP fingerprint
    x_mailer = msg.get("x-mailer", "").lower()
    if any(fp in x_mailer for fp in ESP_FPS):
        return True

    # 3) Keyword heuristics
    subj_is_promo = bool(RE_PROMO_SUBJECT.search(subject or ""))
    subj_is_txn   = bool(RE_TRANSACTIONAL.search(subject or ""))

    if subj_is_promo and not subj_is_txn:
        return True

    return False


# ── Company extractor ────────────────────────────────────────────
def company_from_fromhdr(from_hdr: str) -> str:
    display, addr = parseaddr(from_hdr)
    if display:
        return display[:255]
    return tldextract.extract(addr).domain or "Miscellaneous"
