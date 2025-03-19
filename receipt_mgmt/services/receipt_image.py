import logging
import io
from typing import List

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from PIL import Image

from receipt_mgmt.models import Receipt
from receipt_mgmt.serializers import ReceiptCreateSerializer
from receipt_mgmt.services.img_receipt_engine import extract_receipt
from receipt_mgmt.signals import receipt_uploaded
from receipt_mgmt.utils.azure_utils import upload_receipt_image
from receipt_mgmt.services.spending_categorization import categorize_receipt_items
from receipt_mgmt.services.return_tracking_engine import process_return_receipt, analyze_receipt_returns

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def receipt_upload_image_azure(request):
    """
    Receives one or more images, stitches them together vertically,
    processes the stitched image through Azure Document Intelligence,
    saves the receipt to the database, uploads original images to Azure,
    and triggers background categorization.
    """
    # 1) Get all uploaded files
    files = request.FILES.getlist('receipt_images')
    if not files:
        logger.error("400 error in receipt_upload_image_azure: No 'receipt_images' file(s) found.")
        return Response(
            {"error": "No 'receipt_images' file(s) found in the request."},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = request.user
    if not user:
        logger.error("404 error in receipt_upload_image_azure: A user was not found.")
        return Response(
            {"error": "404 error in receipt_upload_image_azure: A user was not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    # Check if Azure Document Intelligence is configured
    if not settings.DOCUMENT_INTELLIGENCE_ENDPOINT or not settings.DOCUMENT_INTELLIGENCE_KEY:
        logger.error("Azure Document Intelligence is not configured")
        return Response(
            {"error": "Azure Document Intelligence is not configured. Please set DOCUMENT_INTELLIGENCE_ENDPOINT and DOCUMENT_INTELLIGENCE_KEY environment variables."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        # 2) Stitch images together vertically
        stitched_image_data = _stitch_images_vertically(files)
        
        # 3) Process stitched image through Azure Document Intelligence
        parsed_data = extract_receipt(
            stitched_image_data,
            endpoint=settings.DOCUMENT_INTELLIGENCE_ENDPOINT,
            key=settings.DOCUMENT_INTELLIGENCE_KEY
        )
        
        # 3.5) Handle return receipt logic
        is_return_receipt = request.data.get('is_return', False)
        if is_return_receipt:
            logger.info("Processing return receipt - checking if amounts need to be converted to negative")
            parsed_data = process_return_receipt(parsed_data)
        
        # 4) Validate the data and save the receipt
        serializer = ReceiptCreateSerializer(data=parsed_data)
        if not serializer.is_valid():
            logger.error(
                "400 error in receipt_upload_image_azure, serializer error: %s",
                serializer.errors
            )
            return Response(
                {"error": f"Serializer error: {serializer.errors}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the new Receipt
        new_receipt = serializer.save(user=user)
        
        # 5) Upload original images to Azure Blob Storage
        blob_names: List[str] = []
        for file_obj in files:
            file_obj.seek(0)  # Reset file pointer
            try:
                blob_name = upload_receipt_image(
                    image_data=file_obj.read(),
                    content_type=file_obj.content_type,
                    user_id=user.id,
                )
                blob_names.append(blob_name)
            except Exception as exc:
                logger.error("Azure upload failed: %s", exc)
                blob_names.append("upload_failed")  # sentinel

        # 6) Update the receipt's raw_images field
        new_receipt.raw_images = blob_names
        new_receipt.save(update_fields=["raw_images"])

        # 7) Categorize receipt items directly
        try:
            categorization_result = categorize_receipt_items(new_receipt)
            logger.info(f"Receipt {new_receipt.id} categorization completed: {categorization_result['items_updated']} items updated, "
                       f"receipt category {'changed' if categorization_result['receipt_category_changed'] else 'unchanged'}")
        except Exception as e:
            logger.error(f"Failed to categorize receipt {new_receipt.id}: {str(e)}")
            # Don't fail the request if categorization fails

        try:
            return_result = analyze_receipt_returns(new_receipt, receipt_image=stitched_image_data, content_type=files[0].content_type)
            logger.info(f"Receipt {new_receipt.id} return analysis completed: {return_result['success_count']} items updated, {return_result['total_count']} total items processed")
        except Exception as e:
            logger.error(f"Failed to analyze return receipt {new_receipt.id}: {str(e)}")
            # Don't fail the request if return analysis fails

        # 8) Signal receipt upload + send websocket notification
        receipt_uploaded.send(user=user, sender=Receipt, receipt_id=new_receipt.id)

        return Response(
            {
                "status": "success",
                "message": "Receipt processed and stored successfully.",
                "receipt_id": new_receipt.id,
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger.error(f"Error processing receipt images: {str(e)}")
        return Response(
            {"error": f"Error processing receipt: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _stitch_images_vertically(files) -> bytes:
    """
    Stitch multiple image files together vertically.
    
    Args:
        files: List of uploaded image files
        
    Returns:
        bytes: JPEG image data of the stitched image
        
    Raises:
        Exception: If image processing fails
    """
    try:
        # Load all images
        images = []
        for file_obj in files:
            file_obj.seek(0)  # Reset file pointer
            img = Image.open(io.BytesIO(file_obj.read()))
            # Convert to RGB if necessary (handles PNG with transparency, etc.)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            images.append(img)
        
        if not images:
            raise ValueError("No valid images to stitch")
        
        # If only one image, return it as-is
        if len(images) == 1:
            output = io.BytesIO()
            images[0].save(output, format='JPEG', quality=95)
            return output.getvalue()
        
        # Find the target width (minimum width among all images)
        target_width = min(img.width for img in images)
        
        # Resize all images to the same width while maintaining aspect ratio
        resized_images = []
        total_height = 0
        
        for img in images:
            resized_img = _resize_to_width(img, target_width)
            resized_images.append(resized_img)
            total_height += resized_img.height
        
        # Create a new blank image with total height
        stitched_image = Image.new('RGB', (target_width, total_height), color='white')
        
        # Paste images one after the other vertically
        current_y = 0
        for img in resized_images:
            stitched_image.paste(img, (0, current_y))
            current_y += img.height
        
        # Convert to bytes
        output = io.BytesIO()
        stitched_image.save(output, format='JPEG', quality=95)
        return output.getvalue()
        
    except Exception as e:
        logger.error(f"Error stitching images: {str(e)}")
        raise


def _resize_to_width(img: Image.Image, width: int) -> Image.Image:
    """
    Resize an image to a specific width while maintaining aspect ratio.
    
    Args:
        img: PIL Image object
        width: Target width in pixels
        
    Returns:
        PIL Image object resized to the target width
    """
    if img.width == width:
        return img
        
    w_percent = (width / float(img.width))
    h_size = int((float(img.height) * float(w_percent)))
    return img.resize((width, h_size), Image.LANCZOS)
