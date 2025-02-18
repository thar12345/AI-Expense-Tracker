"""
Tests for receipt_mgmt filters.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from receipt_mgmt.models import Receipt, Tag
from receipt_mgmt.filters import ReceiptFilter

User = get_user_model()


class ReceiptFilterTestCase(TestCase):
    """Test cases for ReceiptFilter."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create receipts with different dates and types
        today = timezone.now().date()
        
        self.recent_receipt = Receipt.objects.create(
            user=self.user,
            company='Recent Store',
            date=today,
            total=Decimal('50.00'),
            receipt_type=Receipt.ReceiptType.GROCERIES
        )
        
        self.old_receipt = Receipt.objects.create(
            user=self.user,
            company='Old Store',
            date=today - timedelta(days=45),
            total=Decimal('75.00'),
            receipt_type=Receipt.ReceiptType.DINING_OUT
        )
        
        self.electronics_receipt = Receipt.objects.create(
            user=self.user,
            company='Electronics Store',
            date=today - timedelta(days=10),
            total=Decimal('200.00'),
            receipt_type=Receipt.ReceiptType.ELECTRONICS
        )
        
        # Manually set created_at to match the test scenarios
        Receipt.objects.filter(id=self.recent_receipt.id).update(
            created_at=timezone.now()
        )
        Receipt.objects.filter(id=self.old_receipt.id).update(
            created_at=timezone.now() - timedelta(days=45)
        )
        Receipt.objects.filter(id=self.electronics_receipt.id).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        
        # Create tags
        self.tag1 = Tag.objects.create(user=self.user, name='Important')
        self.tag2 = Tag.objects.create(user=self.user, name='Business')
        
        # Associate tags with receipts
        self.recent_receipt.tags.add(self.tag1)
        self.electronics_receipt.tags.add(self.tag1, self.tag2)
    
    def test_filter_period_7d(self):
        """Test filtering by 7 day period."""
        # Create a receipt within the last 7 days
        recent_date = timezone.now().date() - timedelta(days=3)
        recent_receipt = Receipt.objects.create(
            user=self.user,
            company='Recent Store',
            date=recent_date,
            total=Decimal('25.00'),
            receipt_type=Receipt.ReceiptType.GROCERIES
        )
        
        # Test the filter
        filter_instance = ReceiptFilter()
        filtered_qs = filter_instance.filter_period(
            Receipt.objects.filter(user=self.user), 
            'period', 
            '7d'
        )
        
        # Should include recent receipt and today's receipts
        self.assertIn(recent_receipt, filtered_qs)
        self.assertIn(self.recent_receipt, filtered_qs)
        # Should not include old receipts
        self.assertNotIn(self.old_receipt, filtered_qs)
    
    def test_filter_period_30d(self):
        """Test filtering by 30 day period."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        filtered_qs = filter_instance.filter_period(queryset, 'date_period', '30d')
        
        # Should include recent and electronics receipts, exclude old receipt
        self.assertIn(self.recent_receipt, filtered_qs)
        self.assertIn(self.electronics_receipt, filtered_qs)
        self.assertNotIn(self.old_receipt, filtered_qs)
    
    def test_filter_period_3m(self):
        """Test filtering by 3 month period."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        filtered_qs = filter_instance.filter_period(queryset, 'date_period', '3m')
        
        # Should include all receipts (45 days is less than 90 days)
        self.assertIn(self.recent_receipt, filtered_qs)
        self.assertIn(self.electronics_receipt, filtered_qs)
        self.assertIn(self.old_receipt, filtered_qs)
    
    def test_filter_period_invalid(self):
        """Test filtering with invalid period."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        filtered_qs = filter_instance.filter_period(queryset, 'date_period', 'invalid')
        
        # Should return original queryset unchanged
        self.assertEqual(list(filtered_qs), list(queryset))
    
    def test_filter_category_by_integer(self):
        """Test filtering by category using integer IDs."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by Groceries (1)
        filtered_qs = filter_instance.filter_category(queryset, 'category', '1')
        
        self.assertIn(self.recent_receipt, filtered_qs)
        self.assertNotIn(self.old_receipt, filtered_qs)
        self.assertNotIn(self.electronics_receipt, filtered_qs)
    
    def test_filter_category_by_string(self):
        """Test filtering by category using string names."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by Dining Out
        filtered_qs = filter_instance.filter_category(queryset, 'category', 'Dining Out')
        
        self.assertNotIn(self.recent_receipt, filtered_qs)
        self.assertIn(self.old_receipt, filtered_qs)
        self.assertNotIn(self.electronics_receipt, filtered_qs)
    
    def test_filter_category_multiple_integers(self):
        """Test filtering by multiple categories using integers."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by Groceries (1) and Electronics (4)
        filtered_qs = filter_instance.filter_category(queryset, 'category', '1,4')
        
        self.assertIn(self.recent_receipt, filtered_qs)
        self.assertNotIn(self.old_receipt, filtered_qs)
        self.assertIn(self.electronics_receipt, filtered_qs)
    
    def test_filter_category_mixed_formats(self):
        """Test filtering by categories using mixed string and integer formats."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by Groceries (string) and Electronics (integer)
        filtered_qs = filter_instance.filter_category(queryset, 'category', 'Groceries,4')
        
        self.assertIn(self.recent_receipt, filtered_qs)
        self.assertNotIn(self.old_receipt, filtered_qs)
        self.assertIn(self.electronics_receipt, filtered_qs)
    
    def test_filter_category_invalid(self):
        """Test filtering by invalid category."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by non-existent category
        filtered_qs = filter_instance.filter_category(queryset, 'category', 'NonExistent')
        
        # Should return empty queryset
        self.assertEqual(filtered_qs.count(), 0)
    
    def test_filter_category_empty_string(self):
        """Test filtering by empty category string."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        filtered_qs = filter_instance.filter_category(queryset, 'category', '')
        
        # Should return empty queryset
        self.assertEqual(filtered_qs.count(), 0)
    
    def test_filter_tags_single(self):
        """Test filtering by single tag."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by tag1
        filtered_qs = filter_instance.filter_tags(queryset, 'tags', str(self.tag1.id))
        
        self.assertIn(self.recent_receipt, filtered_qs)
        self.assertNotIn(self.old_receipt, filtered_qs)
        self.assertIn(self.electronics_receipt, filtered_qs)
    
    def test_filter_tags_multiple(self):
        """Test filtering by multiple tags."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by both tags
        filtered_qs = filter_instance.filter_tags(
            queryset, 'tags', f'{self.tag1.id},{self.tag2.id}'
        )
        
        # Should include receipts that have ANY of the specified tags
        self.assertIn(self.recent_receipt, filtered_qs)  # Has tag1
        self.assertNotIn(self.old_receipt, filtered_qs)  # Has no tags
        self.assertIn(self.electronics_receipt, filtered_qs)  # Has both tags
    
    def test_filter_tags_non_existent(self):
        """Test filtering by non-existent tag ID."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by non-existent tag ID
        filtered_qs = filter_instance.filter_tags(queryset, 'tags', '99999')
        
        # Should return empty queryset
        self.assertEqual(filtered_qs.count(), 0)
    
    def test_filter_tags_invalid_format(self):
        """Test filtering by invalid tag format."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Filter by invalid tag format (non-numeric)
        filtered_qs = filter_instance.filter_tags(queryset, 'tags', 'invalid,not-a-number')
        
        # Should return empty queryset
        self.assertEqual(filtered_qs.count(), 0)
    
    def test_filter_tags_empty_string(self):
        """Test filtering by empty tag string."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        filtered_qs = filter_instance.filter_tags(queryset, 'tags', '')
        
        # Should return empty queryset
        self.assertEqual(filtered_qs.count(), 0)
    
    def test_filter_tags_mixed_valid_invalid(self):
        """Test filtering by mix of valid and invalid tag IDs."""
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter()
        
        # Mix valid tag ID with invalid ones
        filtered_qs = filter_instance.filter_tags(
            queryset, 'tags', f'{self.tag1.id},invalid,99999'
        )
        
        # Should filter by the valid tag ID only
        self.assertIn(self.recent_receipt, filtered_qs)
        self.assertNotIn(self.old_receipt, filtered_qs)
        self.assertIn(self.electronics_receipt, filtered_qs)


