import logging
from django.dispatch import Signal, receiver
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from core.models import UsageTracker


# ======================
# 1) DEFINE SIGNALS
# ======================

receipt_uploaded = Signal()

# =========================
# 2) DEFINE RECEIVERS
# =========================

@receiver(receipt_uploaded)
def handle_receipt_uploaded(sender, user, receipt_id, **kwargs):
    """
    This receiver increments the daily usage counter for free users
    when they successfully upload a receipt.
    """
    # Validate that we have a valid user
    if not user:
        logger = logging.getLogger(__name__)
        logger.warning(f"Receipt uploaded signal received with None user for receipt {receipt_id}")
        return
    
    # Try to send websocket notification, but don't let errors prevent usage tracking
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user.id}",
            {
                "type": "new_receipt_notification",
                "receipt_id": receipt_id,
            }
        )
    except Exception as e:
        # Log the error but continue with usage tracking
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to send websocket notification for receipt {receipt_id}: {e}")
    
    # Always update usage tracking regardless of websocket success/failure
    today = timezone.now().date()
    with transaction.atomic():
        usage_record, _created = UsageTracker.objects.select_for_update().get_or_create(
            user=user,
            usage_type=UsageTracker.RECEIPT_UPLOAD,  # e.g. 'receipt_upload'
            date=today
        )
        usage_record.count = F('count') + 1
        usage_record.save()

