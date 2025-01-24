from django.dispatch import Signal, receiver
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from core.models import UsageTracker

report_downloaded = Signal()

@receiver(report_downloaded)
def handle_report_downloaded(sender, user, **kwargs):
    """
    Increments the daily REPORT_DOWNLOAD counter.
    """
    # --- usage tracking ---
    today = timezone.now().date()
    with transaction.atomic():
        usage, _created = UsageTracker.objects.select_for_update().get_or_create(
            user=user,
            usage_type=UsageTracker.REPORT_DOWNLOAD,
            date=today,
        )
        usage.count = F("count") + 1
        usage.save()
