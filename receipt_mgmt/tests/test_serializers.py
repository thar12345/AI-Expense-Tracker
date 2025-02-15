"""
Tests for receipt_mgmt serializers.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from datetime import date, time
from decimal import Decimal
from rest_framework.test import APIRequestFactory

from receipt_mgmt.models import Receipt, Item, Tag
from receipt_mgmt.serializers import (
    ReceiptCreateSerializer, ReceiptSerializer, ReceiptListSerializer,
    ItemSerializer, TagSerializer, TagSummarySerializer
)

User = get_user_model()


class ItemSerializerTestCase(TestCase):
    """Test cases for ItemSerializer."""
    
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
            receipt_type=Receipt.ReceiptType.GROCERIES
        )
        
        self.item = Item.objects.create(
            receipt=self.receipt,
            description='Organic Bananas',
            product_id='FRUIT001',
            quantity=Decimal('2.00'),
            quantity_unit='lbs',
            price=Decimal('3.99'),
            total_price=Decimal('7.98'),
            item_category=Receipt.ReceiptType.GROCERIES
        )
    
    def test_item_serializer_fields(self):
        """Test that ItemSerializer includes all expected fields."""
        serializer = ItemSerializer(instance=self.item)
        data = serializer.data
        
        expected_fields = [
            'id', 'description', 'product_id', 'quantity', 'quantity_unit',
            'price', 'total_price', 'item_category', 'item_category_display'
        ]
        
        for field in expected_fields:
            self.assertIn(field, data)
    
    def test_item_serializer_data(self):
        """Test ItemSerializer data output."""
        serializer = ItemSerializer(instance=self.item)
        data = serializer.data
        
        self.assertEqual(data['description'], 'Organic Bananas')
        self.assertEqual(data['product_id'], 'FRUIT001')
        self.assertEqual(data['quantity'], '2.00000')  # Updated to match actual format
        self.assertEqual(data['quantity_unit'], 'lbs')
        self.assertEqual(data['price'], '3.99')
        self.assertEqual(data['total_price'], '7.98')
        self.assertEqual(data['item_category'], Receipt.ReceiptType.GROCERIES)
        self.assertEqual(data['item_category_display'], 'Groceries')
    
    def test_item_serializer_defaults(self):
        """Test ItemSerializer with default values."""
        item = Item.objects.create(
            receipt=self.receipt,
            description='Test Item'
        )
        
        serializer = ItemSerializer(instance=item)
        data = serializer.data
        
        self.assertEqual(data['description'], 'Test Item')
        self.assertEqual(data['product_id'], '')
        self.assertEqual(data['quantity'], '1.00000')  # Updated to match actual format
        self.assertEqual(data['quantity_unit'], 'Unit(s)')
        self.assertEqual(data['total_price'], '0.00')
        self.assertEqual(data['item_category'], Receipt.ReceiptType.OTHER)
        self.assertEqual(data['item_category_display'], 'Other')


class ReceiptCreateSerializerTestCase(TestCase):
    """Test cases for ReceiptCreateSerializer."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='testpass123'
        )
        
        self.valid_data = {
            'company': 'Test Store',
            'address': '123 Test Street',
            'country_region': 'US',
            'company_phone': '+1234567890',
            'date': date.today(),
            'time': time(14, 30, 0),
            'sub_total': Decimal('20.00'),
            'tax': Decimal('2.00'),
            'tax_rate': Decimal('0.10'),
            'total': Decimal('22.00'),
            'tip': Decimal('3.00'),
            'receipt_type': Receipt.ReceiptType.GROCERIES,
            'item_count': 2,
            'items': [
                {
                    'description': 'Apples',
                    'product_id': 'FRUIT001',
                    'quantity': Decimal('1.00'),
                    'quantity_unit': 'bag',
                    'price': Decimal('5.00'),
                    'total_price': Decimal('5.00'),
                    'item_category': Receipt.ReceiptType.GROCERIES
                },
                {
                    'description': 'Milk',
                    'product_id': 'DAIRY001',
                    'quantity': Decimal('1.00'),
                    'quantity_unit': 'gallon',
                    'price': Decimal('15.00'),
                    'total_price': Decimal('15.00'),
                    'item_category': Receipt.ReceiptType.GROCERIES
                }
            ],
            'receipt_currency_symbol': '$',
            'receipt_currency_code': 'USD'
        }
    
    def test_receipt_create_serializer_valid_data(self):
        """Test ReceiptCreateSerializer with valid data."""
        serializer = ReceiptCreateSerializer(data=self.valid_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        receipt = serializer.save(user=self.user)
        
        self.assertEqual(receipt.company, 'Test Store')
        self.assertEqual(receipt.address, '123 Test Street')
        self.assertEqual(receipt.country_region, 'US')
        self.assertEqual(receipt.company_phone, '+1234567890')
        self.assertEqual(receipt.date, date.today())
        self.assertEqual(receipt.time, time(14, 30, 0))
        self.assertEqual(receipt.sub_total, Decimal('20.00'))
        self.assertEqual(receipt.tax, Decimal('2.00'))
        self.assertEqual(receipt.tax_rate, Decimal('0.10'))
        self.assertEqual(receipt.total, Decimal('22.00'))
        self.assertEqual(receipt.tip, Decimal('3.00'))
        self.assertEqual(receipt.receipt_type, Receipt.ReceiptType.GROCERIES)
        self.assertEqual(receipt.item_count, 2)
        self.assertEqual(receipt.receipt_currency_symbol, '$')
        self.assertEqual(receipt.receipt_currency_code, 'USD')
        self.assertEqual(receipt.user, self.user)
        
        # Check items were created
        self.assertEqual(receipt.items.count(), 2)
        
        item1 = receipt.items.get(description='Apples')
        self.assertEqual(item1.product_id, 'FRUIT001')
        self.assertEqual(item1.quantity, Decimal('1.00'))
        self.assertEqual(item1.quantity_unit, 'bag')
        self.assertEqual(item1.price, Decimal('5.00'))
        self.assertEqual(item1.total_price, Decimal('5.00'))
        self.assertEqual(item1.item_category, Receipt.ReceiptType.GROCERIES)
    
    def test_receipt_create_serializer_minimal_data(self):
        """Test ReceiptCreateSerializer with minimal required data."""
        minimal_data = {
            'company': 'Minimal Store',
            'date': date.today(),
            'total': Decimal('10.00'),
            'items': []
        }
        
        serializer = ReceiptCreateSerializer(data=minimal_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        receipt = serializer.save(user=self.user)
        
        self.assertEqual(receipt.company, 'Minimal Store')
        self.assertEqual(receipt.date, date.today())
        self.assertEqual(receipt.total, Decimal('10.00'))
        self.assertEqual(receipt.receipt_type, Receipt.ReceiptType.OTHER)  # Default
        self.assertEqual(receipt.user, self.user)
        self.assertEqual(receipt.items.count(), 0)
    
    def test_receipt_create_serializer_invalid_data(self):
        """Test ReceiptCreateSerializer with invalid data."""
        invalid_data = {
            'company': '',  # Empty company
            'date': 'invalid-date',  # Invalid date
            'total': 'not-a-number',  # Invalid total
            'items': []
        }
        
        serializer = ReceiptCreateSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        
        self.assertIn('company', serializer.errors)
        self.assertIn('date', serializer.errors)
        self.assertIn('total', serializer.errors)
    
    def test_receipt_create_serializer_default_receipt_type(self):
        """Test that receipt_type defaults to OTHER when not provided."""
        data = {
            'company': 'Test Store',
            'date': date.today(),
            'total': Decimal('10.00'),
            'items': []
        }
        
        serializer = ReceiptCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        receipt = serializer.save(user=self.user)
        self.assertEqual(receipt.receipt_type, Receipt.ReceiptType.OTHER)


class ReceiptSerializerTestCase(TestCase):
    """Test cases for ReceiptSerializer."""
    
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
            address='123 Test Street',
            date=date.today(),
            total=Decimal('22.00'),
            receipt_type=Receipt.ReceiptType.GROCERIES
        )
        
        self.item = Item.objects.create(
            receipt=self.receipt,
            description='Test Item',
            total_price=Decimal('10.00')
        )
        
        self.tag = Tag.objects.create(
            user=self.user,
            name='Test Tag'
        )
        self.receipt.tags.add(self.tag)
    
    def test_receipt_serializer_fields(self):
        """Test that ReceiptSerializer includes all expected fields."""
        serializer = ReceiptSerializer(instance=self.receipt)
        data = serializer.data
        
        expected_fields = [
            'id', 'company', 'company_phone', 'address', 'country_region',
            'date', 'time', 'sub_total', 'tax', 'tax_rate', 'total', 'tip',
            'receipt_type', 'receipt_type_display', 'receipt_currency_symbol',
            'receipt_currency_code', 'item_count', 'items', 'raw_email',
            'raw_images', 'tags', 'manual_entry', 'created_at'
        ]
        
        for field in expected_fields:
            self.assertIn(field, data)
    
    def test_receipt_serializer_data(self):
        """Test ReceiptSerializer data output."""
        serializer = ReceiptSerializer(instance=self.receipt)
        data = serializer.data
        
        self.assertEqual(data['company'], 'Test Store')
        self.assertEqual(data['address'], '123 Test Street')
        self.assertEqual(data['total'], '22.00')
        self.assertEqual(data['receipt_type'], Receipt.ReceiptType.GROCERIES)
        self.assertEqual(data['receipt_type_display'], 'Groceries')
        
        # Check that items are included
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['description'], 'Test Item')
        
        # Check that tags are included
        self.assertEqual(len(data['tags']), 1)
        self.assertEqual(data['tags'][0]['name'], 'Test Tag')


