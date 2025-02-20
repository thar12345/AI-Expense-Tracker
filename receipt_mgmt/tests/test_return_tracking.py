"""
Comprehensive tests for return tracking functionality.
"""

import json
import pytest
from decimal import Decimal
from datetime import date, datetime
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from receipt_mgmt.models import Receipt, Item
from receipt_mgmt.services.return_tracking_engine import (
    process_return_receipt,
    analyze_receipt_returns,
    _analyze_return_policy,
    _create_return_policy_prompt,
    _get_system_prompt,
    _get_return_policy_response_schema
)

pytestmark = pytest.mark.django_db

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user():
    """Create a test user."""
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )


@pytest.fixture
def receipt(user):
    """Create a test receipt."""
    return Receipt.objects.create(
        user=user,
        company='Test Store',
        date=date(2024, 1, 15),
        total=Decimal('99.99'),
        receipt_type=1,
        raw_email='test receipt data'
    )


@pytest.fixture
def items(receipt):
    """Create test items for the receipt."""
    return [
        Item.objects.create(
            receipt=receipt,
            description='Test Item 1',
            quantity=1,
            total_price=Decimal('29.99')
        ),
        Item.objects.create(
            receipt=receipt,
            description='Test Item 2',
            quantity=2,
            total_price=Decimal('35.00')
        )
    ]


# ---------------------------------------------------------------------------
# Process Return Receipt Tests
# ---------------------------------------------------------------------------

def test_process_return_receipt_all_positive_amounts():
    """Test converting all positive amounts to negative."""
    parsed_data = {
        'items': [
            {'name': 'Item 1', 'quantity': 1, 'price': 29.99},
            {'name': 'Item 2', 'quantity': 2, 'price': 35.00}
        ],
        'total': 64.99
    }
    
    result = process_return_receipt(parsed_data)
    
    # All amounts should be negative
    assert result['total'] == -64.99
    assert result['items'][0]['price'] == -29.99
    assert result['items'][1]['price'] == -35.00


def test_process_return_receipt_mixed_amounts():
    """Test handling mixed positive and negative amounts."""
    parsed_data = {
        'items': [
            {'name': 'Item 1', 'quantity': 1, 'price': 29.99},
            {'name': 'Item 2', 'quantity': 2, 'price': -35.00}
        ],
        'total': -5.01
    }
    
    result = process_return_receipt(parsed_data)
    
    # If ANY amount is negative, leave ALL amounts unchanged
    assert result['total'] == -5.01  # unchanged
    assert result['items'][0]['price'] == 29.99  # unchanged (stays positive)
    assert result['items'][1]['price'] == -35.00  # unchanged (stays negative)


def test_process_return_receipt_all_negative_amounts():
    """Test handling all negative amounts."""
    parsed_data = {
        'items': [
            {'name': 'Item 1', 'quantity': 1, 'price': -29.99},
            {'name': 'Item 2', 'quantity': 2, 'price': -35.00}
        ],
        'total': -64.99
    }
    
    result = process_return_receipt(parsed_data)
    
    # All amounts should remain negative
    assert result['total'] == -64.99
    assert result['items'][0]['price'] == -29.99
    assert result['items'][1]['price'] == -35.00


def test_process_return_receipt_zero_amounts():
    """Test handling zero amounts."""
    parsed_data = {
        'items': [
            {'name': 'Item 1', 'quantity': 1, 'price': 0.00},
            {'name': 'Item 2', 'quantity': 2, 'price': -35.00}
        ],
        'total': -35.00
    }
    
    result = process_return_receipt(parsed_data)
    
    # Zero amounts should remain zero
    assert result['total'] == -35.00
    assert result['items'][0]['price'] == 0.00
    assert result['items'][1]['price'] == -35.00


# ---------------------------------------------------------------------------
# Analyze Receipt Returns Tests
# ---------------------------------------------------------------------------

def test_analyze_receipt_returns_with_image_bytes(receipt, items):
    """Test analyzing returns with image bytes."""
    image_bytes = b'fake_image_data'
    content_type = 'image/jpeg'
    
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '2024-02-15'},
                {'name': 'Test Item 2', 'return_date': '2024-02-20'}
            ]
        }
        
        result = analyze_receipt_returns(
            receipt=receipt,
            receipt_image=image_bytes,
            content_type=content_type
        )
        
        # Should use image data
        mock_analyze.assert_called_once()
        call_args = mock_analyze.call_args
        assert call_args[1]['image_data'] == image_bytes
        assert call_args[1]['content_type'] == content_type
        assert call_args[1]['email_content'] is None
        
        # Should return success info
        assert result['success_count'] == 2
        assert result['total_count'] == 2
        assert result['success_rate'] == '100.0%'


