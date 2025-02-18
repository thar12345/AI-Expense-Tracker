"""
Tests for receipt_mgmt signals.
"""

from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, Mock
from datetime import date
from decimal import Decimal

from receipt_mgmt.models import Receipt
from receipt_mgmt.signals import receipt_uploaded, handle_receipt_uploaded
from core.models import UsageTracker

User = get_user_model()


class ReceiptSignalsTestCase(TransactionTestCase):
    """Test cases for receipt signals using TransactionTestCase for atomic operations."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='testpass123'
        )
        
        self.receipt = Receipt.objects.create(
            user=self.user,
            company='Test Store',
            date=date.today(),
            total=Decimal('10.00')
        )
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_receipt_uploaded_signal_websocket_notification(self, mock_async_to_sync, mock_get_channel_layer):
        """Test that receipt_uploaded signal sends websocket notification."""
        mock_channel_layer = Mock()
        mock_get_channel_layer.return_value = mock_channel_layer
        mock_group_send = Mock()
        mock_async_to_sync.return_value = mock_group_send
        
        # Send the signal
        receipt_uploaded.send(
            sender=Receipt,
            user=self.user,
            receipt_id=self.receipt.id
        )
        
        # Verify websocket notification was sent
        mock_get_channel_layer.assert_called_once()
        mock_async_to_sync.assert_called_once_with(mock_channel_layer.group_send)
        mock_group_send.assert_called_once_with(
            f"user_{self.user.id}",
            {
                "type": "new_receipt_notification",
                "receipt_id": self.receipt.id,
            }
        )
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_receipt_uploaded_signal_usage_tracking_new_record(self, mock_async_to_sync, mock_get_channel_layer):
        """Test that receipt_uploaded signal creates new usage tracker record."""
        # Ensure no existing usage record
        UsageTracker.objects.filter(user=self.user).delete()
        
        # Send the signal
        receipt_uploaded.send(
            sender=Receipt,
            user=self.user,
            receipt_id=self.receipt.id
        )
        
        # Verify usage tracker record was created
        usage_record = UsageTracker.objects.get(
            user=self.user,
            usage_type=UsageTracker.RECEIPT_UPLOAD,
            date=timezone.now().date()
        )
        self.assertEqual(usage_record.count, 1)
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_receipt_uploaded_signal_usage_tracking_existing_record(self, mock_async_to_sync, mock_get_channel_layer):
        """Test that receipt_uploaded signal increments existing usage tracker record."""
        # Create existing usage record
        today = timezone.now().date()
        existing_record = UsageTracker.objects.create(
            user=self.user,
            usage_type=UsageTracker.RECEIPT_UPLOAD,
            date=today,
            count=5
        )
        
        # Send the signal
        receipt_uploaded.send(
            sender=Receipt,
            user=self.user,
            receipt_id=self.receipt.id
        )
        
        # Verify usage tracker record was incremented
        existing_record.refresh_from_db()
        self.assertEqual(existing_record.count, 6)
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_receipt_uploaded_signal_multiple_calls_same_day(self, mock_async_to_sync, mock_get_channel_layer):
        """Test multiple signal calls on the same day increment the counter."""
        # Ensure no existing usage record
        UsageTracker.objects.filter(user=self.user).delete()
        
        # Send the signal multiple times
        for i in range(3):
            receipt_uploaded.send(
                sender=Receipt,
                user=self.user,
                receipt_id=self.receipt.id
            )
        
        # Verify usage tracker record shows correct count
        usage_record = UsageTracker.objects.get(
            user=self.user,
            usage_type=UsageTracker.RECEIPT_UPLOAD,
            date=timezone.now().date()
        )
        self.assertEqual(usage_record.count, 3)
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_receipt_uploaded_signal_different_users(self, mock_async_to_sync, mock_get_channel_layer):
        """Test that signal correctly handles different users."""
        # Create another user
        user2 = User.objects.create_user(
            username='user2@example.com',
            email='user2@example.com',
            password='testpass123'
        )
        
        receipt2 = Receipt.objects.create(
            user=user2,
            company='Store 2',
            date=date.today(),
            total=Decimal('20.00')
        )
        
        # Send signals for both users
        receipt_uploaded.send(
            sender=Receipt,
            user=self.user,
            receipt_id=self.receipt.id
        )
        
        receipt_uploaded.send(
            sender=Receipt,
            user=user2,
            receipt_id=receipt2.id
        )
        
        # Verify separate usage records were created
        usage_record1 = UsageTracker.objects.get(
            user=self.user,
            usage_type=UsageTracker.RECEIPT_UPLOAD,
            date=timezone.now().date()
        )
        usage_record2 = UsageTracker.objects.get(
            user=user2,
            usage_type=UsageTracker.RECEIPT_UPLOAD,
            date=timezone.now().date()
        )
        
        self.assertEqual(usage_record1.count, 1)
        self.assertEqual(usage_record2.count, 1)
    
    @patch('receipt_mgmt.signals.async_to_sync')
    @patch('receipt_mgmt.signals.get_channel_layer')
    def test_receipt_uploaded_signal_websocket_error_handling(self, mock_get_channel_layer, mock_async_to_sync):
        """Test that websocket errors don't prevent usage tracking."""
        # Mock channel layer to raise an exception
        mock_channel_layer = Mock()
        mock_get_channel_layer.return_value = mock_channel_layer
        
        # Make the async_to_sync wrapper raise an exception
        mock_async_to_sync.side_effect = Exception("WebSocket error")
        
        # Create a receipt
        receipt = Receipt.objects.create(
            user=self.user,
            company='Test Store',
            date=date.today(),
            total=Decimal('50.00'),
            receipt_type=Receipt.ReceiptType.GROCERIES
        )
        
        # Send signal - should not raise exception despite websocket error
        receipt_uploaded.send(
            user=self.user,
            sender=Receipt,
            receipt_id=receipt.id
        )
        
        # Usage tracking should still work
        usage_tracker = UsageTracker.objects.get(user=self.user, date=date.today())
        self.assertEqual(usage_tracker.count, 1)


