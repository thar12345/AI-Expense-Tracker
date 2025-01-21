"""
Email Management Signals

This module defines Django signals used for real-time notifications when
new emails are received and processed by the system.
"""

from django.dispatch import Signal, receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# Define custom signals
email_received = Signal()

@receiver(email_received)
def handle_email_received(sender, user, email_id, subject, category, company, **kwargs):
    """
    Signal handler that sends a WebSocket notification when a new email is received.
    
    This handler sends a real-time notification to the user's WebSocket group,
    allowing the UI to update immediately when new emails arrive.
    
    Args:
        sender: The model class that sent the signal (Email)
        user: The user who received the email
        email_id: The ID of the newly created email
        subject: The email subject
        category: The email category (marketing/message)
        company: The derived company name
        **kwargs: Additional keyword arguments
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user.id}",  # Each user has their own notification group
        {
            "type": "new_email_notification",
            "email_id": email_id,
            "subject": subject,
            "category": category,
            "company": company,
        }
    )
    