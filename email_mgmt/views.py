"""
Email Management Views

This module provides the API endpoints for managing and viewing emails in the system.
It includes views for listing emails, grouping them by company, viewing details,
and handling email ingestion from SendGrid's Inbound Parse webhook.
"""

from django.db.models import Count
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import api_view, parser_classes
from .models import Email
from .serializers import EmailListSerializer, EmailDetailSerializer, EmailSerializer
from .filters import EmailFilter
from .services.email_processor import is_marketing, company_from_fromhdr
from .signals import email_received
from django.contrib.auth import get_user_model
from email.utils import parseaddr
from django.shortcuts import get_object_or_404
from rest_framework import status
from typing import Dict, Any
import logging
import base64
from django.db.models import Count
from receipt_mgmt.services.receipt_parsing import receipt_upload_email
from django.db.models import Max

logger = logging.getLogger(__name__)


# ── A) flat list  /api/emails/ ───────────────────────────────────
class EmailListView(ListAPIView):
    """
    API endpoint that lists all emails for the authenticated user.
    
    Supports:
        - Filtering by date, category, and company
        - Ordering by creation date (newest first by default)
        - Pagination
    
    URL: /api/emails/
    Method: GET
    Auth: Required
    """
    serializer_class   = EmailListSerializer
    permission_classes = [IsAuthenticated]
    filterset_class    = EmailFilter
    ordering_fields    = ["created_at"]
    ordering           = ["-created_at"]          # newest first

    def get_queryset(self):
        """Returns emails belonging to the authenticated user"""
        return Email.objects.filter(user=self.request.user).select_related('user')

# ── B) bucket view  /api/emails/by-company/ ──────────────────────
class EmailByCompanyView(ListAPIView):
    """
    API endpoint that lists companies sorted by their most recent email.
    
    Returns a list of companies sorted by their most recent email date.
    The frontend can then fetch specific email lists for each company
    using the main email endpoint with filters.
    
    URL: /api/emails/by-company/
    Method: GET
    Auth: Required
    
    Response format:
    [
      {
        "company": "Amazon",
        "latest_email_date": "2024-03-21T14:30:00Z"
      },
      ...
    ]
    """
    permission_classes = [IsAuthenticated]
    filterset_class    = EmailFilter
    pagination_class   = None

    def get_queryset(self):
        return Email.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        """
        Custom list method to get companies sorted by their latest email date.
        """
        qs = self.filter_queryset(self.get_queryset())

        # Get companies with their latest email dates
        company_stats = (
            qs.values("company")
              .annotate(latest_email_date=Max("created_at"))
              .order_by("-latest_email_date")
        )

        return Response(list(company_stats))

