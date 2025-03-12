"""
Password reset service for handling password reset requests.
"""
import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.contrib.auth.models import AnonymousUser
from ..models import PasswordReset
from django.utils import timezone
from django.contrib.auth.hashers import make_password

logger = logging.getLogger(__name__)

User = get_user_model()


class PasswordResetError(Exception):
    """Base exception for password reset errors"""
    pass


class TokenExpiredError(PasswordResetError):
    """Raised when reset token has expired"""
    pass


class TokenNotFoundError(PasswordResetError):
    """Raised when reset token is not found"""
    pass


class TokenAlreadyUsedError(PasswordResetError):
    """Raised when reset token has already been used"""
    pass


class UserNotFoundError(PasswordResetError):
    """Raised when user with given email doesn't exist"""
    pass


def create_password_reset_token(user):
    """
    Create a new password reset token for the user.
    Invalidates any existing unused tokens.
    """
    # Invalidate any existing unused tokens for security
    PasswordReset.objects.filter(
        user=user, 
        is_used=False
    ).update(is_used=True)
    
    # Create new reset token
    reset_token = PasswordReset.objects.create(user=user)
    return reset_token


def send_password_reset_email(email, request=None):
    """
    Send password reset email to the user.
    
    Args:
        email: User's email address
        request: Django request object (optional, used for building absolute URLs)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    
    Raises:
        UserNotFoundError: If no user exists with the given email
    """
    try:
        # Find user by email
        try:
            user = User.objects.get(email=email.lower())
        except User.DoesNotExist:
            raise UserNotFoundError("No user found with this email address")
        
        # Create reset token
        reset_token = create_password_reset_token(user)
        
        # Build reset URL
        if request:
            reset_url = request.build_absolute_uri(
                reverse('password-reset-confirm', kwargs={'token': reset_token.token})
            )
        else:
            # Fallback if no request object
            reset_url = f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')}/reset-password/{reset_token.token}"
        
        # Email context
        context = {
            'user': user,
            'reset_url': reset_url,
            'token': reset_token.token,
            'expires_hours': 1,
        }
        
        # Render email templates
        html_message = render_to_string('core/emails/password_reset.html', context)
        plain_message = render_to_string('core/emails/password_reset.txt', context)
        
        # Send email
        sent = send_mail(
            subject="Reset your Squirll password",
            message=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@squirll.com'),
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        if sent:
            logger.info(f"Password reset email sent successfully to {user.email}")
            return True
        else:
            logger.error(f"Failed to send password reset email to {user.email}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending password reset email to {email}: {str(e)}")
        return False


def verify_password_reset_token(token):
    """
    Verify a password reset token.
    
    Args:
        token: UUID token string
    
    Returns:
        PasswordReset: The reset token instance
    
    Raises:
        TokenNotFoundError: If token doesn't exist
        TokenExpiredError: If token has expired
        TokenAlreadyUsedError: If token has already been used
    """
    try:
        reset_token = PasswordReset.objects.get(token=token)
    except PasswordReset.DoesNotExist:
        raise TokenNotFoundError("Invalid password reset token")
    
    if reset_token.is_used:
        raise TokenAlreadyUsedError("This password reset link has already been used")
    
    if reset_token.is_expired:
        raise TokenExpiredError("This password reset link has expired. Please request a new one.")
    
    return reset_token


def invalidate_all_user_sessions(user):
    """
    Invalidate all active sessions for a user.
    This logs out the user from all devices.
    """
    # Get all active sessions
    sessions = Session.objects.filter(expire_date__gte=timezone.now())
    
    sessions_deleted = 0
    for session in sessions:
        data = session.get_decoded()
        if data.get('_auth_user_id') == str(user.id):
            session.delete()
            sessions_deleted += 1
    
    logger.info(f"Invalidated {sessions_deleted} active sessions for user {user.email}")
    return sessions_deleted


def send_password_changed_confirmation_email(user):
    """
    Send confirmation email after password has been successfully changed.
    
    Args:
        user: User instance whose password was changed
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        # Email context
        context = {
            'user': user,
            'change_time': timezone.now(),
        }
        
        # Render email templates
        html_message = render_to_string('core/emails/password_changed.html', context)
        plain_message = render_to_string('core/emails/password_changed.txt', context)
        
        # Send confirmation email
        sent = send_mail(
            subject="Your password has been updated",
            message=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@squirll.com'),
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        if sent:
            logger.info(f"Password changed confirmation email sent successfully to {user.email}")
            return True
        else:
            logger.error(f"Failed to send password changed confirmation email to {user.email}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending password changed confirmation email to {user.email}: {str(e)}")
        return False


def reset_user_password(token, new_password):
    """
    Reset user's password using a valid token.
    
    Args:
        token: UUID token string
        new_password: New password to set
    
    Returns:
        User: The user whose password was reset
    
    Raises:
        TokenNotFoundError: If token doesn't exist
        TokenExpiredError: If token has expired
        TokenAlreadyUsedError: If token has already been used
    """
    # Verify token first
    reset_token = verify_password_reset_token(token)
    
    # Reset password
    user = reset_token.user
    user.set_password(new_password)
    user.save(update_fields=['password'])
    
    # Mark token as used
    reset_token.mark_as_used()
    
    # Invalidate all active sessions (logout from all devices)
    invalidate_all_user_sessions(user)
    
    # Send confirmation email
    send_password_changed_confirmation_email(user)
    
    logger.info(f"Password reset successfully for user {user.email}")
    return user


def cleanup_expired_password_reset_tokens():
    """
    Clean up expired password reset tokens from the database.
    This can be run as a periodic task.
    """
    expired_count = PasswordReset.objects.filter(
        expires_at__lt=timezone.now(),
        is_used=False
    ).update(is_used=True)
    
    logger.info(f"Cleaned up {expired_count} expired password reset tokens")
    return expired_count 