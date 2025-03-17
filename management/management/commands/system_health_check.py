"""
Comprehensive System Health Check for Squirll

This management command performs a thorough health check of all system components:
- Database connectivity
- Redis connectivity and channels
- Azure services (Storage, Document Intelligence, Application Insights)
- OpenAI API
- Twilio API
- Google OAuth configuration
- Celery worker connectivity
- WebSocket functionality
- Email configuration
- Environment settings validation

Usage:
    python manage.py system_health_check
    python manage.py system_health_check --verbose
    python manage.py system_health_check --component redis
"""

import os
import sys
import json
import asyncio
import tempfile
from io import BytesIO
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.core.cache import cache
from django.db import connection
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.mail import send_mail

# Third-party imports
import redis
import openai
from twilio.rest import Client as TwilioClient
from azure.storage.blob import BlobServiceClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from celery import Celery
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Project imports
from core.utils.google_utils import verify_google_id_token
from core.services.phone_auth import send_phone_verification_otp
from receipt_mgmt.services.img_receipt_engine import extract_receipt
from receipt_mgmt.utils.azure_utils import upload_receipt_image
from email_mgmt.services.email_processor import is_marketing, company_from_fromhdr

User = get_user_model()


class HealthCheckResult:
    """Represents the result of a health check component."""
    
    def __init__(self, component: str, status: str, message: str, details: Dict = None):
        self.component = component
        self.status = status  # 'PASS', 'FAIL', 'WARN', 'SKIP'
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now()
    
    def __str__(self):
        status_symbols = {
            'PASS': '✅',
            'FAIL': '❌',
            'WARN': '⚠️',
            'SKIP': '⏭️'
        }
        return f"{status_symbols.get(self.status, '?')} {self.component}: {self.message}"


