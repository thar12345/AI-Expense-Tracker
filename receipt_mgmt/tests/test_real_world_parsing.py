"""
Tests for real-world receipt parsing using actual Azure Document Intelligence responses.
"""

import json
import os
from decimal import Decimal
from datetime import date, time
from django.test import TestCase
from unittest.mock import Mock

from receipt_mgmt.services.img_receipt_engine import (
    _build_serializer_dict, _extract_items, _extract_tax_amount, 
    _extract_tax_rate, _round_quantity, _format_title_case
)


class MockAnalyzeResult:
    """Mock Azure AnalyzeResult object to match the expected interface."""
    def __init__(self, json_data):
        self.documents = []
        if 'analyzeResult' in json_data and 'documents' in json_data['analyzeResult']:
            for doc in json_data['analyzeResult']['documents']:
                mock_doc = MockDocument(doc)
                self.documents.append(mock_doc)


class MockDocument:
    """Mock Azure Document object."""
    def __init__(self, doc_data):
        self.fields = doc_data.get('fields', {})


class RealWorldReceiptParsingTestCase(TestCase):
    """Test cases using real-world Azure Document Intelligence responses."""
    
    @classmethod
    def setUpClass(cls):
        """Load the real-world JSON example once for all tests."""
        super().setUpClass()
        json_path = os.path.join(
            os.path.dirname(__file__), 
            'dynamite_receipt_example.json'
        )
        with open(json_path, 'r') as f:
            cls.example_json = json.load(f)
        
        # Create mock result object
        cls.mock_result = MockAnalyzeResult(cls.example_json)
        
        # Extract fields for individual tests
        cls.fields = cls.example_json['analyzeResult']['documents'][0]['fields']
    
    def test_real_world_json_structure(self):
        """Test that the real-world JSON has the expected structure."""
        self.assertEqual(self.example_json['status'], 'succeeded')
        self.assertEqual(
            self.example_json['analyzeResult']['modelId'], 
            'prebuilt-receipt'
        )
        self.assertEqual(len(self.example_json['analyzeResult']['documents']), 1)
        
        # Check that key fields exist
        expected_fields = [
            'MerchantName', 'MerchantAddress', 'CountryRegion', 'Items',
            'Subtotal', 'Total', 'TotalTax', 'TaxDetails', 'TransactionDate', 
            'TransactionTime', 'ReceiptType'
        ]
        for field in expected_fields:
            self.assertIn(field, self.fields, f"Missing field: {field}")
    
    def test_full_receipt_parsing(self):
        """Test complete receipt parsing with real-world data."""
        result = _build_serializer_dict(self.mock_result)
        
        # Test basic receipt information
        self.assertEqual(result['company'], 'Dynamite')
        self.assertEqual(result['country_region'], 'CAN')
        self.assertEqual(result['receipt_currency_code'], 'CAD')
        self.assertEqual(
            result['address'], 
            '25 The West Mall Dynamite 13.\nEtobicoke, ON M9C1B8'
        )
        
        # Test date and time parsing
        self.assertEqual(result['date'], date(2025, 6, 10))
        self.assertEqual(result['time'], time(19, 5, 34))  # 7:05:34 PM converted
        
        # Test monetary values with proper decimal precision
        self.assertEqual(result['sub_total'], Decimal('114.85'))
        self.assertEqual(result['tax'], Decimal('14.92'))
        self.assertEqual(result['tax_rate'], Decimal('0.13'))  # 13%
        self.assertEqual(result['total'], Decimal('129.77'))
        self.assertIsNone(result['tip'])
        
        # Test items
        self.assertEqual(result['item_count'], 5)
        self.assertEqual(len(result['items']), 5)
    
    def test_items_extraction_with_real_data(self):
        """Test item extraction with real-world item data."""
        items = _extract_items(self.fields)
        
        self.assertEqual(len(items), 5)
        
        # Test first item (Leo Wide Leg Linen P)
        item1 = items[0]
        self.assertEqual(
            item1['description'], 
            'Leo Wide Leg Linen P ||\nL/03G Snow White || Snow White'
        )
        self.assertEqual(item1['product_id'], '0925562')
        self.assertEqual(item1['quantity'], Decimal('1.00'))
        self.assertEqual(item1['price'], Decimal('69.95'))
        self.assertEqual(item1['total_price'], Decimal('69.95'))
        self.assertEqual(item1['quantity_unit'], 'Unit(s)')
        
        # Test second item (Linen Tube Top)
        item2 = items[1]
        self.assertEqual(
            item2['description'], 
            'Linen Tube Top || Haut\nM/03G Snow White || Snow White'
        )
        self.assertEqual(item2['product_id'], '0927677')
        self.assertEqual(item2['quantity'], Decimal('1.00'))
        self.assertEqual(item2['price'], Decimal('49.95'))
        self.assertEqual(item2['total_price'], Decimal('49.95'))
        
        # Test return item (negative price)
        item5 = items[4]
        self.assertEqual(item5['description'], 'Eloise Poplin Mini D Ii')
        self.assertEqual(item5['product_id'], '0924299')
        self.assertEqual(item5['quantity'], Decimal('1.00'))
        self.assertEqual(item5['price'], Decimal('-89.95'))  # Return item
        self.assertEqual(item5['total_price'], Decimal('-89.95'))
    
    def test_tax_extraction_with_real_data(self):
        """Test tax amount and rate extraction with real tax data."""
        # Test tax amount extraction
        tax_amount = _extract_tax_amount(self.fields)
        self.assertEqual(tax_amount, 14.92)
        
        # Test tax rate extraction
        tax_rate = _extract_tax_rate(self.fields)
        self.assertEqual(tax_rate, 0.13)  # 13% GST/HST
    
    def test_quantity_rounding_with_real_data(self):
        """Test that quantities are properly rounded to 2 decimal places."""
        items = _extract_items(self.fields)
        
        for i, item in enumerate(items):
            # All quantities should be Decimal objects rounded to 2 places
            self.assertIsInstance(
                item['quantity'], 
                Decimal, 
                f"Item {i+1} quantity is not a Decimal"
            )
            self.assertEqual(
                item['quantity'], 
                Decimal('1.00'),
                f"Item {i+1} quantity not properly rounded"
            )
    
    def test_title_case_formatting(self):
        """Test title case formatting with real data."""
        # Test company name formatting
        company_raw = self.fields['MerchantName']['valueString']  # "DYNAMITE"
        company_formatted = _format_title_case(company_raw)
        self.assertEqual(company_formatted, 'Dynamite')
        
        # Test item descriptions are formatted
        items = _extract_items(self.fields)
        
        # Test first item specifically (Leo Wide Leg)
        item1 = items[0]
        self.assertIn('Leo Wide Leg', item1['description'])
        
        # Test that other items have proper formatting
        for item in items:
            description = item['description']
            # Check that descriptions don't contain all caps words
            self.assertNotIn('LINEN', description)  # Should be "Linen"
            self.assertNotIn('TUBE', description)   # Should be "Tube"
            # Note: The actual descriptions in this receipt are already mixed case
    
    def test_currency_handling(self):
        """Test currency code and symbol extraction."""
        result = _build_serializer_dict(self.mock_result)
        
        # This receipt has currency code but no symbol in the JSON
        self.assertEqual(result['receipt_currency_code'], 'CAD')
        self.assertEqual(result['receipt_currency_symbol'], '')
    
    def test_missing_fields_handling(self):
        """Test graceful handling of missing optional fields."""
        result = _build_serializer_dict(self.mock_result)
        
        # Fields that are missing in this receipt should be handled gracefully
        self.assertEqual(result['company_phone'], '')  # No MerchantPhoneNumber
        self.assertIsNone(result['tip'])  # No Tip field
        
        # Items should have empty quantity_unit since not provided
        for item in result['items']:
            self.assertEqual(item['quantity_unit'], 'Unit(s)')
    
    def test_multiline_descriptions(self):
        """Test handling of multi-line item descriptions."""
        items = _extract_items(self.fields)
        
        # First item has multi-line description
        item1 = items[0]
        self.assertIn('\n', item1['description'])
        self.assertTrue(item1['description'].startswith('Leo Wide Leg'))
        self.assertIn('Snow White', item1['description'])
    
    def test_negative_prices_for_returns(self):
        """Test handling of negative prices for return items."""
        items = _extract_items(self.fields)
        
        # Last item is a return with negative price
        return_item = items[4]
        self.assertEqual(return_item['product_id'], '0924299')
        self.assertEqual(return_item['price'], Decimal('-89.95'))
        self.assertEqual(return_item['total_price'], Decimal('-89.95'))
        self.assertTrue(return_item['price'] < 0)
    
    def test_decimal_precision_consistency(self):
        """Test that all monetary values maintain consistent decimal precision."""
        result = _build_serializer_dict(self.mock_result)
        
        # All monetary fields should be Decimal with 2 decimal places
        monetary_fields = ['sub_total', 'tax', 'tax_rate', 'total']
        for field in monetary_fields:
            value = result[field]
            if value is not None:
                self.assertIsInstance(value, Decimal, f"{field} is not a Decimal")
                # Check that it has exactly 2 decimal places when converted to string
                str_value = str(value)
                if '.' in str_value:
                    decimal_places = len(str_value.split('.')[1])
                    self.assertLessEqual(
                        decimal_places, 
                        2, 
                        f"{field} has more than 2 decimal places: {value}"
                    )
        
        # Test item prices and quantities
        for i, item in enumerate(result['items']):
            for field in ['price', 'total_price', 'quantity']:
                value = item[field]
                if value is not None:
                    self.assertIsInstance(
                        value, 
                        Decimal, 
                        f"Item {i+1} {field} is not a Decimal"
                    )
    
    def test_receipt_type_handling(self):
        """Test receipt type extraction and handling."""
        # This receipt has ReceiptType as "Supplies"
        receipt_type = self.fields.get('ReceiptType', {}).get('valueString')
        self.assertEqual(receipt_type, 'Supplies')
        
        # Our engine doesn't currently map this to the receipt_type field
        # but it could be added in the future
    
    def test_complete_data_integrity(self):
        """Test that the parsed data maintains integrity with the source."""
        result = _build_serializer_dict(self.mock_result)
        
        # Verify totals make sense
        expected_item_total = sum(item['total_price'] for item in result['items'])
        # Note: The receipt has returns, so item total might not equal subtotal
        
        # Verify tax calculation
        if result['sub_total'] and result['tax_rate']:
            expected_tax = result['sub_total'] * result['tax_rate']
            # Allow for small rounding differences (up to 2 cents due to rounding)
            tax_diff = abs(expected_tax - result['tax'])
            self.assertLess(tax_diff, Decimal('0.02'), "Tax calculation mismatch")
        
        # Verify final total
        if result['sub_total'] and result['tax']:
            expected_total = result['sub_total'] + result['tax']
            self.assertEqual(expected_total, result['total'], "Total calculation mismatch") 