class ReceiptSignalsUnitTestCase(TestCase):
    """Unit tests for signal handler functions."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='testpass123'
        )
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_handle_receipt_uploaded_function_directly(self, mock_async_to_sync, mock_get_channel_layer):
        """Test calling the signal handler function directly."""
        mock_channel_layer = Mock()
        mock_get_channel_layer.return_value = mock_channel_layer
        mock_group_send = Mock()
        mock_async_to_sync.return_value = mock_group_send
        
        receipt_id = 123
        
        # Call the handler directly
        handle_receipt_uploaded(
            sender=Receipt,
            user=self.user,
            receipt_id=receipt_id
        )
        
        # Verify websocket notification
        mock_group_send.assert_called_once_with(
            f"user_{self.user.id}",
            {
                "type": "new_receipt_notification",
                "receipt_id": receipt_id,
            }
        )
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_handle_receipt_uploaded_with_kwargs(self, mock_async_to_sync, mock_get_channel_layer):
        """Test signal handler with additional kwargs."""
        mock_channel_layer = Mock()
        mock_get_channel_layer.return_value = mock_channel_layer
        mock_group_send = Mock()
        mock_async_to_sync.return_value = mock_group_send
        
        receipt_id = 456
        
        # Call with extra kwargs
        handle_receipt_uploaded(
            sender=Receipt,
            user=self.user,
            receipt_id=receipt_id,
            extra_param="test",
            another_param=True
        )
        
        # Should still work correctly
        mock_group_send.assert_called_once_with(
            f"user_{self.user.id}",
            {
                "type": "new_receipt_notification",
                "receipt_id": receipt_id,
            }
        )


class ReceiptSignalsEdgeCasesTestCase(TransactionTestCase):
    """Test edge cases and error scenarios for receipt signals."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='testpass123'
        )
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_signal_with_invalid_receipt_id(self, mock_async_to_sync, mock_get_channel_layer):
        """Test signal with invalid receipt ID."""
        mock_channel_layer = Mock()
        mock_get_channel_layer.return_value = mock_channel_layer
        mock_group_send = Mock()
        mock_async_to_sync.return_value = mock_group_send
        
        # Send signal with invalid receipt ID
        receipt_uploaded.send(
            sender=Receipt,
            user=self.user,
            receipt_id=99999  # Non-existent ID
        )
        
        # Should still process normally
        mock_group_send.assert_called_once_with(
            f"user_{self.user.id}",
            {
                "type": "new_receipt_notification",
                "receipt_id": 99999,
            }
        )
        
        # Usage tracking should still work
        usage_record = UsageTracker.objects.get(
            user=self.user,
            usage_type=UsageTracker.RECEIPT_UPLOAD,
            date=timezone.now().date()
        )
        self.assertEqual(usage_record.count, 1)
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    @patch('receipt_mgmt.signals.UsageTracker.objects.select_for_update')
    def test_signal_with_database_error(self, mock_select_for_update, mock_async_to_sync, mock_get_channel_layer):
        """Test signal behavior when database operations fail."""
        # Make database operation fail
        mock_select_for_update.side_effect = Exception("Database error")
        
        # Signal should raise the exception (no error handling in current implementation)
        with self.assertRaises(Exception):
            receipt_uploaded.send(
                sender=Receipt,
                user=self.user,
                receipt_id=123
            )
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    @patch('receipt_mgmt.signals.async_to_sync')
    def test_signal_without_required_parameters(self, mock_async_to_sync, mock_get_channel_layer):
        """Test signal behavior when required parameters are missing."""
        # This should raise an error since user and receipt_id are required
        with self.assertRaises(TypeError):
            receipt_uploaded.send(sender=Receipt)
    
    @patch('receipt_mgmt.signals.get_channel_layer')
    def test_signal_with_none_user(self, mock_get_channel_layer):
        """Test signal behavior with None user."""
        # The signal should handle None user gracefully and not create any usage records
        receipt_uploaded.send(
            sender=Receipt,
            user=None,
            receipt_id=123
        )
        
        # Should not create any usage tracker records
        self.assertEqual(UsageTracker.objects.count(), 0) 