def test_analyze_receipt_returns_with_email_content(receipt, items):
    """Test analyzing returns with email content."""
    email_content = "Return policy: 30 days"
    
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '2024-02-15'}
            ]
        }
        
        result = analyze_receipt_returns(
            receipt=receipt,
            receipt_email=email_content
        )
        
        # Should use email content
        mock_analyze.assert_called_once()
        call_args = mock_analyze.call_args
        assert call_args[1]['email_content'] == email_content
        assert call_args[1]['image_data'] is None
        
        # Should return success info
        assert result['success_count'] == 1
        assert result['total_count'] == 2
        assert result['success_rate'] == '50.0%'


def test_analyze_receipt_returns_fallback_to_receipt_email(receipt, items):
    """Test falling back to receipt email content."""
    receipt.raw_email = "Receipt email content"
    receipt.save()
    
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '2024-02-15'}
            ]
        }
        
        result = analyze_receipt_returns(receipt=receipt)
        
        # Should use receipt email content
        mock_analyze.assert_called_once()
        call_args = mock_analyze.call_args
        assert call_args[1]['email_content'] == "Receipt email content"
        assert call_args[1]['image_data'] is None


def test_analyze_receipt_returns_with_urls_only_now_works(receipt, items):
    """Test that function now works with URLs only (using metadata fallback)."""
    receipt.raw_images = ['https://example.com/image1.jpg', 'https://example.com/image2.jpg']
    receipt.raw_email = None  # Clear email content to force URL-only scenario
    receipt.save()
    
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '2024-02-15'}
            ]
        }
        
        result = analyze_receipt_returns(receipt=receipt)
        
        # Should use metadata-only analysis
        mock_analyze.assert_called_once()
        call_args = mock_analyze.call_args
        assert call_args[1]['email_content'] is None
        assert call_args[1]['image_data'] is None
        
        assert result['success_count'] == 1
        assert result['total_count'] == 2
        assert result['success_rate'] == '50.0%'


def test_analyze_receipt_returns_metadata_only_fallback(receipt, items):
    """Test metadata-only analysis as last resort."""
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '2024-02-15'}
            ]
        }
        
        result = analyze_receipt_returns(receipt=receipt)
        
        # Should use metadata only
        mock_analyze.assert_called_once()
        call_args = mock_analyze.call_args
        assert call_args[1]['email_content'] == "test receipt data"  # from fixture
        assert call_args[1]['image_data'] is None
        
        assert result['success_count'] == 1
        assert result['total_count'] == 2
        assert result['success_rate'] == '50.0%'


def test_analyze_receipt_returns_updates_items_in_database(receipt, items):
    """Test that items are updated in the database."""
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '2024-02-15'},
                {'name': 'Test Item 2', 'return_date': '2024-02-20'}
            ]
        }
        
        result = analyze_receipt_returns(receipt=receipt)
        
        # Check items were updated in database
        items[0].refresh_from_db()
        items[1].refresh_from_db()
        
        assert items[0].returnable_by_date == date(2024, 2, 15)
        assert items[1].returnable_by_date == date(2024, 2, 20)
        
        assert result['success_count'] == 2
        assert result['total_count'] == 2


def test_analyze_receipt_returns_partial_matches(receipt, items):
    """Test handling partial item matches."""
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '2024-02-15'},
                {'name': 'Unknown Item', 'return_date': '2024-02-20'}
            ]
        }
        
        result = analyze_receipt_returns(receipt=receipt)
        
        # Only one item should be updated
        items[0].refresh_from_db()
        items[1].refresh_from_db()
        
        assert items[0].returnable_by_date == date(2024, 2, 15)
        assert items[1].returnable_by_date is None
        
        assert result['success_count'] == 1
        assert result['total_count'] == 2
        assert result['success_rate'] == '50.0%'


# ---------------------------------------------------------------------------
# Analyze Return Policy Tests
# ---------------------------------------------------------------------------

