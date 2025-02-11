import json
import logging
from collections import Counter
from typing import List, Dict, Optional

import openai
from django.conf import settings

from receipt_mgmt.models import Receipt, Item

logger = logging.getLogger(__name__)

def categorize_receipt_items(receipt: Receipt) -> Dict[str, any]:
    """
    Use OpenAI GPT-4o-mini to categorize each item in a receipt based on description and product_id.
    Then set the receipt category to the mode (most common) of all item categories.
    
    Args:
        receipt: Receipt instance with items to categorize
        
    Returns:
        Dict containing:
        - 'items_updated': int - number of items updated
        - 'receipt_category_changed': bool - whether receipt category was changed
        - 'old_receipt_category': int - original receipt category
        - 'new_receipt_category': int - new receipt category
        - 'category_distribution': dict - count of each category found
    """
    
    # Get all items for this receipt
    items = receipt.items.all()
    
    if not items.exists():
        logger.info(f"No items found for receipt {receipt.id}, setting category to Other")
        
        old_receipt_category = receipt.receipt_type
        new_receipt_category = Receipt.ReceiptType.OTHER
        
        receipt_category_changed = False
        if old_receipt_category != new_receipt_category:
            receipt.receipt_type = new_receipt_category
            receipt.save()
            receipt_category_changed = True
            logger.info(f"Receipt {receipt.id}: Set category to Other (no items)")
        
        return {
            'items_updated': 0,
            'receipt_category_changed': receipt_category_changed,
            'old_receipt_category': old_receipt_category,
            'new_receipt_category': new_receipt_category,
            'category_distribution': {},
            'categorization_method': 'no_items'
        }
    
    # Prepare items data for OpenAI
    items_data = []
    for item in items:
        items_data.append({
            'id': item.id,
            'description': item.description or 'Unknown',
            'product_id': item.product_id or '',
        })
    
    # Get category mappings for the prompt
    category_mappings = _get_category_mappings()
    
    try:
        # Call OpenAI to categorize items
        categorized_items = _call_openai_for_categorization(items_data, category_mappings)
        
        # Update items with new categories
        items_updated = 0
        new_categories = []
        items_to_update = []
        
        for item_data in categorized_items:
            try:
                item = Item.objects.get(id=item_data['id'])
                old_category = item.item_category
                new_category = item_data['category']
                
                if old_category != new_category:
                    item.item_category = new_category
                    items_to_update.append(item)
                    items_updated += 1
                    
                new_categories.append(new_category)
                
            except Item.DoesNotExist:
                logger.error(f"Item with ID {item_data['id']} not found")
                continue
        
        # Bulk update all items in a single query for better performance
        if items_to_update:
            Item.objects.bulk_update(items_to_update, ['item_category'])
        
        # Calculate category distribution
        category_distribution = dict(Counter(new_categories))
        
        # Set receipt category to the mode (most common category)
        old_receipt_category = receipt.receipt_type
        new_receipt_category = _get_mode_category(new_categories)
        
        receipt_category_changed = False
        if new_receipt_category and old_receipt_category != new_receipt_category:
            receipt.receipt_type = new_receipt_category
            receipt.save()
            receipt_category_changed = True
            
        logger.info(f"Receipt {receipt.id}: Updated {items_updated} items, "
                   f"receipt category {'changed' if receipt_category_changed else 'unchanged'}")
        
        return {
            'items_updated': items_updated,
            'receipt_category_changed': receipt_category_changed,
            'old_receipt_category': old_receipt_category,
            'new_receipt_category': new_receipt_category or old_receipt_category,
            'category_distribution': category_distribution,
            'categorization_method': 'item_analysis'
        }
        
    except Exception as e:
        logger.error(f"Error categorizing receipt {receipt.id}: {str(e)}")
        return {
            'items_updated': 0,
            'receipt_category_changed': False,
            'old_receipt_category': receipt.receipt_type,
            'new_receipt_category': receipt.receipt_type,
            'category_distribution': {},
            'error': str(e)
        }