class ReceiptFilterIntegrationTestCase(TestCase):
    """Integration tests for ReceiptFilter with actual filtering."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create receipts for comprehensive testing
        today = timezone.now().date()
        
        self.walmart_receipt = Receipt.objects.create(
            user=self.user,
            company='Walmart',
            date=today,
            total=Decimal('50.00'),
            receipt_type=Receipt.ReceiptType.GROCERIES
        )
        
        self.target_receipt = Receipt.objects.create(
            user=self.user,
            company='Target',
            date=today - timedelta(days=5),
            total=Decimal('75.00'),
            receipt_type=Receipt.ReceiptType.GROCERIES
        )
        
        self.restaurant_receipt = Receipt.objects.create(
            user=self.user,
            company='Fine Dining',
            date=today - timedelta(days=2),
            total=Decimal('100.00'),
            receipt_type=Receipt.ReceiptType.DINING_OUT
        )
        
        # Set created_at dates
        Receipt.objects.filter(id=self.walmart_receipt.id).update(
            created_at=timezone.now()
        )
        Receipt.objects.filter(id=self.target_receipt.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        Receipt.objects.filter(id=self.restaurant_receipt.id).update(
            created_at=timezone.now() - timedelta(days=2)
        )
    
    def test_combined_filters(self):
        """Test combining multiple filters."""
        from django_filters import FilterSet
        from django.http import QueryDict
        
        # Create filter data
        data = QueryDict(mutable=True)
        data.update({
            'date_period': '7d',
            'category': 'Groceries',
            'company': 'walmart'
        })
        
        # Apply filters
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter(data, queryset=queryset)
        filtered_qs = filter_instance.qs
        
        # Should only include Walmart receipt (recent Groceries from Walmart)
        self.assertIn(self.walmart_receipt, filtered_qs)
        self.assertNotIn(self.target_receipt, filtered_qs)  # Groceries but not Walmart
        self.assertNotIn(self.restaurant_receipt, filtered_qs)  # Not Groceries
    
    def test_date_range_filters(self):
        """Test date_after and date_before filters."""
        from django.http import QueryDict
        
        # Filter for receipts created in the last 3 days
        three_days_ago = timezone.now() - timedelta(days=3)
        
        data = QueryDict(mutable=True)
        data['date_after'] = three_days_ago.date().isoformat()
        
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter(data, queryset=queryset)
        filtered_qs = filter_instance.qs
        
        # Should include walmart and restaurant receipts, exclude target
        self.assertIn(self.walmart_receipt, filtered_qs)
        self.assertNotIn(self.target_receipt, filtered_qs)
        self.assertIn(self.restaurant_receipt, filtered_qs)
    
    def test_company_filter_case_insensitive(self):
        """Test that company filter is case insensitive."""
        from django.http import QueryDict
        
        data = QueryDict(mutable=True)
        data['company'] = 'WALMART'  # Uppercase
        
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter(data, queryset=queryset)
        filtered_qs = filter_instance.qs
        
        # Should find Walmart receipt despite case difference
        self.assertIn(self.walmart_receipt, filtered_qs)
        self.assertNotIn(self.target_receipt, filtered_qs)
        self.assertNotIn(self.restaurant_receipt, filtered_qs)
    
    def test_empty_filters(self):
        """Test that empty filters return all receipts."""
        from django.http import QueryDict
        
        data = QueryDict()  # Empty filters
        
        queryset = Receipt.objects.filter(user=self.user)
        filter_instance = ReceiptFilter(data, queryset=queryset)
        filtered_qs = filter_instance.qs
        
        # Should include all receipts
        self.assertEqual(filtered_qs.count(), 3)
        self.assertIn(self.walmart_receipt, filtered_qs)
        self.assertIn(self.target_receipt, filtered_qs)
        self.assertIn(self.restaurant_receipt, filtered_qs) 