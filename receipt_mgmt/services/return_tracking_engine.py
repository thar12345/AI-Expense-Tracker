import json
import logging
from datetime import datetime, date
from typing import Dict
import base64
import openai
from ..models import Receipt, Item
from django.db import connection, DatabaseError

logger = logging.getLogger(__name__)


def process_return_receipt(parsed_data: Dict) -> Dict:
    """
    Process return receipt by converting positive amounts to negative if all amounts are positive.
    If any amounts are already negative, don't modify anything.
    
    Args:
        parsed_data: Dictionary containing parsed receipt data
        
    Returns:
        Dictionary with potentially modified amounts for return receipts
    """
    # Fields to check for amounts in the main receipt
    amount_fields = ['sub_total', 'tax', 'total', 'tip']
    
    # Collect all amounts from the main receipt
    main_amounts = []
    for field in amount_fields:
        value = parsed_data.get(field)
        if value is not None:
            main_amounts.append(value)
    
    # Collect all item amounts
    item_amounts = []
    items = parsed_data.get('items', [])
    for item in items:
        price = item.get('price')
        total_price = item.get('total_price')
        if price is not None:
            item_amounts.append(price)
        if total_price is not None:
            item_amounts.append(total_price)
    
    # Combine all amounts
    all_amounts = main_amounts + item_amounts
    
    # Check if we have any amounts to process
    if not all_amounts:
        logger.info("No amounts found in receipt data, skipping return processing")
        return parsed_data
    
    # Check if any amounts are already negative
    has_negative_amounts = any(amount < 0 for amount in all_amounts)
    
    if has_negative_amounts:
        logger.info("Return receipt already contains negative amounts, leaving as-is")
        return parsed_data
    
    # All amounts are positive, so convert them to negative
    logger.info("Converting all positive amounts to negative for return receipt")
    
    # Convert main receipt amounts
    for field in amount_fields:
        if parsed_data.get(field) is not None:
            parsed_data[field] = -abs(parsed_data[field])
    
    # Convert item amounts
    for item in items:
        if item.get('price') is not None:
            item['price'] = -abs(item['price'])
        if item.get('total_price') is not None:
            item['total_price'] = -abs(item['total_price'])
    
    return parsed_data