@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_return_policy_with_image_data(mock_openai, receipt, items):
    """Test analyzing return policy with image data."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        'items': [
            {'name': 'Test Item 1', 'return_date': '2024-02-15'},
            {'name': 'Test Item 2', 'return_date': '2024-02-20'}
        ]
    })
    mock_openai.chat.completions.create.return_value = mock_response
    
    image_data = b'fake_image_data'
    content_type = 'image/jpeg'
    
    result = _analyze_return_policy(
        receipt=receipt,
        image_data=image_data,
        content_type=content_type,
        email_content=None
    )
    
    # Check OpenAI was called with image data
    mock_openai.chat.completions.create.assert_called_once()
    call_args = mock_openai.chat.completions.create.call_args
    
    # Should use vision model
    assert call_args[1]['model'] == 'gpt-4o'
    
    # Should have image in messages
    messages = call_args[1]['messages']
    user_message = messages[1]  # Second message should be user message
    assert isinstance(user_message['content'], list)
    assert user_message['content'][1]['type'] == 'image_url'
    
    assert result['items'][0]['name'] == 'Test Item 1'
    assert result['items'][0]['return_date'] == '2024-02-15'


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_return_policy_with_email_content(mock_openai, receipt, items):
    """Test analyzing return policy with email content."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        'items': [
            {'name': 'Test Item 1', 'return_date': '2024-02-15'}
        ]
    })
    mock_openai.chat.completions.create.return_value = mock_response
    
    email_content = "Return policy: 30 days from purchase"
    
    result = _analyze_return_policy(
        receipt=receipt,
        image_data=None,
        content_type=None,
        email_content=email_content
    )
    
    # Check OpenAI was called with email content
    mock_openai.chat.completions.create.assert_called_once()
    call_args = mock_openai.chat.completions.create.call_args
    
    # Should use text model
    assert call_args[1]['model'] == 'gpt-4o'
    
    # Should have email content in messages
    messages = call_args[1]['messages']
    user_message = messages[1]  # Second message should be user message
    assert email_content in user_message['content']
    
    assert result['items'][0]['name'] == 'Test Item 1'
    assert result['items'][0]['return_date'] == '2024-02-15'


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_return_policy_metadata_only(mock_openai, receipt, items):
    """Test analyzing return policy with metadata only."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        'items': [
            {'name': 'Test Item 1', 'return_date': '2024-02-15'}
        ]
    })
    mock_openai.chat.completions.create.return_value = mock_response
    
    result = _analyze_return_policy(
        receipt=receipt,
        image_data=None,
        content_type=None,
        email_content=None
    )
    
    # Check OpenAI was called with metadata
    mock_openai.chat.completions.create.assert_called_once()
    call_args = mock_openai.chat.completions.create.call_args
    
    # Should use text model
    assert call_args[1]['model'] == 'gpt-4o'
    
    # Should have receipt metadata in messages
    messages = call_args[1]['messages']
    user_message = messages[1]  # Second message should be user message
    assert 'Test Store' in user_message['content']
    assert '2024-01-15' in user_message['content']
    
    assert result['items'][0]['name'] == 'Test Item 1'
    assert result['items'][0]['return_date'] == '2024-02-15'


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_return_policy_openai_error(mock_openai, receipt, items):
    """Test handling OpenAI API errors."""
    mock_openai.chat.completions.create.side_effect = Exception("API Error")
    
    with patch('receipt_mgmt.services.return_tracking_engine.logger') as mock_logger:
        result = _analyze_return_policy(
            receipt=receipt,
            image_data=None,
            content_type=None,
            email_content=None
        )
        
        # Should log error and return empty result
        mock_logger.error.assert_called_once()
        assert "OpenAI API error" in mock_logger.error.call_args[0][0]
        
        assert result == {'items': []}


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_return_policy_json_parsing_error(mock_openai, receipt, items):
    """Test handling JSON parsing errors."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Invalid JSON response"
    mock_openai.chat.completions.create.return_value = mock_response
    
    with patch('receipt_mgmt.services.return_tracking_engine.logger') as mock_logger:
        result = _analyze_return_policy(
            receipt=receipt,
            image_data=None,
            content_type=None,
            email_content=None
        )
        
        # Should log error and return empty result
        mock_logger.error.assert_called_once()
        assert "Failed to parse JSON response" in mock_logger.error.call_args[0][0]
        
        assert result == {'items': []}


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_return_policy_invalid_date_format(mock_openai, receipt, items):
    """Test handling invalid date formats."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        'items': [
            {'name': 'Test Item 1', 'return_date': 'invalid-date'},
            {'name': 'Test Item 2', 'return_date': '2024-02-20'}
        ]
    })
    mock_openai.chat.completions.create.return_value = mock_response
    
    # Call the function directly
    result = _analyze_return_policy(
        receipt=receipt,
        image_data=None,
        content_type=None,
        email_content=None
    )
    
    # Should filter out invalid dates
    assert len(result['items']) == 1
    assert result['items'][0]['name'] == 'Test Item 2'
    assert result['items'][0]['return_date'] == '2024-02-20'


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_return_policy_unlimited_return_date(mock_openai, receipt, items):
    """Test handling unlimited return policies."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        'items': [
            {'name': 'Test Item 1', 'return_date': '9999-12-31'},
            {'name': 'Test Item 2', 'return_date': '2024-02-20'}
        ]
    })
    mock_openai.chat.completions.create.return_value = mock_response
    
    result = _analyze_return_policy(
        receipt=receipt,
        image_data=None,
        content_type=None,
        email_content=None
    )
    
    # Should handle unlimited return date
    assert result['items'][0]['name'] == 'Test Item 1'
    assert result['items'][0]['return_date'] == '9999-12-31'
    assert result['items'][1]['name'] == 'Test Item 2'
    assert result['items'][1]['return_date'] == '2024-02-20'


