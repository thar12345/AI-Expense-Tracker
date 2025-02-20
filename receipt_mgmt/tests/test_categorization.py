"""
Tests for receipt item categorization functionality.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from datetime import date
from unittest.mock import patch, MagicMock

from receipt_mgmt.models import Receipt, Item
from receipt_mgmt.services.spending_categorization import categorize_receipt_items

User = get_user_model()


class ReceiptCategorizationTestCase(TestCase):
    """Test cases for receipt item categorization."""
    
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
            total=100.00,
            receipt_type=Receipt.ReceiptType.OTHER
        )
    
    def test_categorize_receipt_with_no_items(self):
        """Test that receipts with no items are categorized as Other."""
        # Ensure receipt has no items
        self.assertEqual(self.receipt.items.count(), 0)
        
        # Set initial category to something other than Other
        self.receipt.receipt_type = Receipt.ReceiptType.GROCERIES
        self.receipt.save()
        
        # Run categorization
        result = categorize_receipt_items(self.receipt)
        
        # Check results
        self.assertEqual(result['items_updated'], 0)
        self.assertTrue(result['receipt_category_changed'])
        self.assertEqual(result['old_receipt_category'], Receipt.ReceiptType.GROCERIES)
        self.assertEqual(result['new_receipt_category'], Receipt.ReceiptType.OTHER)
        self.assertEqual(result['category_distribution'], {})
        self.assertEqual(result['categorization_method'], 'no_items')
        
        # Verify receipt was updated
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.receipt_type, Receipt.ReceiptType.OTHER)
    
    def test_categorize_receipt_with_no_items_already_other(self):
        """Test that receipts already categorized as Other don't change."""
        # Set receipt to Other category
        self.receipt.receipt_type = Receipt.ReceiptType.OTHER
        self.receipt.save()
        
        # Run categorization
        result = categorize_receipt_items(self.receipt)
        
        # Check results - no change should occur
        self.assertEqual(result['items_updated'], 0)
        self.assertFalse(result['receipt_category_changed'])
        self.assertEqual(result['old_receipt_category'], Receipt.ReceiptType.OTHER)
        self.assertEqual(result['new_receipt_category'], Receipt.ReceiptType.OTHER)
        self.assertEqual(result['categorization_method'], 'no_items')
    
    @patch('receipt_mgmt.services.spending_categorization.openai.chat.completions.create')
    def test_categorize_receipt_with_items(self, mock_openai):
        """Test categorization of receipt with items using mocked OpenAI."""
        # Create test items
        item1 = Item.objects.create(
            receipt=self.receipt,
            description='Organic Bananas',
            product_id='FRUIT001',
            total_price=3.99,
            item_category=Receipt.ReceiptType.OTHER
        )
        item2 = Item.objects.create(
            receipt=self.receipt,
            description='Wireless Headphones',
            product_id='TECH456',
            total_price=79.99,
            item_category=Receipt.ReceiptType.OTHER
        )
        item3 = Item.objects.create(
            receipt=self.receipt,
            description='Dog Food',
            product_id='PET123',
            total_price=24.99,
            item_category=Receipt.ReceiptType.OTHER
        )
        
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '''
        {
            "categorized_items": [
                {"id": ''' + str(item1.id) + ''', "category": 1},
                {"id": ''' + str(item2.id) + ''', "category": 4},
                {"id": ''' + str(item3.id) + ''', "category": 15}
            ]
        }
        '''
        mock_openai.return_value = mock_response
        
        # Run categorization
        result = categorize_receipt_items(self.receipt)
        
        # Check results
        self.assertEqual(result['items_updated'], 3)
        self.assertTrue(result['receipt_category_changed'])
        self.assertEqual(result['old_receipt_category'], Receipt.ReceiptType.OTHER)
        # Receipt should be categorized as the mode of item categories
        # Since we have 1 grocery, 1 electronics, 1 pets - it should pick the first one
        self.assertIn(result['new_receipt_category'], [
            Receipt.ReceiptType.GROCERIES,
            Receipt.ReceiptType.ELECTRONICS, 
            Receipt.ReceiptType.PETS
        ])
        self.assertEqual(result['categorization_method'], 'item_analysis')
        
        # Verify items were updated
        item1.refresh_from_db()
        item2.refresh_from_db()
        item3.refresh_from_db()
        
        self.assertEqual(item1.item_category, Receipt.ReceiptType.GROCERIES)
        self.assertEqual(item2.item_category, Receipt.ReceiptType.ELECTRONICS)
        self.assertEqual(item3.item_category, Receipt.ReceiptType.PETS)
        
        # Verify OpenAI was called
        mock_openai.assert_called_once()
    
    @patch('receipt_mgmt.services.spending_categorization.openai.chat.completions.create')
    def test_categorize_receipt_with_items_same_category(self, mock_openai):
        """Test categorization when all items are in the same category."""
        # Create test items
        item1 = Item.objects.create(
            receipt=self.receipt,
            description='Apples',
            product_id='FRUIT001',
            total_price=3.99,
            item_category=Receipt.ReceiptType.OTHER
        )
        item2 = Item.objects.create(
            receipt=self.receipt,
            description='Milk',
            product_id='DAIRY001',
            total_price=4.99,
            item_category=Receipt.ReceiptType.OTHER
        )
        
        # Mock OpenAI response - both items as groceries
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '''
        {
            "categorized_items": [
                {"id": ''' + str(item1.id) + ''', "category": 1},
                {"id": ''' + str(item2.id) + ''', "category": 1}
            ]
        }
        '''
        mock_openai.return_value = mock_response
        
        # Run categorization
        result = categorize_receipt_items(self.receipt)
        
        # Check results
        self.assertEqual(result['items_updated'], 2)
        self.assertTrue(result['receipt_category_changed'])
        self.assertEqual(result['new_receipt_category'], Receipt.ReceiptType.GROCERIES)
        self.assertEqual(result['category_distribution'], {Receipt.ReceiptType.GROCERIES: 2})
        
        # Verify receipt was updated
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.receipt_type, Receipt.ReceiptType.GROCERIES)
    
    @patch('receipt_mgmt.services.spending_categorization.openai.chat.completions.create')
    def test_categorize_receipt_openai_error(self, mock_openai):
        """Test handling of OpenAI API errors."""
        # Create test item
        Item.objects.create(
            receipt=self.receipt,
            description='Test Item',
            product_id='TEST001',
            total_price=10.00,
            item_category=Receipt.ReceiptType.OTHER
        )
        
        # Mock OpenAI to raise an exception
        mock_openai.side_effect = Exception("API Error")
        
        # Run categorization
        result = categorize_receipt_items(self.receipt)
        
        # Check error handling
        self.assertEqual(result['items_updated'], 0)
        self.assertFalse(result['receipt_category_changed'])
        self.assertEqual(result['old_receipt_category'], Receipt.ReceiptType.OTHER)
        self.assertEqual(result['new_receipt_category'], Receipt.ReceiptType.OTHER)
        self.assertIn('error', result)
        self.assertEqual(result['error'], "API Error") 