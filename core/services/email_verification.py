"""
Email verification service for handling email verification during user registration.
"""
import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from ..models import EmailVerification
from django.utils import timezone

logger = logging.getLogger(__name__)

User = get_user_model()


class EmailVerificationError(Exception):
    """Base exception for email verification errors"""
    pass


class TokenExpiredError(EmailVerificationError):
    """Raised when verification token has expired"""
    pass


class TokenNotFoundError(EmailVerificationError):
    """Raised when verification token is not found"""
    pass


class TokenAlreadyUsedError(EmailVerificationError):
    """Raised when verification token has already been used"""
    pass


def create_verification_token(user):
    """
    Create a new email verification token for the user.
    Invalidates any existing unused tokens.
    """
    # Invalidate any existing unused tokens
    EmailVerification.objects.filter(
        user=user, 
        is_used=False
    ).update(is_used=True)
    
    # Create new verification token
    verification = EmailVerification.objects.create(user=user)
    return verification


def send_verification_email(user, request=None):
    """
    Send email verification email to the user.
    
    Args:
        user: User instance
        request: Django request object (optional, used for building absolute URLs)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        # Create verification token
        verification = create_verification_token(user)
        
        # Build verification URL
        if request:
            verification_url = request.build_absolute_uri(
                reverse('verify-email', kwargs={'token': verification.token})
            )
        else:
            # Fallback if no request object
            verification_url = f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')}/verify-email/{verification.token}"
        
        # Email context
        context = {
            'user': user,
            'verification_url': verification_url,
            'token': verification.token,
            'expires_hours': 24,
        }
        
        # Render email templates
        html_message = render_to_string('core/emails/email_verification.html', context)
        plain_message = render_to_string('core/emails/email_verification.txt', context)
        
        # Send email
        sent = send_mail(
            subject="Verify your Squirll account",
            message=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@squirll.com'),
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        if sent:
            logger.info(f"Verification email sent successfully to {user.email}")
            return True
        else:
            logger.error(f"Failed to send verification email to {user.email}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending verification email to {user.email}: {str(e)}")
        return False


def verify_email_token(token):
    """
    Verify an email verification token and mark user's email as verified.
    
    Args:
        token: UUID token string
    
    Returns:
        User: The verified user instance
    
    Raises:
        TokenNotFoundError: If token doesn't exist
        TokenExpiredError: If token has expired
        TokenAlreadyUsedError: If token has already been used
    """
    try:
        verification = EmailVerification.objects.get(token=token)
    except EmailVerification.DoesNotExist:
        raise TokenNotFoundError("Invalid verification token")
    
    if verification.is_used:
        raise TokenAlreadyUsedError("This verification link has already been used")
    
    if verification.is_expired:
        raise TokenExpiredError("This verification link has expired. Please request a new one.")
    
    # Mark token as used and verify user's email
    verification.mark_as_used()
    verification.user.mark_email_verified()
    
    logger.info(f"Email verified successfully for user {verification.user.email}")
    return verification.user


def resend_verification_email(user, request=None):
    """
    Resend verification email to user. This creates a new token.
    
    Args:
        user: User instance
        request: Django request object (optional)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    
    Raises:
        EmailVerificationError: If user's email is already verified
    """
    if user.is_email_verified:
        raise EmailVerificationError("Email is already verified")
    
    return send_verification_email(user, request)


def cleanup_expired_tokens():
    """
    Clean up expired verification tokens from the database.
    This can be run as a periodic task.
    """
    expired_count = EmailVerification.objects.filter(
        expires_at__lt=timezone.now(),
        is_used=False
    ).update(is_used=True)
    
    logger.info(f"Cleaned up {expired_count} expired verification tokens")
    return expired_count 