from django.db import models
from django.contrib.auth.models import AbstractUser
import datetime
from django.contrib.auth import get_user_model
import uuid
from django.utils import timezone

# Create your models here.
class UserProfile(AbstractUser):
    """
    Custom user model that inherits from AbstractUser.
    This includes fields: username, email, password, first_name, last_name, etc.
    We add extra fields as needed, for example 'phone_number'.
    """
    # Extra fields
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True)

    # Email verification fields
    is_email_verified = models.BooleanField(default=False, help_text="Whether the user's email has been verified")
    email_verified_at = models.DateTimeField(null=True, blank=True, help_text="When the email was verified")

    # User Tier Information
    FREE = 'free'
    PREMIUM = 'premium'
    SUBSCRIPTION_CHOICES = [
        (FREE, 'Free'),
        (PREMIUM, 'Premium'),
    ]

    subscription_type = models.CharField(
        max_length=10,
        choices=SUBSCRIPTION_CHOICES,
        default=FREE,
        db_index=True,         
    )

    squirll_id = models.EmailField(
        unique=True,
        null=True, blank=True,
        help_text="Pseudo e-mail to receive email receipts. "
    )

    @property
    def is_premium(self) -> bool:
        """True for paid accounts, False for free accounts."""
        return self.subscription_type == self.PREMIUM

    def mark_email_verified(self):
        """Mark the user's email as verified"""
        self.is_email_verified = True
        self.email_verified_at = timezone.now()
        self.save(update_fields=['is_email_verified', 'email_verified_at'])

    def __str__(self):
        # Show username or any other identifying field
        return self.username


class EmailVerification(models.Model):
    """
    Model to store email verification tokens for users.
    """
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="email_verifications")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Token expires in 24 hours
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        """Check if the verification token has expired"""
        return timezone.now() > self.expires_at
    
    @property
    def is_valid(self):
        """Check if the token is valid (not used and not expired)"""
        return not self.is_used and not self.is_expired
    
    def mark_as_used(self):
        """Mark the token as used"""
        self.is_used = True
        self.save(update_fields=['is_used'])
    
    def __str__(self):
        return f"Email verification for {self.user.email} - {'Used' if self.is_used else 'Pending'}"


class UsageTracker(models.Model):
    """
    Tracks how many times a user performs a specific action each day.
    E.g., how many receipts they have uploaded, how many chatbot queries, etc.
    """

    RECEIPT_UPLOAD = 'receipt_upload'
    CHATBOT_USE = 'chatbot_use'
    REPORT_DOWNLOAD = 'report_upload'
    # add more usage "types" as needed

    USAGE_CHOICES = [
        (RECEIPT_UPLOAD, 'Receipt Upload'),
        (CHATBOT_USE, 'Chatbot Use'),
        (REPORT_DOWNLOAD, 'Report Download'),
        # etc.
    ]

    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="trackers")
    usage_type = models.CharField(max_length=50, choices=USAGE_CHOICES)
    date = models.DateField(default=datetime.date.today)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'usage_type', 'date')

    def __str__(self):
        return (f"{self.user.username} - {self.usage_type} "
                f"on {self.date}: {self.count}")


class PasswordReset(models.Model):
    """
    Model to store password reset tokens for users.
    """
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="password_resets")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Token expires in 1 hour for security
            self.expires_at = timezone.now() + timezone.timedelta(hours=1)
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        """Check if the reset token has expired"""
        return timezone.now() > self.expires_at
    
    @property
    def is_valid(self):
        """Check if the token is valid (not used and not expired)"""
        return not self.is_used and not self.is_expired
    
    def mark_as_used(self):
        """Mark the token as used"""
        self.is_used = True
        self.save(update_fields=['is_used'])
    
    def __str__(self):
        return f"Password reset for {self.user.email} - {'Used' if self.is_used else 'Pending'}"