def analyze_receipt_returns(receipt: Receipt, receipt_image: bytes = None, receipt_email: str = None, content_type: str = None) -> Dict[str, any]:
    """
    Analyze return policy for all items in a receipt and save return dates to database.
    
    Args:
        receipt: Receipt instance with items to analyze
        receipt_image: Optional raw image data in bytes (takes precedence over receipt raw data)
        receipt_email: Optional raw email content as string (takes precedence over receipt raw data)
        content_type: MIME type of the image (required if receipt_image provided)
        
    Returns:
        Dict containing:
        - 'success_count': int - number of items updated with return dates
        - 'total_count': int - total number of items processed
        - 'success_rate': str - percentage of items that got return dates
        - 'failed_items': list - items that failed to get return dates
    """
    items = list(receipt.items.all())
    
    if not items:
        logger.warning(f"No items found for receipt {receipt.id}")
        return {
            'success_count': 0,
            'total_count': 0,
            'success_rate': '0.0%',
            'failed_items': []
        }
    
    # Validate image parameters
    if receipt_image and not content_type:
        logger.error(f"Receipt {receipt.id}: content_type is required when receipt_image is provided")
        return {
            'success_count': 0,
            'total_count': len(items),
            'success_rate': '0.0%',
            'failed_items': [item.id for item in items]
        }
    
    try:
        # Data source handling with explicit precedence
        # 1. Raw image bytes (highest priority)
        if receipt_image and content_type:
            logger.info(f"Receipt {receipt.id}: Using provided image data for return analysis")
            analysis_result = _analyze_return_policy(
                receipt=receipt,
                image_data=receipt_image,
                content_type=content_type,
                email_content=None
            )
        # 2. Email content (from parameter or receipt model)
        elif receipt_email or receipt.raw_email:
            email_content = receipt_email or receipt.raw_email
            logger.info(f"Receipt {receipt.id}: Using email content for return analysis")
            analysis_result = _analyze_return_policy(
                receipt=receipt,
                image_data=None,
                content_type=None,
                email_content=email_content
            )
        # 3. Metadata-only analysis (last resort)
        else:
            logger.info(f"Receipt {receipt.id}: Using metadata-only analysis for return policy")
            analysis_result = _analyze_return_policy(
                receipt=receipt,
                image_data=None,
                content_type=None,
                email_content=None
            )
        
        # Process analysis results
        if not analysis_result or not analysis_result.get('items'):
            logger.warning(f"Receipt {receipt.id}: Return policy analysis returned no data")
            return {
                'success_count': 0,
                'total_count': len(items),
                'success_rate': '0.0%',
                'failed_items': [item.id for item in items]
            }
        
        # Update items with return dates
        success_count = 0
        failed_items = []
        items_to_update = []
        
        # Create a mapping of item names to items for matching
        item_name_map = {item.description.lower().strip(): item for item in items}
        
        for result_item in analysis_result['items']:
            item_name = result_item.get('name', '').lower().strip()
            return_date_str = result_item.get('return_date')
            
            # Find matching item
            matched_item = item_name_map.get(item_name)
            if not matched_item:
                # Try partial matching
                for db_item in items:
                    if item_name in db_item.description.lower() or db_item.description.lower() in item_name:
                        matched_item = db_item
                        break
            
            if matched_item and return_date_str:
                try:
                    # Handle unlimited returns
                    if return_date_str == '9999-12-31':
                        matched_item.returnable_by_date = date(9999, 12, 31)
                        logger.info(f"Item {matched_item.id} ({matched_item.description}) set to unlimited return")
                    else:
                        matched_item.returnable_by_date = datetime.strptime(return_date_str, '%Y-%m-%d').date()
                        logger.info(f"Item {matched_item.id} ({matched_item.description}) return date set to {return_date_str}")
                    
                    items_to_update.append(matched_item)
                    success_count += 1
                    
                except ValueError as e:
                    logger.error(f"Receipt {receipt.id}: Invalid date format '{return_date_str}' for item {matched_item.id}: {e}")
                    failed_items.append(matched_item.id)
            else:
                if matched_item:
                    logger.warning(f"Receipt {receipt.id}: No return date found for item {matched_item.id} ({matched_item.description})")
                    failed_items.append(matched_item.id)
        
        # Bulk update items. If the connection is lost or bulk_update fails, fall back to individual saves.
        if items_to_update:
            try:
                # Ensure DB connection is alive
                connection.ensure_connection()

                Item.objects.bulk_update(items_to_update, ['returnable_by_date'])
                logger.info(f"Receipt {receipt.id}: Bulk updated {len(items_to_update)} items with return dates")

            except DatabaseError as db_err:
                # Log and fall back to saving each item individually
                logger.warning(
                    f"Receipt {receipt.id}: bulk_update failed ({db_err}); falling back to individual updates"
                )
                for itm in items_to_update:
                    try:
                        itm.save(update_fields=['returnable_by_date'])
                    except Exception as ind_err:
                        logger.error(
                            f"Receipt {receipt.id}: Failed to save item {itm.id} individually: {ind_err}"
                        )
                        failed_items.append(itm.id)
        
        # Calculate success rate
        success_rate = (success_count / len(items)) * 100 if items else 0
        success_rate_str = f"{success_rate:.1f}%"
        
        logger.info(f"Receipt {receipt.id}: Return analysis complete - {success_count}/{len(items)} items ({success_rate_str}) got return dates")
        
        return {
            'success_count': success_count,
            'total_count': len(items),
            'success_rate': success_rate_str,
            'failed_items': failed_items
        }
        
    except Exception as e:
        logger.error(f"Receipt {receipt.id}: Error analyzing return policy: {e}")
        return {
            'success_count': 0,
            'total_count': len(items),
            'success_rate': '0.0%',
            'failed_items': [item.id for item in items]
        }


