"""
Tests for img_receipt_engine service.
"""

from django.test import TestCase
from unittest.mock import Mock, patch
from datetime import datetime, date, time
from decimal import Decimal

from receipt_mgmt.services.img_receipt_engine import (
    _safe_field, _parse_date, _parse_time, 
    _extract_currency_amount, _extract_items, _build_serializer_dict,
    _extract_tax_amount, _extract_tax_rate, _round_quantity
)


class ImgReceiptEngineTestCase(TestCase):
    """Test cases for img_receipt_engine helper functions."""
    
    def test_safe_field_success(self):
        """Test successful field extraction."""
        obj = {"field": {"subfield": "value"}}
        result = _safe_field(obj, "field", "subfield")
        self.assertEqual(result, "value")
    
    def test_safe_field_missing_field(self):
        """Test field extraction with missing field."""
        obj = {}
        result = _safe_field(obj, "field", "subfield", "default")
        self.assertEqual(result, "default")
    
    def test_safe_field_missing_subfield(self):
        """Test field extraction with missing subfield."""
        obj = {"field": {}}
        result = _safe_field(obj, "field", "subfield", "default")
        self.assertEqual(result, "default")
    

    
    def test_parse_date_valid(self):
        """Test date parsing with valid date."""
        result = _parse_date("2023-12-25")
        self.assertEqual(result, date(2023, 12, 25))
    
    def test_parse_date_invalid(self):
        """Test date parsing with invalid date."""
        result = _parse_date("invalid-date")
        self.assertIsNone(result)
    
    def test_parse_date_none(self):
        """Test date parsing with None input."""
        result = _parse_date(None)
        self.assertIsNone(result)
    
    def test_parse_time_valid_hms(self):
        """Test time parsing with HH:MM:SS format."""
        result = _parse_time("14:30:45")
        self.assertEqual(result, time(14, 30, 45))
    
    def test_parse_time_valid_hm(self):
        """Test time parsing with HH:MM format."""
        result = _parse_time("09:15")
        self.assertEqual(result, time(9, 15))
    
    def test_parse_time_invalid(self):
        """Test time parsing with invalid time."""
        result = _parse_time("invalid-time")
        self.assertIsNone(result)
    
    def test_parse_time_none(self):
        """Test time parsing with None input."""
        result = _parse_time(None)
        self.assertIsNone(result)
    
    def test_extract_currency_amount_valid(self):
        """Test currency amount extraction with valid data."""
        parent = {"Total": {"valueCurrency": {"amount": 25.99}}}
        result = _extract_currency_amount(parent, "Total")
        self.assertEqual(result, 25.99)
    
    def test_extract_currency_amount_missing(self):
        """Test currency amount extraction with missing data."""
        parent = {}
        result = _extract_currency_amount(parent, "Total")
        self.assertIsNone(result)
    
    def test_extract_tax_amount_from_total_tax(self):
        """Test tax extraction from TotalTax field."""
        fields = {"TotalTax": {"valueCurrency": {"amount": 5.25}}}
        result = _extract_tax_amount(fields)
        self.assertEqual(result, 5.25)
    
    def test_extract_tax_amount_from_tax_details(self):
        """Test tax extraction by summing TaxDetails."""
        fields = {
            "TaxDetails": {
                "valueArray": [
                    {
                        "valueObject": {
                            "Amount": {"valueCurrency": {"amount": 3.00}}
                        }
                    },
                    {
                        "valueObject": {
                            "Amount": {"valueCurrency": {"amount": 2.25}}
                        }
                    }
                ]
            }
        }
        result = _extract_tax_amount(fields)
        self.assertEqual(result, 5.25)
    
    def test_extract_tax_amount_missing(self):
        """Test tax extraction with no tax data."""
        fields = {}
        result = _extract_tax_amount(fields)
        self.assertIsNone(result)
    
    def test_extract_tax_rate_valid(self):
        """Test tax rate extraction with valid data."""
        fields = {
            "TaxDetails": {
                "valueArray": [
                    {
                        "valueObject": {
                            "Rate": {"valueNumber": 0.08}
                        }
                    }
                ]
            }
        }
        result = _extract_tax_rate(fields)
        self.assertEqual(result, 0.08)
    
    def test_extract_tax_rate_string_value(self):
        """Test tax rate extraction with string value."""
        fields = {
            "TaxDetails": {
                "valueArray": [
                    {
                        "valueObject": {
                            "Rate": {"valueString": "8.5"}
                        }
                    }
                ]
            }
        }
        result = _extract_tax_rate(fields)
        self.assertEqual(result, 8.5)
    
    def test_extract_tax_rate_missing(self):
        """Test tax rate extraction with no data."""
        fields = {}
        result = _extract_tax_rate(fields)
        self.assertIsNone(result)
    
    def test_extract_items_valid(self):
        """Test item extraction with valid data."""
        fields = {
            "Items": {
                "valueArray": [
                    {
                        "valueObject": {
                            "Description": {"valueString": "Apple"},
                            "Quantity": {"valueNumber": 2},
                            "QuantityUnit": {"valueString": "pieces"},
                            "Price": {"valueCurrency": {"amount": 1.50}},
                            "TotalPrice": {"valueCurrency": {"amount": 3.00}},
                            "ProductCode": {"valueString": "APPLE001"}
                        }
                    }
                ]
            }
        }
        
        result = _extract_items(fields)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["description"], "Apple")
        self.assertEqual(result[0]["quantity"], Decimal('2.00'))
        self.assertEqual(result[0]["quantity_unit"], "pieces")
        self.assertEqual(result[0]["price"], Decimal('1.50'))
        self.assertEqual(result[0]["total_price"], Decimal('3.00'))
        self.assertEqual(result[0]["product_id"], "APPLE001")
    
    def test_extract_items_total_price_fallback(self):
        """Test item extraction with TotalPrice fallback to Price."""
        fields = {
            "Items": {
                "valueArray": [
                    {
                        "valueObject": {
                            "Description": {"valueString": "Banana"},
                            "Quantity": {"valueNumber": 1},
                            "Price": {"valueCurrency": {"amount": 2.50}},
                            "ProductCode": {"valueString": "BANANA001"}
                        }
                    }
                ]
            }
        }
        
        result = _extract_items(fields)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["description"], "Banana")
        self.assertEqual(result[0]["quantity"], Decimal('1.00'))
        self.assertEqual(result[0]["price"], Decimal('2.50'))
        self.assertEqual(result[0]["total_price"], Decimal('2.50'))  # Should fallback to price
    
    def test_extract_items_decimal_quantity(self):
        """Test item extraction with decimal quantity that needs rounding."""
        fields = {
            "Items": {
                "valueArray": [
                    {
                        "valueObject": {
                            "Description": {"valueString": "Oranges"},
                            "Quantity": {"valueNumber": 2.555},  # Should round to 2.56
                            "QuantityUnit": {"valueString": "lbs"},
                            "Price": {"valueCurrency": {"amount": 3.99}},
                            "TotalPrice": {"valueCurrency": {"amount": 10.19}},
                            "ProductCode": {"valueString": "ORANGE001"}
                        }
                    }
                ]
            }
        }
        
        result = _extract_items(fields)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["description"], "Oranges")
        self.assertEqual(result[0]["quantity"], Decimal('2.56'))  # Rounded to 2 decimal places
        self.assertEqual(result[0]["quantity_unit"], "lbs")
        self.assertEqual(result[0]["price"], Decimal('3.99'))
        self.assertEqual(result[0]["total_price"], Decimal('10.19'))
        self.assertEqual(result[0]["product_id"], "ORANGE001")
    
    def test_round_quantity_function(self):
        """Test the _round_quantity helper function."""
        # Test normal rounding
        self.assertEqual(_round_quantity(2.555), Decimal('2.56'))
        self.assertEqual(_round_quantity(1.234), Decimal('1.23'))
        self.assertEqual(_round_quantity(5.0), Decimal('5.00'))
        
        # Test None input
        self.assertIsNone(_round_quantity(None))
        
        # Test edge cases
        self.assertEqual(_round_quantity(0.125), Decimal('0.13'))  # ROUND_HALF_UP
        self.assertEqual(_round_quantity(0.124), Decimal('0.12'))

    def test_extract_items_empty(self):
        """Test item extraction with no items."""
        fields = {}
        result = _extract_items(fields)
        self.assertEqual(result, [])
    
    def test_build_serializer_dict_no_documents(self):
        """Test build_serializer_dict with no documents."""
        mock_result = Mock()
        mock_result.documents = []
        
        with self.assertRaises(ValueError) as context:
            _build_serializer_dict(mock_result)
        
        self.assertIn("No receipt document detected", str(context.exception))
    
    def test_build_serializer_dict_company_fallback(self):
        """Test company extraction with fallback to content field."""
        mock_result = Mock()
        mock_result.documents = [Mock()]
        mock_result.documents[0].fields = {
            "MerchantName": {"content": "Fallback Store Name"},
            "MerchantAddress": {"content": "123 Test St"},
            "TransactionDate": {"valueDate": "2023-12-25"},
            "TransactionTime": {"valueTime": "14:30:00"},
            "Total": {"valueCurrency": {"amount": 25.99, "currencySymbol": "$", "currencyCode": "USD"}},
            "Items": {"valueArray": []}
        }
        
        result = _build_serializer_dict(mock_result)
        
        self.assertEqual(result["company"], "Fallback Store Name")
    
    def test_build_serializer_dict_valid_complete(self):
        """Test build_serializer_dict with complete valid data."""
        mock_result = Mock()
        mock_result.documents = [Mock()]
        mock_result.documents[0].fields = {
            "MerchantName": {"valueString": "Test Store"},
            "MerchantAddress": {"content": "123 Test St"},
            "CountryRegion": {"valueCountryRegion": "US"},
            "MerchantPhoneNumber": {"valuePhoneNumber": "+1234567890"},
            "TransactionDate": {"valueDate": "2023-12-25"},
            "TransactionTime": {"valueTime": "14:30:00"},
            "Subtotal": {"valueCurrency": {"amount": 20.00}},
            "TotalTax": {"valueCurrency": {"amount": 2.00}},
            "Total": {"valueCurrency": {"amount": 25.99, "currencySymbol": "$", "currencyCode": "USD"}},
            "Tip": {"valueCurrency": {"amount": 3.99}},
            "ReceiptType": {"valueString": "itemized"},
            "TaxDetails": {
                "valueArray": [
                    {
                        "valueObject": {
                            "Rate": {"valueNumber": 0.08}
                        }
                    }
                ]
            },
            "Items": {"valueArray": []}
        }
        
        result = _build_serializer_dict(mock_result)
        
        # Test all fields are present and correct
        self.assertEqual(result["company"], "Test Store")
        self.assertEqual(result["address"], "123 Test St")
        self.assertEqual(result["country_region"], "US")
        self.assertEqual(result["company_phone"], "+1234567890")
        self.assertEqual(result["date"], date(2023, 12, 25))
        self.assertEqual(result["time"], time(14, 30, 0))
        self.assertEqual(result["sub_total"], Decimal('20.00'))
        self.assertEqual(result["tax"], Decimal('2.00'))
        self.assertEqual(result["tax_rate"], Decimal('0.08'))
        self.assertEqual(result["total"], Decimal('25.99'))
        self.assertEqual(result["tip"], Decimal('3.99'))
        self.assertEqual(result["receipt_currency_symbol"], "$")
        self.assertEqual(result["receipt_currency_code"], "USD")
        self.assertEqual(result["item_count"], 0)
        self.assertEqual(result["items"], []) 