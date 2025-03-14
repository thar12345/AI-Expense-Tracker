"""
Custom email backends for Squirll project.
"""
import os
import logging
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail import EmailMultiAlternatives
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, From, To, Subject, PlainTextContent, HtmlContent
import urllib3
import ssl

logger = logging.getLogger(__name__)


class SendGridBackend(BaseEmailBackend):
    """
    Custom email backend that uses SendGrid API to send emails.
    """
    
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        logger.info("Initializing SendGrid email backend")
        
        self.api_key = os.environ.get('SENDGRID_API_KEY')
        if not self.api_key:
            logger.error("SENDGRID_API_KEY not found in environment variables")
            if not fail_silently:
                raise ValueError("SENDGRID_API_KEY environment variable is required")
            logger.error("SENDGRID_API_KEY not set - emails will not be sent")
        else:
            logger.info("SENDGRID_API_KEY found")
        
        # Configure SSL verification
        disable_ssl_verify = os.environ.get('SENDGRID_DISABLE_SSL_VERIFY', 'false').lower() == 'true'
        logger.info(f"SSL verification disabled: {disable_ssl_verify}")
        
        if self.api_key:
            if disable_ssl_verify:
                logger.warning("SSL verification disabled for SendGrid - this should only be used in development")
                # Disable SSL warnings
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                # Monkey patch SSL verification globally for this process
                ssl._create_default_https_context = ssl._create_unverified_context
                
            logger.info("Creating SendGrid client...")
            self.client = SendGridAPIClient(api_key=self.api_key)
            logger.info("SendGrid client created successfully")
        else:
            logger.error("No API key available - SendGrid client not created")
            self.client = None
    
    def send_messages(self, email_messages):
        """
        Send multiple email messages.
        Returns the number of successfully sent messages.
        """
        logger.info(f"SendGrid backend: send_messages called with {len(email_messages)} messages")
        
        if not self.client:
            logger.error("SendGrid client not initialized - cannot send emails")
            if not self.fail_silently:
                raise RuntimeError("SendGrid client not initialized")
            return 0
        
        sent_count = 0
        for i, message in enumerate(email_messages):
            logger.info(f"Processing message {i+1}/{len(email_messages)}")
            if self._send_message(message):
                sent_count += 1
        
        logger.info(f"Successfully sent {sent_count}/{len(email_messages)} messages")
        return sent_count
    
    def _send_message(self, message):
        """
        Send a single email message using SendGrid.
        Returns True if successful, False otherwise.
        """
        try:
            logger.info(f"Attempting to send email via SendGrid to {message.to}")
            logger.info(f"From: {message.from_email}, Subject: {message.subject}")
            
            # Convert Django EmailMessage to SendGrid Mail object
            mail = Mail()
            
            # Set from address
            from_email = message.from_email or os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@squirll.com')
            logger.info(f"Using from_email: {from_email}")
            mail.from_email = From(from_email)
            
            # Set recipients
            if message.to:
                for recipient in message.to:
                    logger.info(f"Adding recipient: {recipient}")
                    mail.add_to(To(recipient))
            
            # Set subject
            mail.subject = Subject(message.subject)
            
            # Set content
            if hasattr(message, 'alternatives') and message.alternatives:
                # Email has both plain text and HTML
                logger.info("Email has HTML content")
                mail.add_content(PlainTextContent(message.body))
                for content, mimetype in message.alternatives:
                    if mimetype == 'text/html':
                        mail.add_content(HtmlContent(content))
            else:
                # Plain text only
                logger.info("Email is plain text only")
                mail.add_content(PlainTextContent(message.body))
            
            # Send the email
            logger.info("Calling SendGrid API...")
            response = self.client.send(mail)
            logger.info(f"SendGrid API response: status={response.status_code}")
            
            if response.status_code in [200, 201, 202]:
                logger.info(f"Email sent successfully to {message.to} via SendGrid")
                return True
            else:
                logger.error(f"SendGrid API returned status {response.status_code}: {response.body}")
                if not self.fail_silently:
                    raise RuntimeError(f"SendGrid API error: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending email via SendGrid: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            if not self.fail_silently:
                raise
            return False 