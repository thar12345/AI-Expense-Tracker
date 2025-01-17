from django.db import models
from django.contrib.auth import get_user_model

class Email(models.Model):
    """
    Model to store and manage email data received through SendGrid's Inbound Parse webhook.
    
    This model stores both the parsed components of an email (subject, sender, etc.) as well as
    the complete MIME content for archival purposes. It supports both HTML and plain text content,
    along with email attachments stored as JSON.
    
    Each email is categorized as either 'marketing' or 'message' for UI organization, and is
    associated with a company for grouping purposes.
    
    Relationships:
        - Each email belongs to one user (ForeignKey to AUTH_USER_MODEL)
    """
    user = models.ForeignKey(
        get_user_model(), 
        on_delete=models.CASCADE, 
        related_name="emails",
        help_text="The user who received this email"
    )

    # Basic email fields for quick access and display
    sender = models.TextField(
        help_text="The full 'From' header of the email"
    )
    html = models.TextField(
        help_text="HTML version of the email body"
    )
    subject = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        help_text="Email subject line"
    )
    company = models.CharField(
        max_length=255, 
        default="Miscellaneous",
        help_text="Derived company name from the sender's email domain"
    )

    # Full MIME email storage for complete archival
    raw_email = models.TextField(
        help_text="Complete raw MIME email content including all headers and parts"
    )
    headers = models.TextField(
        blank=True, 
        null=True,
        help_text="Parsed email headers stored as text"
    )
    text_content = models.TextField(
        blank=True, 
        null=True,
        help_text="Plain text version of the email body"
    )
    attachments = models.JSONField(
        default=dict,
        help_text="JSON object containing attachment metadata and base64 encoded content"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the email record was created"
    )

    # Email categorization constants
    MARKETING = "marketing"
    MESSAGE = "message"

    CATEGORY_CHOICES = [
        (MARKETING, "Marketing / Promotions"),
        (MESSAGE, "Primary / Messages"),
    ]

    category = models.CharField(
        max_length=10,
        choices=CATEGORY_CHOICES,
        default=MESSAGE,
        db_index=True,
        help_text="Classification used for inbox organization (marketing vs primary messages)"
    )

    def __str__(self):
        """Returns a human-readable representation of the email"""
        return f"Email to {self.user.email} from {self.sender} - {self.subject}"

    class Meta:
        indexes = [
            # Index for company bucketing with dates (used in by-company view)
            models.Index(fields=['user', 'company', '-created_at']),
            # Index for filtering by category within a user's emails
            models.Index(fields=['user', 'category', '-created_at']),
        ]
        ordering = ['-created_at']