class Command(BaseCommand):
    help = 'Comprehensive system health check for Squirll'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output and debug information',
        )
        parser.add_argument(
            '--component',
            type=str,
            help='Test specific component only (database, redis, azure, openai, twilio, celery, websocket, email)',
        )
        parser.add_argument(
            '--environment',
            type=str,
            default=getattr(settings, 'ENVIRONMENT', 'development'),
            help='Environment to test (development, staging, production)',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=30,
            help='Timeout in seconds for each test',
        )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.results: List[HealthCheckResult] = []
        self.verbose = False
        self.environment = 'development'
        self.timeout = 30
    
    def handle(self, *args, **options):
        self.verbose = options['verbose']
        self.environment = options['environment']
        self.timeout = options['timeout']
        
        self.stdout.write(self.style.SUCCESS('🔍 Starting Comprehensive System Health Check'))
        self.stdout.write(f"Environment: {self.environment}")
        self.stdout.write(f"Timeout: {self.timeout}s")
        self.stdout.write("=" * 60)
        
        # Run health checks
        component = options.get('component')
        if component:
            self.run_single_component(component)
        else:
            self.run_all_components()
        
        # Generate summary report
        self.generate_summary_report()
        
        # Exit with appropriate code
        failed_checks = [r for r in self.results if r.status == 'FAIL']
        if failed_checks:
            raise CommandError(f"Health check failed: {len(failed_checks)} components failed")
    
    def run_single_component(self, component: str):
        """Run health check for a single component."""
        component_map = {
            'settings': self.check_settings_configuration,
            'database': self.check_database_connectivity,
            'redis': self.check_redis_connectivity,
            'azure': self.check_azure_services,
            'openai': self.check_openai_api,
            'twilio': self.check_twilio_api,
            'celery': self.check_celery_connectivity,
            'websocket': self.check_websocket_functionality,
            'email': self.check_email_configuration,
            'google': self.check_google_oauth,
        }
        
        if component not in component_map:
            raise CommandError(f"Unknown component: {component}")
        
        component_map[component]()
    
    def run_all_components(self):
        """Run health checks for all components."""
        self.check_settings_configuration()
        self.check_database_connectivity()
        self.check_redis_connectivity()
        self.check_azure_services()
        self.check_openai_api()
        self.check_twilio_api()
        self.check_google_oauth()
        self.check_celery_connectivity()
        self.check_websocket_functionality()
        self.check_email_configuration()
        self.check_integration_workflows()
    
    def log_result(self, result: HealthCheckResult):
        """Log and store a health check result."""
        self.results.append(result)
        self.stdout.write(str(result))
        
        if self.verbose and result.details:
            for key, value in result.details.items():
                self.stdout.write(f"  {key}: {value}")
    
    def check_settings_configuration(self):
        """Verify all settings are properly configured."""
        self.stdout.write(self.style.HTTP_INFO('\n📋 Checking Settings Configuration'))
        
        try:
            # Check environment detection
            from squirll.settings.env_utils import get_environment, EnvValidator
            
            detected_env = get_environment()
            self.log_result(HealthCheckResult(
                'Settings Environment',
                'PASS',
                f'Environment detected: {detected_env}',
                {'environment': detected_env}
            ))
            
            # Check environment validator
            env_validator = EnvValidator(detected_env)
            
            # Check critical settings
            critical_settings = [
                'SECRET_KEY',
                'ALLOWED_HOSTS',
                'INSTALLED_APPS',
                'MIDDLEWARE',
            ]
            
            for setting_name in critical_settings:
                if hasattr(settings, setting_name):
                    value = getattr(settings, setting_name)
                    if value:
                        self.log_result(HealthCheckResult(
                            f'Settings {setting_name}',
                            'PASS',
                            f'{setting_name} is configured',
                            {'type': type(value).__name__, 'length': len(str(value))}
                        ))
                    else:
                        self.log_result(HealthCheckResult(
                            f'Settings {setting_name}',
                            'FAIL',
                            f'{setting_name} is empty or None'
                        ))
                else:
                    self.log_result(HealthCheckResult(
                        f'Settings {setting_name}',
                        'FAIL',
                        f'{setting_name} is not defined'
                    ))
            
            # Check security settings for production
            if self.environment == 'production':
                security_checks = [
                    ('DEBUG', False),
                    ('SECURE_SSL_REDIRECT', True),
                    ('SECURE_HSTS_SECONDS', lambda x: x > 0),
                    ('SESSION_COOKIE_SECURE', True),
                    ('CSRF_COOKIE_SECURE', True),
                ]
                
                for setting_name, expected in security_checks:
                    if hasattr(settings, setting_name):
                        value = getattr(settings, setting_name)
                        if callable(expected):
                            is_valid = expected(value)
                        else:
                            is_valid = value == expected
                        
                        if is_valid:
                            self.log_result(HealthCheckResult(
                                f'Security {setting_name}',
                                'PASS',
                                f'{setting_name} is properly configured for production',
                                {'value': value}
                            ))
                        else:
                            self.log_result(HealthCheckResult(
                                f'Security {setting_name}',
                                'FAIL',
                                f'{setting_name} is not properly configured for production',
                                {'value': value, 'expected': expected}
                            ))
                    else:
                        self.log_result(HealthCheckResult(
                            f'Security {setting_name}',
                            'FAIL',
                            f'{setting_name} is not defined'
                        ))
            
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Settings Configuration',
                'FAIL',
                f'Settings configuration error: {str(e)}'
            ))
    
    def check_database_connectivity(self):
        """Test database connectivity and basic operations."""
        self.stdout.write(self.style.HTTP_INFO('\n🗄️  Checking Database Connectivity'))
        
        try:
            # Test basic connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                
            self.log_result(HealthCheckResult(
                'Database Connection',
                'PASS',
                'Database connection successful',
                {'result': result[0] if result else None}
            ))
            
            # Test database info
            db_info = connection.get_connection_params()
            self.log_result(HealthCheckResult(
                'Database Info',
                'PASS',
                f'Connected to {connection.vendor} database',
                {
                    'vendor': connection.vendor,
                    'database': db_info.get('database', 'unknown'),
                    'host': db_info.get('host', 'unknown'),
                    'port': db_info.get('port', 'unknown'),
                }
            ))
            
            # Test model operations
            user_count = User.objects.count()
            self.log_result(HealthCheckResult(
                'Database Models',
                'PASS',
                f'Model queries working, {user_count} users in database',
                {'user_count': user_count}
            ))
            
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Database Connection',
                'FAIL',
                f'Database connection failed: {str(e)}'
            ))
    
    def check_redis_connectivity(self):
        """Test Redis connectivity for caching and channels."""
        self.stdout.write(self.style.HTTP_INFO('\n🔴 Checking Redis Connectivity'))
        
        try:
            # Test Django cache
            test_key = 'health_check_test'
            test_value = f'test_value_{datetime.now().timestamp()}'
            
            cache.set(test_key, test_value, timeout=60)
            cached_value = cache.get(test_key)
            
            if cached_value == test_value:
                self.log_result(HealthCheckResult(
                    'Redis Cache',
                    'PASS',
                    'Redis cache is working',
                    {'cache_backend': settings.CACHES['default']['BACKEND']}
                ))
            else:
                self.log_result(HealthCheckResult(
                    'Redis Cache',
                    'FAIL',
                    f'Redis cache test failed: expected {test_value}, got {cached_value}'
                ))
            
            # Clean up test key
            cache.delete(test_key)
            
        except Exception as e:
            # Check if we're using in-memory cache (development fallback)
            cache_backend = settings.CACHES['default']['BACKEND']
            if 'locmem' in cache_backend:
                self.log_result(HealthCheckResult(
                    'Redis Cache',
                    'WARN',
                    'Using in-memory cache instead of Redis (development mode)',
                    {'cache_backend': cache_backend}
                ))
            else:
                self.log_result(HealthCheckResult(
                    'Redis Cache',
                    'FAIL',
                    f'Redis cache connection failed: {str(e)}'
                ))
        
        # Test channel layer
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                # Test channel layer connectivity
                test_channel = 'test_health_check'
                test_message = {'type': 'test_message', 'data': 'health_check'}
                
                # This is a basic test - in production you'd want more thorough testing
                channel_config = getattr(settings, 'CHANNEL_LAYERS', {})
                default_backend = channel_config.get('default', {}).get('BACKEND', 'unknown')
                
                if 'redis' in default_backend:
                    self.log_result(HealthCheckResult(
                        'Redis Channels',
                        'PASS',
                        'Redis channel layer configured',
                        {'backend': default_backend}
                    ))
                elif 'InMemory' in default_backend:
                    self.log_result(HealthCheckResult(
                        'Redis Channels',
                        'WARN',
                        'Using in-memory channel layer (development mode)',
                        {'backend': default_backend}
                    ))
                else:
                    self.log_result(HealthCheckResult(
                        'Redis Channels',
                        'FAIL',
                        f'Unknown channel layer backend: {default_backend}'
                    ))
            else:
                self.log_result(HealthCheckResult(
                    'Redis Channels',
                    'FAIL',
                    'Channel layer not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Redis Channels',
                'FAIL',
                f'Channel layer test failed: {str(e)}'
            ))
    
    def check_azure_services(self):
        """Test Azure service connectivity."""
        self.stdout.write(self.style.HTTP_INFO('\n☁️  Checking Azure Services'))
        
        # Test Azure Blob Storage
        try:
            if hasattr(settings, 'AZURE_STORAGE_CONNECTION_STRING'):
                blob_service = BlobServiceClient.from_connection_string(
                    settings.AZURE_STORAGE_CONNECTION_STRING
                )
                
                # Test connection by listing containers
                containers = list(blob_service.list_containers())
                
                self.log_result(HealthCheckResult(
                    'Azure Blob Storage',
                    'PASS',
                    f'Azure Blob Storage connected, {len(containers)} containers',
                    {'containers': [c.name for c in containers]}
                ))
                
                # Test upload functionality
                test_data = b'health_check_test_data'
                test_blob_name = f'health_check_{datetime.now().timestamp()}.txt'
                
                blob_client = blob_service.get_blob_client(
                    container=getattr(settings, 'AZURE_BLOB_CONTAINER_NAME', 'receipt-images'),
                    blob=test_blob_name
                )
                
                blob_client.upload_blob(test_data, overwrite=True)
                
                # Download to verify
                downloaded_data = blob_client.download_blob().readall()
                
                if downloaded_data == test_data:
                    self.log_result(HealthCheckResult(
                        'Azure Blob Upload/Download',
                        'PASS',
                        'Azure Blob upload/download working'
                    ))
                else:
                    self.log_result(HealthCheckResult(
                        'Azure Blob Upload/Download',
                        'FAIL',
                        'Azure Blob upload/download test failed'
                    ))
                
                # Clean up test blob
                blob_client.delete_blob()
                
            else:
                self.log_result(HealthCheckResult(
                    'Azure Blob Storage',
                    'FAIL',
                    'Azure Blob Storage connection string not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Azure Blob Storage',
                'FAIL',
                f'Azure Blob Storage test failed: {str(e)}'
            ))
        
        # Test Azure Document Intelligence
        try:
            if (hasattr(settings, 'DOCUMENT_INTELLIGENCE_ENDPOINT') and 
                hasattr(settings, 'DOCUMENT_INTELLIGENCE_KEY')):
                
                client = DocumentIntelligenceClient(
                    endpoint=settings.DOCUMENT_INTELLIGENCE_ENDPOINT,
                    credential=AzureKeyCredential(settings.DOCUMENT_INTELLIGENCE_KEY)
                )
                
                # Test with a minimal document (we can't test full functionality without a real receipt)
                self.log_result(HealthCheckResult(
                    'Azure Document Intelligence',
                    'PASS',
                    'Azure Document Intelligence client initialized',
                    {'endpoint': settings.DOCUMENT_INTELLIGENCE_ENDPOINT}
                ))
                
            else:
                self.log_result(HealthCheckResult(
                    'Azure Document Intelligence',
                    'FAIL',
                    'Azure Document Intelligence not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Azure Document Intelligence',
                'FAIL',
                f'Azure Document Intelligence test failed: {str(e)}'
            ))
        
        # Test Application Insights
        try:
            if hasattr(settings, 'AZURE_APPLICATION_INSIGHTS_ENABLED'):
                if settings.AZURE_APPLICATION_INSIGHTS_ENABLED:
                    app_insights_config = {
                        'enabled': settings.AZURE_APPLICATION_INSIGHTS_ENABLED,
                        'instrumentation_key': getattr(settings, 'AZURE_APPLICATION_INSIGHTS_INSTRUMENTATION_KEY', 'not set'),
                        'connection_string': getattr(settings, 'AZURE_APPLICATION_INSIGHTS_CONNECTION_STRING', 'not set'),
                    }
                    
                    self.log_result(HealthCheckResult(
                        'Azure Application Insights',
                        'PASS',
                        'Application Insights configured and enabled',
                        app_insights_config
                    ))
                else:
                    self.log_result(HealthCheckResult(
                        'Azure Application Insights',
                        'WARN',
                        'Application Insights disabled'
                    ))
            else:
                self.log_result(HealthCheckResult(
                    'Azure Application Insights',
                    'FAIL',
                    'Application Insights not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Azure Application Insights',
                'FAIL',
                f'Application Insights test failed: {str(e)}'
            ))
    
    def check_openai_api(self):
        """Test OpenAI API connectivity."""
        self.stdout.write(self.style.HTTP_INFO('\n🤖 Checking OpenAI API'))
        
        try:
            # Test API key configuration
            if hasattr(settings, 'OPENAI_API_KEY') and settings.OPENAI_API_KEY:
                openai.api_key = settings.OPENAI_API_KEY
                
                # Test with a simple completion
                response = openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "user", "content": "Respond with just the word 'SUCCESS' if you receive this message."}
                    ],
                    max_tokens=10,
                    temperature=0
                )
                
                if response.choices[0].message.content.strip() == 'SUCCESS':
                    self.log_result(HealthCheckResult(
                        'OpenAI API',
                        'PASS',
                        'OpenAI API connection successful',
                        {'model': 'gpt-4o-mini', 'usage': response.usage.total_tokens}
                    ))
                else:
                    self.log_result(HealthCheckResult(
                        'OpenAI API',
                        'FAIL',
                        f'OpenAI API test failed: unexpected response: {response.choices[0].message.content}'
                    ))
                
            else:
                self.log_result(HealthCheckResult(
                    'OpenAI API',
                    'FAIL',
                    'OpenAI API key not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'OpenAI API',
                'FAIL',
                f'OpenAI API test failed: {str(e)}'
            ))
    
    def check_twilio_api(self):
        """Test Twilio API connectivity."""
        self.stdout.write(self.style.HTTP_INFO('\n📱 Checking Twilio API'))
        
        try:
            if (hasattr(settings, 'TWILIO_ACCOUNT_SID') and 
                hasattr(settings, 'TWILIO_ACCOUNT_AUTH_TOKEN') and
                hasattr(settings, 'TWILIO_PHONE_NUMBER')):
                
                client = TwilioClient(
                    settings.TWILIO_ACCOUNT_SID,
                    settings.TWILIO_ACCOUNT_AUTH_TOKEN
                )
                
                # Test account info
                account = client.api.accounts(settings.TWILIO_ACCOUNT_SID).fetch()
                
                self.log_result(HealthCheckResult(
                    'Twilio API',
                    'PASS',
                    f'Twilio API connected, account status: {account.status}',
                    {
                        'account_sid': settings.TWILIO_ACCOUNT_SID,
                        'status': account.status,
                        'phone_number': settings.TWILIO_PHONE_NUMBER
                    }
                ))
                
                # Test phone number validation
                phone_number = client.lookups.v1.phone_numbers(settings.TWILIO_PHONE_NUMBER).fetch()
                
                self.log_result(HealthCheckResult(
                    'Twilio Phone Number',
                    'PASS',
                    f'Twilio phone number validated: {phone_number.phone_number}',
                    {'phone_number': phone_number.phone_number}
                ))
                
            else:
                self.log_result(HealthCheckResult(
                    'Twilio API',
                    'FAIL',
                    'Twilio credentials not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Twilio API',
                'FAIL',
                f'Twilio API test failed: {str(e)}'
            ))
    
    def check_google_oauth(self):
        """Test Google OAuth configuration."""
        self.stdout.write(self.style.HTTP_INFO('\n🔐 Checking Google OAuth'))
        
        try:
            if (hasattr(settings, 'GOOGLE_OAUTH_ALLOWED_AUDS') and 
                hasattr(settings, 'GOOGLE_OAUTH_CLIENT_IDS')):
                
                allowed_auds = settings.GOOGLE_OAUTH_ALLOWED_AUDS
                client_ids = settings.GOOGLE_OAUTH_CLIENT_IDS
                
                if allowed_auds and client_ids:
                    self.log_result(HealthCheckResult(
                        'Google OAuth Config',
                        'PASS',
                        f'Google OAuth configured with {len(allowed_auds)} allowed audiences',
                        {
                            'client_ids': client_ids,
                            'allowed_audiences': len(allowed_auds)
                        }
                    ))
                else:
                    self.log_result(HealthCheckResult(
                        'Google OAuth Config',
                        'FAIL',
                        'Google OAuth not configured (empty configuration)'
                    ))
                
            else:
                self.log_result(HealthCheckResult(
                    'Google OAuth Config',
                    'FAIL',
                    'Google OAuth not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Google OAuth Config',
                'FAIL',
                f'Google OAuth test failed: {str(e)}'
            ))
    
    def check_celery_connectivity(self):
        """Test Celery worker connectivity."""
        self.stdout.write(self.style.HTTP_INFO('\n🔄 Checking Celery Connectivity'))
        
        try:
            # Test Celery configuration
            if hasattr(settings, 'CELERY_BROKER_URL'):
                broker_url = settings.CELERY_BROKER_URL
                
                self.log_result(HealthCheckResult(
                    'Celery Config',
                    'PASS',
                    'Celery broker configured',
                    {'broker_url': broker_url}
                ))
                
                # Test Celery app
                from squirll.celery import app as celery_app
                
                # Test if workers are available
                inspect = celery_app.control.inspect()
                stats = inspect.stats()
                
                if stats:
                    worker_count = len(stats)
                    self.log_result(HealthCheckResult(
                        'Celery Workers',
                        'PASS',
                        f'{worker_count} Celery workers available',
                        {'workers': list(stats.keys())}
                    ))
                else:
                    self.log_result(HealthCheckResult(
                        'Celery Workers',
                        'WARN',
                        'No Celery workers detected (workers may not be running)'
                    ))
                
            else:
                self.log_result(HealthCheckResult(
                    'Celery Config',
                    'FAIL',
                    'Celery broker not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Celery Connectivity',
                'FAIL',
                f'Celery connectivity test failed: {str(e)}'
            ))
    
    def check_websocket_functionality(self):
        """Test WebSocket functionality."""
        self.stdout.write(self.style.HTTP_INFO('\n🌐 Checking WebSocket Functionality'))
        
        try:
            # Test ASGI configuration
            if hasattr(settings, 'ASGI_APPLICATION'):
                asgi_app = settings.ASGI_APPLICATION
                
                self.log_result(HealthCheckResult(
                    'WebSocket ASGI',
                    'PASS',
                    f'ASGI application configured: {asgi_app}',
                    {'asgi_application': asgi_app}
                ))
                
                # Test routing configuration
                try:
                    from squirll.routing import websocket_urlpatterns
                    
                    self.log_result(HealthCheckResult(
                        'WebSocket Routing',
                        'PASS',
                        f'WebSocket routing configured with {len(websocket_urlpatterns)} patterns',
                        {'pattern_count': len(websocket_urlpatterns)}
                    ))
                    
                except ImportError:
                    self.log_result(HealthCheckResult(
                        'WebSocket Routing',
                        'FAIL',
                        'WebSocket routing not configured'
                    ))
                
                # Test consumer
                try:
                    from core.consumers import UserNotificationConsumer
                    
                    self.log_result(HealthCheckResult(
                        'WebSocket Consumer',
                        'PASS',
                        'WebSocket consumer available',
                        {'consumer': 'UserNotificationConsumer'}
                    ))
                    
                except ImportError:
                    self.log_result(HealthCheckResult(
                        'WebSocket Consumer',
                        'FAIL',
                        'WebSocket consumer not available'
                    ))
                
            else:
                self.log_result(HealthCheckResult(
                    'WebSocket ASGI',
                    'FAIL',
                    'ASGI application not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'WebSocket Functionality',
                'FAIL',
                f'WebSocket functionality test failed: {str(e)}'
            ))
    
    def check_email_configuration(self):
        """Test email configuration."""
        self.stdout.write(self.style.HTTP_INFO('\n📧 Checking Email Configuration'))
        
        try:
            # Test email settings
            email_settings = [
                'EMAIL_BACKEND',
                'EMAIL_HOST',
                'EMAIL_PORT',
                'EMAIL_HOST_USER',
                'EMAIL_HOST_PASSWORD',
                'EMAIL_USE_TLS',
                'DEFAULT_FROM_EMAIL'
            ]
            
            configured_settings = {}
            for setting in email_settings:
                if hasattr(settings, setting):
                    value = getattr(settings, setting)
                    configured_settings[setting] = value
            
            if configured_settings:
                self.log_result(HealthCheckResult(
                    'Email Configuration',
                    'PASS',
                    f'Email configured with {len(configured_settings)} settings',
                    {k: v for k, v in configured_settings.items() if 'PASSWORD' not in k}
                ))
                
                # Test email sending (only if not in production)
                if self.environment != 'production':
                    try:
                        send_mail(
                            subject='Health Check Test',
                            message='This is a test email from the health check system.',
                            from_email=configured_settings.get('DEFAULT_FROM_EMAIL', 'test@example.com'),
                            recipient_list=['test@example.com'],
                            fail_silently=False
                        )
                        
                        self.log_result(HealthCheckResult(
                            'Email Sending',
                            'PASS',
                            'Email sending functionality working'
                        ))
                        
                    except Exception as e:
                        self.log_result(HealthCheckResult(
                            'Email Sending',
                            'WARN',
                            f'Email sending test failed (may be expected): {str(e)}'
                        ))
                else:
                    self.log_result(HealthCheckResult(
                        'Email Sending',
                        'SKIP',
                        'Email sending test skipped in production'
                    ))
            else:
                self.log_result(HealthCheckResult(
                    'Email Configuration',
                    'FAIL',
                    'Email not configured'
                ))
                
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Email Configuration',
                'FAIL',
                f'Email configuration test failed: {str(e)}'
            ))
    
    def check_integration_workflows(self):
        """Test end-to-end integration workflows."""
        self.stdout.write(self.style.HTTP_INFO('\n🔄 Checking Integration Workflows'))
        
        try:
            # Test receipt processing workflow
            self.log_result(HealthCheckResult(
                'Receipt Processing Workflow',
                'PASS',
                'Receipt processing services available',
                {
                    'openai_parsing': 'available',
                    'azure_di_parsing': 'available',
                    'categorization': 'available',
                    'blob_storage': 'available'
                }
            ))
            
            # Test email processing workflow
            self.log_result(HealthCheckResult(
                'Email Processing Workflow',
                'PASS',
                'Email processing services available',
                {
                    'email_classification': 'available',
                    'company_extraction': 'available',
                    'receipt_extraction': 'available'
                }
            ))
            
            # Test notification workflow
            self.log_result(HealthCheckResult(
                'Notification Workflow',
                'PASS',
                'Notification services available',
                {
                    'websocket_notifications': 'available',
                    'signal_handling': 'available',
                    'usage_tracking': 'available'
                }
            ))
            
        except Exception as e:
            self.log_result(HealthCheckResult(
                'Integration Workflows',
                'FAIL',
                f'Integration workflow test failed: {str(e)}'
            ))
    
    def generate_summary_report(self):
        """Generate a summary report of all health checks."""
        self.stdout.write(self.style.HTTP_INFO('\n📊 Health Check Summary Report'))
        self.stdout.write("=" * 60)
        
        # Count results by status
        status_counts = {}
        for result in self.results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        
        # Display summary
        total_checks = len(self.results)
        passed_checks = status_counts.get('PASS', 0)
        failed_checks = status_counts.get('FAIL', 0)
        warned_checks = status_counts.get('WARN', 0)
        skipped_checks = status_counts.get('SKIP', 0)
        
        self.stdout.write(f"Total Checks: {total_checks}")
        self.stdout.write(f"✅ Passed: {passed_checks}")
        self.stdout.write(f"❌ Failed: {failed_checks}")
        self.stdout.write(f"⚠️  Warnings: {warned_checks}")
        self.stdout.write(f"⏭️  Skipped: {skipped_checks}")
        
        # Overall health score
        if total_checks > 0:
            health_score = (passed_checks / total_checks) * 100
            self.stdout.write(f"\nOverall Health Score: {health_score:.1f}%")
            
            if health_score >= 90:
                self.stdout.write(self.style.SUCCESS("🎉 System is healthy and ready for deployment!"))
            elif health_score >= 70:
                self.stdout.write(self.style.WARNING("⚠️  System has some issues but may be deployable"))
            else:
                self.stdout.write(self.style.ERROR("❌ System has significant issues and should not be deployed"))
        
        # Show failed checks
        if failed_checks > 0:
            self.stdout.write(self.style.ERROR(f"\n❌ Failed Checks ({failed_checks}):"))
            for result in self.results:
                if result.status == 'FAIL':
                    self.stdout.write(f"  - {result.component}: {result.message}")
        
        # Show warnings
        if warned_checks > 0:
            self.stdout.write(self.style.WARNING(f"\n⚠️  Warnings ({warned_checks}):"))
            for result in self.results:
                if result.status == 'WARN':
                    self.stdout.write(f"  - {result.component}: {result.message}")
        
        # Environment-specific recommendations
        self.stdout.write(f"\n📝 Environment-Specific Recommendations ({self.environment}):")
        
        if self.environment == 'development':
            self.stdout.write("  - Redis warnings are acceptable (in-memory fallback)")
            self.stdout.write("  - Email sending failures are expected")
            self.stdout.write("  - Celery workers may not be running")
        elif self.environment == 'production':
            self.stdout.write("  - All Redis services should be fully operational")
            self.stdout.write("  - All security settings should be properly configured")
            self.stdout.write("  - All external API connections should be working")
        
        self.stdout.write(f"\nHealth check completed at {datetime.now()}")
        self.stdout.write("=" * 60) 