def _analyze_return_policy(receipt: Receipt, image_data: bytes = None, content_type: str = None, email_content: str = None) -> Dict:
    """
    Analyze return policy using OpenAI with explicit data source handling.
    
    Args:
        receipt: Receipt instance
        image_data: Raw image bytes (highest priority)
        content_type: MIME type for image
        email_content: Email content text
        
    Returns:
        Dict with 'items' list containing return policy analysis
    """
    try:
        # Create receipt metadata string
        receipt_metadata = f"Receipt from {receipt.company} on {receipt.date}"
        if receipt.country_region:
            receipt_metadata += f" in {receipt.country_region}"
        
        # Extract item descriptions from the receipt
        items = list(receipt.items.all())
        item_descriptions = [item.description for item in items]

        # Create user prompt
        user_prompt = _create_return_policy_prompt(
            item_descriptions=item_descriptions,
            image_data=image_data,
            content_type=content_type,
            email_content=email_content,
            receipt_metadata=receipt_metadata
        )
        
        # Build messages
        messages = [
            {"role": "system", "content": _get_system_prompt()},
            {"role": "user", "content": user_prompt}
        ]
        
        # Get response schema
        response_schema = _get_return_policy_response_schema()
        
        # Call OpenAI API
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "return_policy_analysis",
                    "schema": response_schema,
                    # Set strict to False to allow optional fields like 'return_date'
                    "strict": False
                }
            }
        )
        
        response_content = response.choices[0].message.content.strip()
        logger.info(f"Receipt {receipt.id}: OpenAI response received")
        
        # Parse response
        result = json.loads(response_content)
        
        # Filter out items with null or invalid return dates
        valid_items = []
        for item in result.get('items', []):
            return_date = item.get('return_date')
            if return_date and return_date != 'null':
                # Validate date format
                try:
                    if return_date == '9999-12-31':
                        # Special case for unlimited returns
                        valid_items.append(item)
                    else:
                        # Try to parse the date to validate format
                        datetime.strptime(return_date, '%Y-%m-%d')
                        valid_items.append(item)
                except ValueError:
                    # Invalid date format, skip this item
                    logger.warning(f"Receipt {receipt.id}: Skipping item with invalid date format: {return_date}")
                    continue
        
        return {'items': valid_items}
        
    except json.JSONDecodeError as e:
        logger.error(f"Receipt {receipt.id}: Failed to parse JSON response from OpenAI: {e}")
        return {'items': []}
    except Exception as e:
        logger.error(f"Receipt {receipt.id}: OpenAI API error: {e}")
        return {'items': []}


def _create_return_policy_prompt(item_descriptions: list, image_data: bytes = None, content_type: str = None, email_content: str = None, receipt_metadata: str = None) -> any:
    """
    Create the prompt for return policy analysis based on available data.
    
    Args:
        image_data: Raw image bytes
        content_type: MIME type for image
        email_content: Email content text
        receipt_metadata: Receipt metadata string
        item_descriptions: List of item descriptions for metadata-only analysis
        
    Returns:
        Prompt content (string or list for vision)
    """
    items_list_str = "\\n".join(f"- {item}" for item in item_descriptions)
    items_prompt_part = f"The items on this receipt are:\\n{items_list_str}"

    base_prompt = f"""
Analyze this receipt and determine the return deadline for each of the specific items listed below.

{items_prompt_part}

{receipt_metadata}

Please examine the receipt data you have been given (image, email, or just metadata). Your task is to provide a return date for EACH of the items from the list above.

- Match the return information to the specific items from the provided list.
- Your response MUST include an object for every single item in the list.
- If you can confidently determine a return date, provide it in 'YYYY-MM-DD' format.
- Use '9999-12-31' for items with an unlimited return policy.
- If you cannot determine a return date for a specific item, return the item object without the 'return_date' field.
- If you are unsure about the return date, return the item object without the 'return_date' field.
"""
    
    # Image data takes precedence
    if image_data and content_type:
        base64_image = base64.b64encode(image_data).decode("utf-8")
        return [
            {"type": "text", "text": f"{base_prompt}\\n\\nAnalyze the following receipt image:"},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{content_type};base64,{base64_image}",
                    "detail": "high"
                }
            }
        ]
    
    # Email content
    elif email_content:
        return f"{base_prompt}\\n\\n--- EMAIL RECEIPT CONTENT ---\\n{email_content}"
    
    # Metadata only
    else:
        return f"{base_prompt}\\n\\nNote: Only receipt metadata and the item list are available. Provide your best estimate based on the store, items, and general retail policies."


def _get_system_prompt() -> str:
    """Get the system prompt for return policy analysis."""
    return """You are a professional retail return policy analyst. Your task is to analyze receipt information and determine the return deadline for a specific list of items.

- Your analysis must be conservative: Only provide dates when you are confident.
- Be accurate: Use store-specific policies when known.
- Be consistent: Always provide dates in 'YYYY-MM-DD' format.
- For unlimited returns (like at Costco or Nordstrom), use the date '9999-12-31'.

You will be given a list of items. Your JSON response must contain an array with an object for each item in that list.
If you can determine a return date, include the 'return_date' field.
If you cannot determine a return date for an item, omit the 'return_date' field for that item's object. Do not guess."""


def _get_return_policy_response_schema() -> Dict:
    """Get the JSON schema for structured OpenAI response."""
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Item name or description. This MUST exactly match one of the items from the prompt."
                        },
                        "return_date": {
                            "type": "string",
                            "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                            "description": "Return deadline in YYYY-MM-DD format, or 9999-12-31 for unlimited. Omit if unknown."
                        }
                    },
                    "required": ["name"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["items"],
        "additionalProperties": False
    } 
    