class ReceiptListSerializerTestCase(TestCase):
    """Test cases for ReceiptListSerializer."""
    
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
            address='123 Test Street',
            date=date.today(),
            total=Decimal('22.00'),
            receipt_type=Receipt.ReceiptType.DINING_OUT
        )
    
    def test_receipt_list_serializer_fields(self):
        """Test that ReceiptListSerializer includes expected fields."""
        serializer = ReceiptListSerializer(instance=self.receipt)
        data = serializer.data
        
        expected_fields = [
            'id', 'company', 'total', 'date', 'receipt_type',
            'receipt_type_display', 'receipt_currency_symbol',
            'created_at', 'address'
        ]
        
        for field in expected_fields:
            self.assertIn(field, data)
    
    def test_receipt_list_serializer_data(self):
        """Test ReceiptListSerializer data output."""
        serializer = ReceiptListSerializer(instance=self.receipt)
        data = serializer.data
        
        self.assertEqual(data['company'], 'Test Store')
        self.assertEqual(data['total'], '22.00')
        self.assertEqual(data['receipt_type'], Receipt.ReceiptType.DINING_OUT)
        self.assertEqual(data['receipt_type_display'], 'Dining Out')
        self.assertEqual(data['address'], '123 Test Street')


class TagSerializerTestCase(TestCase):
    """Test cases for TagSerializer."""
    
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
        
        self.tag = Tag.objects.create(
            user=self.user,
            name='Test Tag'
        )
        self.tag.receipts.add(self.receipt)
    
    def test_tag_serializer_fields(self):
        """Test that TagSerializer includes expected fields."""
        serializer = TagSerializer(instance=self.tag)
        data = serializer.data
        
        expected_fields = ['id', 'name', 'receipts']
        
        for field in expected_fields:
            self.assertIn(field, data)
    
    def test_tag_serializer_data(self):
        """Test TagSerializer data output."""
        serializer = TagSerializer(instance=self.tag)
        data = serializer.data
        
        self.assertEqual(data['name'], 'Test Tag')
        self.assertEqual(len(data['receipts']), 1)
        self.assertEqual(data['receipts'][0], self.receipt.id)
    
    def test_tag_serializer_create_with_context(self):
        """Test TagSerializer create method with request context."""
        factory = APIRequestFactory()
        request = factory.post('/test/')
        request.user = self.user
        
        data = {
            'name': 'New Tag',
            'receipts': [self.receipt.id]
        }
        
        serializer = TagSerializer(data=data, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        tag = serializer.save()
        self.assertEqual(tag.name, 'New Tag')
        self.assertEqual(tag.user, self.user)
        self.assertEqual(tag.receipts.count(), 1)


class TagSummarySerializerTestCase(TestCase):
    """Test cases for TagSummarySerializer."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='testpass123'
        )
        
        self.tag = Tag.objects.create(
            user=self.user,
            name='Summary Tag'
        )
    
    def test_tag_summary_serializer_fields(self):
        """Test that TagSummarySerializer includes expected fields."""
        serializer = TagSummarySerializer(instance=self.tag)
        data = serializer.data
        
        expected_fields = ['id', 'name']
        
        for field in expected_fields:
            self.assertIn(field, data)
        
        # Should NOT include receipts field
        self.assertNotIn('receipts', data)
    
    def test_tag_summary_serializer_data(self):
        """Test TagSummarySerializer data output."""
        serializer = TagSummarySerializer(instance=self.tag)
        data = serializer.data
        
        self.assertEqual(data['name'], 'Summary Tag')
        self.assertEqual(len(data), 2)  # Only id and name 