def _get_category_mappings() -> str:
    """Get formatted string of category mappings for the OpenAI prompt."""
    mappings = []
    for choice in Receipt.ReceiptType.choices:
        mappings.append(f"{choice[0]}={choice[1]}")
    return ", ".join(mappings)


def _call_openai_for_categorization(items_data: List[Dict], category_mappings: str) -> List[Dict]:
    """
    Call OpenAI GPT-4o-mini to categorize items using structured output.
    
    Args:
        items_data: List of item dictionaries with id, description, product_id
        category_mappings: String of category mappings for the prompt
        
    Returns:
        List of dictionaries with id and category for each item
    """
    
    # Define the JSON schema for structured output
    response_schema = {
        "type": "object",
        "properties": {
            "categorized_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "integer",
                            "description": "The item ID"
                        },
                        "category": {
                            "type": "integer",
                            "description": "The category integer (1-17)",
                            "enum": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
                        }
                    },
                    "required": ["id", "category"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["categorized_items"],
        "additionalProperties": False
    }
    
    # Create the improved prompt
    system_prompt = f"""You are an expert at categorizing shopping items into spending categories.

Available categories: {category_mappings}

Analyze each item's description and product_id to determine the most appropriate category.

Categorization Guidelines:
1. Groceries (1): Food items, beverages, household consumables
2. Apparel (2): Clothing, shoes, accessories, jewelry
3. Dining Out (3): Restaurant meals, takeout, food delivery
4. Electronics (4): Gadgets, computers, phones, tech accessories
5. Supplies (5): Office supplies, school supplies, general supplies
6. Healthcare (6): Medicine, medical supplies, health products
7. Home (7): Furniture, home decor, household items, appliances
8. Utilities (8): Electric, gas, water, internet, phone bills
9. Transportation (9): Gas, car maintenance, public transit, rideshare
10. Insurance (10): Health, car, home, life insurance
11. Personal Care (11): Cosmetics, toiletries, grooming products
12. Subscriptions (12): Streaming services, magazines, software subscriptions
13. Entertainment (13): Movies, games, books, hobbies, sports
14. Education (14): Books, courses, school supplies, tuition
15. Pets (15): Pet food, toys, veterinary, pet supplies
16. Travel (16): Hotels, flights, vacation expenses
17. Other (17): Items that don't fit other categories

For each item, consider:
- Primary purpose and use case
- Where it would typically be purchased
- What expense category it represents for budgeting

If uncertain, use category 17 (Other)."""

    user_prompt = f"Categorize these items:\n{json.dumps(items_data, indent=2)}"
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,  # Low temperature for consistent categorization
            max_tokens=1000,  # Reduced since no reasoning needed
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "item_categorization",
                    "schema": response_schema,
                    "strict": True
                }
            }
        )
        
        # Parse the structured response
        response_content = response.choices[0].message.content.strip()
        parsed_response = json.loads(response_content)
        
        # Extract the categorized items from the structured response
        categorized_items = parsed_response["categorized_items"]
        
        # Log successful categorization
        logger.info(f"OpenAI successfully categorized {len(categorized_items)} items")
        
        # Return the categorized items directly (already in correct format)
        return categorized_items
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI structured response: {e}")
        logger.error(f"Response content: {response_content}")
        raise
        
    except KeyError as e:
        logger.error(f"Missing expected key in structured response: {e}")
        logger.error(f"Response content: {response_content}")
        raise
        
    except Exception as e:
        logger.error(f"OpenAI API call failed: {e}")
        raise


def _get_mode_category(categories: List[int]) -> Optional[int]:
    """
    Get the mode (most common) category from a list of categories.
    
    Args:
        categories: List of category integers
        
    Returns:
        Most common category integer, or None if list is empty
    """
    if not categories:
        return None
        
    # Count occurrences of each category
    category_counts = Counter(categories)
    
    # Return the most common category
    # In case of tie, Counter.most_common() returns the first one encountered
    most_common = category_counts.most_common(1)
    return most_common[0][0] if most_common else None