# ── C) detail  /api/emails/<pk>/ ─────────────────────────────────
class EmailDetailView(RetrieveAPIView):
    """
    API endpoint that returns detailed information about a single email.
    
    URL: /api/emails/<pk>/
    Method: GET
    Auth: Required
    """
    serializer_class   = EmailDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Returns emails belonging to the authenticated user"""
        return Email.objects.filter(user=self.request.user)

# ── D) upload  /api/emails/upload/ ───────────────────────────────
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def create_email(request):
    """
    API endpoint that handles incoming emails from SendGrid's Parse Webhook.
    
    This view:
    1. Validates the incoming email data
    2. Processes any attachments
    3. Determines email category (marketing vs message)
    4. Stores the complete email with all MIME content
    5. Checks for receipt-like content
    6. Sends notification signals
    
    URL: /api/emails/upload/
    Method: POST
    Content-Type: multipart/form-data
    Auth: Not required (webhook endpoint)
    """
    # Parse and validate the recipient email
    user_email_unparsed = request.data.get('to')
    if not user_email_unparsed:
        logger.error("400 error in create_email: No 'to' field in request data")
        return Response(
            {"error": "Missing 'to' field in request data"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        display_name, email_address = parseaddr(user_email_unparsed)
    except Exception as e:
        logger.error("400 error in create_email: %s", f"Error parsing email address: {str(e)}")
        return Response(
            {"error": f"Error parsing email address: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get the user based on their squirll_id (email address)
    try:
        user = get_object_or_404(get_user_model(), squirll_id=email_address)
    except Exception as e:
        logger.error("404 error in create_email: User not found for email %s", email_address)
        return Response(
            {"error": f"User not found for email address: {email_address}"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    sg = request.data

    # Validate required fields
    if not sg.get("from") or not sg.get("subject"):
        logger.error("400 error in create_email: Missing required 'from' or 'subject' fields")
        return Response(
            {"error": "Missing required fields: 'from' and 'subject' are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Extract email content parts
    html_part = sg.get("html")
    text_part = sg.get("text", "")
    raw_headers = sg.get("headers", "")

    # Ensure HTML content exists
    if not html_part:
        html_part = text_part or "<p>(no html body)</p>"

    # Process attachments if present
    attachments = {}
    num_attachments = int(sg.get('attachments', 0))
    
    for i in range(1, num_attachments + 1):
        attachment_key = f'attachment{i}'
        if attachment_key in sg:
            attachment = sg[attachment_key]
            content = attachment.read()
            
            attachments[attachment.name] = {
                'type': attachment.content_type,
                'size': len(content),
                'content': base64.b64encode(content).decode('utf-8')
            }
            
            logger.info("Attachment found: %s (%s)", 
                       attachment.name, attachment.content_type)

    # Prepare email data for storage
    data: Dict[str, Any] = {
        "sender": sg["from"],
        "subject": sg["subject"],
        "html": html_part,
        "text_content": text_part,
        "headers": raw_headers,
        "raw_email": str(sg),  # Store complete SendGrid payload
        "attachments": attachments,
        "company": company_from_fromhdr(sg["from"]),
    }

    # Determine email category
    category = (
        Email.MARKETING
        if is_marketing(raw_headers, data["subject"])
        else Email.MESSAGE
    )

    # Validate and save the email
    serializer = EmailSerializer(data=data)
    if not serializer.is_valid():
        logger.error("Email validation error for user %s: %s",
                     user.squirll_id, serializer.errors)
        return Response(
            {"error": f"Email validation failed: {serializer.errors}"},
            status=status.HTTP_400_BAD_REQUEST
        )

    email = serializer.save(user=user, category=category)

    # Send notification signal
    email_received.send(
        sender=Email,
        user=user,
        email_id=email.id,
        subject=email.subject,
        category=email.category,
        company=email.company,
    )

    logger.info("Email (%s) saved for %s (%s)", category,
                user.squirll_id, email.company)
    
    # Check for receipt-like content
    receipt_keywords = [
        "receipt", "order confirmation", "invoice", "total",
        "subtotal", "payment", "transaction", "purchase", 
        "order #", "order number", "amount paid"
    ]
    
    # Check all text content for receipt keywords
    is_receipt = any(
        keyword.lower() in data["subject"].lower() or 
        keyword.lower() in data["html"].lower() or
        keyword.lower() in data.get("text_content", "").lower()
        for keyword in receipt_keywords
    )
    
    if is_receipt:
        # Check PDF attachments for potential receipt content
        for filename, attachment in attachments.items():
            if attachment['type'] == 'application/pdf':
                logger.info("Receipt may be in PDF attachment: %s", filename)
        receipt_upload_email(html_content=html_part, user=user)
        
        logger.info("Receipt detected in email from %s", email.company)
    
    logger.info("Email processed successfully (is_receipt=%s, attachments=%d)", 
                is_receipt, len(attachments))
    
    return Response({
        "status": "success",
        "message": "Email processed successfully",
        "email_id": email.id,
        "is_receipt": is_receipt,
        "category": category
    }, status=status.HTTP_201_CREATED)


