"""
Email Management Filters

This module provides filtering capabilities for the Email model,
allowing API clients to filter emails by date, category, company,
and predefined time periods.
"""

import django_filters as df
from django.utils import timezone
from .models import Email

class EmailFilter(df.FilterSet):
    """
    FilterSet for the Email model that provides various filtering options.
    
    Supported filters:
        - date_after: Filter emails after a specific date
        - date_before: Filter emails before a specific date
        - category: Filter by email category (marketing/message)
        - company: Filter by company name
        - date_period: Quick filter for common time periods (7d, 30d, 3m)
    
    Example usage:
        GET /api/emails/?date_period=7d
        GET /api/emails/?category=marketing&company=Amazon
        GET /api/emails/?date_after=2024-01-01
    """
    
    # Date range filters
    date_after = df.DateFilter(
        field_name="created_at",
        lookup_expr="gte",
        help_text="Filter emails created on or after this date"
    )
    date_before = df.DateFilter(
        field_name="created_at",
        lookup_expr="lte",
        help_text="Filter emails created on or before this date"
    )
    
    # Category and company filters
    category = df.CharFilter(
        field_name="category",
        lookup_expr="iexact",
        help_text="Filter by email category (marketing/message)"
    )
    company = df.CharFilter(
        field_name="company",
        lookup_expr="iexact",
        help_text="Filter by company name"
    )

    # Quick period presets
    date_period = df.CharFilter(
        method="filter_period",
        help_text="Quick filter for time periods: 7d (7 days), 30d (30 days), 3m (3 months)"
    )

    def filter_period(self, qs, name, value):
        """
        Custom filter method for predefined time periods.
        
        Args:
            qs: The base queryset
            name: The filter field name
            value: The period value (7d, 30d, or 3m)
            
        Returns:
            Filtered queryset for the specified time period
        """
        days_map = {
            "7d": 7,    # Last 7 days
            "30d": 30,  # Last 30 days
            "3m": 90    # Last 3 months
        }
        days = days_map.get(value)
        return qs.filter(created_at__gte=timezone.now()-timezone.timedelta(days=days)) if days else qs

    class Meta:
        model = Email
        fields = []  # Base fields defined as class attributes above