# ---------------------------------------------------------------------------
# Prompt and Schema Tests
# ---------------------------------------------------------------------------

def test_create_return_policy_prompt_with_image():
    """Test creating return policy prompt with image data."""
    image_data = b'fake_image_data'
    content_type = 'image/jpeg'
    item_descriptions = ["Test Item 1", "Test Item 2"]
    
    prompt = _create_return_policy_prompt(
        item_descriptions=item_descriptions,
        image_data=image_data,
        content_type=content_type,
        email_content=None,
        receipt_metadata="Receipt from Test Store"
    )
    
    assert len(prompt) == 2
    assert prompt[0]['type'] == 'text'
    assert 'return policy' in prompt[0]['text']
    assert prompt[1]['type'] == 'image_url'
    assert prompt[1]['image_url']['url'].startswith('data:image/jpeg;base64,')


def test_create_return_policy_prompt_with_email():
    """Test creating return policy prompt with email content."""
    email_content = "Return policy: 30 days from purchase"
    item_descriptions = ["Test Item 1", "Test Item 2"]
    
    prompt = _create_return_policy_prompt(
        item_descriptions=item_descriptions,
        image_data=None,
        content_type=None,
        email_content=email_content,
        receipt_metadata="Receipt from Test Store"
    )
    
    assert isinstance(prompt, str)
    assert 'return policy' in prompt
    assert email_content in prompt


def test_create_return_policy_prompt_metadata_only():
    """Test creating return policy prompt with metadata only."""
    receipt_metadata = "Receipt from Test Store on 2024-01-15"
    item_descriptions = ["Test Item 1", "Test Item 2"]
    
    prompt = _create_return_policy_prompt(
        item_descriptions=item_descriptions,
        image_data=None,
        content_type=None,
        email_content=None,
        receipt_metadata=receipt_metadata
    )
    
    assert isinstance(prompt, str)
    assert 'return policy' in prompt
    assert receipt_metadata in prompt


def test_get_system_prompt():
    """Test getting system prompt."""
    prompt = _get_system_prompt()
    
    assert 'return policy' in prompt
    assert 'JSON' in prompt
    assert 'items' in prompt


