from django.db.models import Sum
from core.models import UsageTracker
from django.utils import timezone
from rest_framework.permissions import BasePermission


class MonthlyReportLimit(BasePermission):
    """
    • Paid users: unlimited.
    • Free users: max **1** report download per calendar month.
    """
    message = "Free-tier limit reached (1 report download per month)."

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False

        if user.is_premium:
            return True

        today = timezone.now().date()
        month_start = today.replace(day=1)

        monthly_total = (
            UsageTracker.objects.filter(
                user=user,
                usage_type=UsageTracker.REPORT_DOWNLOAD,
                date__gte=month_start,
                date__lte=today,
            )
            .aggregate(total=Sum("count"))
            .get("total")
        ) or 0

        return monthly_total < 1
    
    