def test_get_return_policy_response_schema():
    """Test getting return policy response schema."""
    schema = _get_return_policy_response_schema()
    
    assert 'type' in schema
    assert schema['type'] == 'object'
    assert 'properties' in schema
    assert 'items' in schema['properties']
    assert 'items' in schema['properties']['items']


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_integration_image_data_flow(mock_openai, receipt, items):
    """Test complete flow with image data."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        'items': [
            {'name': 'Test Item 1', 'return_date': '2024-02-15'},
            {'name': 'Test Item 2', 'return_date': '2024-02-20'}
        ]
    })
    mock_openai.chat.completions.create.return_value = mock_response
    
    # Simulate stitched image data from receipt_upload_image_azure
    stitched_image_data = b'fake_stitched_image_data'
    
    result = analyze_receipt_returns(
        receipt=receipt,
        receipt_image=stitched_image_data,
        content_type='image/jpeg'
    )
    
    # Check OpenAI was called with image
    mock_openai.chat.completions.create.assert_called_once()
    call_args = mock_openai.chat.completions.create.call_args
    messages = call_args[1]['messages']
    user_message = messages[1]
    assert isinstance(user_message['content'], list)
    assert user_message['content'][1]['type'] == 'image_url'
    
    # Check database updates
    items[0].refresh_from_db()
    items[1].refresh_from_db()
    assert items[0].returnable_by_date == date(2024, 2, 15)
    assert items[1].returnable_by_date == date(2024, 2, 20)
    
    # Check result
    assert result['success_count'] == 2
    assert result['total_count'] == 2
    assert result['success_rate'] == '100.0%'


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_integration_email_content_flow(mock_openai, receipt, items):
    """Test complete flow with email content."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        'items': [
            {'name': 'Test Item 1', 'return_date': '2024-02-15'}
        ]
    })
    mock_openai.chat.completions.create.return_value = mock_response
    
    email_content = "Return policy: Items can be returned within 30 days of purchase"
    
    result = analyze_receipt_returns(
        receipt=receipt,
        receipt_email=email_content
    )
    
    # Check OpenAI was called with email content
    mock_openai.chat.completions.create.assert_called_once()
    call_args = mock_openai.chat.completions.create.call_args
    messages = call_args[1]['messages']
    user_message = messages[1]
    assert email_content in user_message['content']
    
    # Check database updates
    items[0].refresh_from_db()
    items[1].refresh_from_db()
    assert items[0].returnable_by_date == date(2024, 2, 15)
    assert items[1].returnable_by_date is None  # Not matched
    
    # Check result
    assert result['success_count'] == 1
    assert result['total_count'] == 2
    assert result['success_rate'] == '50.0%'


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_integration_error_handling_flow(mock_openai, receipt, items):
    """Test complete flow with error handling."""
    mock_openai.chat.completions.create.side_effect = Exception("API Error")
    
    with patch('receipt_mgmt.services.return_tracking_engine.logger') as mock_logger:
        result = analyze_receipt_returns(receipt=receipt)
        
        # Check error was logged
        mock_logger.error.assert_called_once()
        assert "OpenAI API error" in mock_logger.error.call_args[0][0]
        
        # Check no database updates
        items[0].refresh_from_db()
        items[1].refresh_from_db()
        assert items[0].returnable_by_date is None
        assert items[1].returnable_by_date is None
        
        # Check result
        assert result['success_count'] == 0
        assert result['total_count'] == 2
        assert result['success_rate'] == '0.0%'


# ---------------------------------------------------------------------------
# Additional Edge Case Tests
# ---------------------------------------------------------------------------

def test_analyze_receipt_returns_no_items(receipt):
    """Test analyzing returns when receipt has no items."""
    result = analyze_receipt_returns(receipt=receipt)
    
    assert result['success_count'] == 0
    assert result['total_count'] == 0
    assert result['success_rate'] == '0.0%'
    assert result['failed_items'] == []


def test_analyze_receipt_returns_image_without_content_type(receipt, items):
    """Test that function fails when image provided without content type."""
    image_bytes = b'fake_image_data'
    
    with patch('receipt_mgmt.services.return_tracking_engine.logger') as mock_logger:
        result = analyze_receipt_returns(
            receipt=receipt,
            receipt_image=image_bytes
            # Missing content_type
        )
        
        # Should log error and return failure
        mock_logger.error.assert_called_once()
        assert "content_type is required" in mock_logger.error.call_args[0][0]
        
        assert result['success_count'] == 0
        assert result['total_count'] == 2
        assert result['success_rate'] == '0.0%'


def test_analyze_receipt_returns_unlimited_return_dates(receipt, items):
    """Test handling unlimited return dates."""
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': '9999-12-31'},
                {'name': 'Test Item 2', 'return_date': '2024-02-20'}
            ]
        }
        
        result = analyze_receipt_returns(receipt=receipt)
        
        # Check items were updated in database
        items[0].refresh_from_db()
        items[1].refresh_from_db()
        
        # First item should have unlimited return date
        assert items[0].returnable_by_date == date(9999, 12, 31)
        assert items[1].returnable_by_date == date(2024, 2, 20)
        
        assert result['success_count'] == 2
        assert result['total_count'] == 2


def test_analyze_receipt_returns_invalid_date_during_update(receipt, items):
    """Test handling invalid dates during database update."""
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'Test Item 1', 'return_date': 'invalid-date-format'},
                {'name': 'Test Item 2', 'return_date': '2024-02-20'}
            ]
        }
        
        with patch('receipt_mgmt.services.return_tracking_engine.logger') as mock_logger:
            result = analyze_receipt_returns(receipt=receipt)
            
            # Should log error for invalid date
            mock_logger.error.assert_called()
            
            # Only valid item should be updated
            items[0].refresh_from_db()
            items[1].refresh_from_db()
            
            assert items[0].returnable_by_date is None  # Invalid date, not updated
            assert items[1].returnable_by_date == date(2024, 2, 20)
            
            assert result['success_count'] == 1
            assert result['total_count'] == 2
            assert result['success_rate'] == '50.0%'


def test_analyze_receipt_returns_partial_name_matching(receipt, items):
    """Test partial name matching for items."""
    # Update item descriptions to test partial matching
    items[0].description = "Apple iPhone 15 Pro Max"
    items[0].save()
    items[1].description = "Samsung Galaxy S24 Ultra"
    items[1].save()
    
    with patch('receipt_mgmt.services.return_tracking_engine._analyze_return_policy') as mock_analyze:
        mock_analyze.return_value = {
            'items': [
                {'name': 'iPhone 15', 'return_date': '2024-02-15'},  # Partial match
                {'name': 'Galaxy S24', 'return_date': '2024-02-20'}  # Partial match
            ]
        }
        
        result = analyze_receipt_returns(receipt=receipt)
        
        # Check partial matches worked
        items[0].refresh_from_db()
        items[1].refresh_from_db()
        
        assert items[0].returnable_by_date == date(2024, 2, 15)
        assert items[1].returnable_by_date == date(2024, 2, 20)
        
        assert result['success_count'] == 2
        assert result['total_count'] == 2


@patch('receipt_mgmt.services.return_tracking_engine.openai')
def test_analyze_receipt_returns_no_openai_client(mock_openai, receipt, items):
    """Test behavior when OpenAI API is not available."""
    mock_openai.chat.completions.create.side_effect = Exception("OpenAI API not available")
    
    with patch('receipt_mgmt.services.return_tracking_engine.logger') as mock_logger:
        result = analyze_receipt_returns(receipt=receipt)
        
        # Should log error about OpenAI API failure
        mock_logger.error.assert_called()
        assert "OpenAI API error" in mock_logger.error.call_args[0][0]
        
        assert result['success_count'] == 0
        assert result['total_count'] == 2
        assert result['success_rate'] == '0.0%'


def test_process_return_receipt_no_amounts():
    """Test process_return_receipt with no amount fields."""
    parsed_data = {
        'items': [],
        'company': 'Test Store'
        # No amount fields
    }
    
    result = process_return_receipt(parsed_data)
    
    # Should return unchanged data
    assert result == parsed_data


def test_process_return_receipt_with_null_amounts():
    """Test process_return_receipt with null amount fields."""
    parsed_data = {
        'items': [
            {'name': 'Item 1', 'quantity': 1, 'price': None},
            {'name': 'Item 2', 'quantity': 2, 'price': 35.00}
        ],
        'total': None,
        'sub_total': 35.00
    }
    
    result = process_return_receipt(parsed_data)
    
    # Only non-null amounts should be converted
    assert result['sub_total'] == -35.00
    assert result['total'] is None
    assert result['items'][0]['price'] is None
    assert result['items'][1]['price'] == -35.00


def test_get_return_policy_response_schema_structure():
    """Test that the response schema has correct structure."""
    schema = _get_return_policy_response_schema()
    
    # Validate schema structure
    assert schema['type'] == 'object'
    assert 'items' in schema['properties']
    assert schema['properties']['items']['type'] == 'array'
    
    item_schema = schema['properties']['items']['items']
    assert item_schema['type'] == 'object'
    assert 'name' in item_schema['properties']
    assert 'return_date' in item_schema['properties']
    assert item_schema['properties']['return_date']['pattern'] == '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'


def test_create_return_policy_prompt_edge_cases():
    """Test prompt creation with edge cases."""
    item_descriptions = ["Test Item 1", "Test Item 2"]
    
    # Test with empty receipt metadata
    prompt = _create_return_policy_prompt(
        item_descriptions=item_descriptions,
        image_data=None,
        content_type=None,
        email_content=None,
        receipt_metadata=""
    )
    
    assert isinstance(prompt, str)
    assert 'return policy' in prompt
    
    # Test with very long email content
    long_email = "A" * 10000
    prompt = _create_return_policy_prompt(
        item_descriptions=item_descriptions,
        image_data=None,
        content_type=None,
        email_content=long_email,
        receipt_metadata="Test"
    )
    
    assert isinstance(prompt, str)
    assert long_email in prompt