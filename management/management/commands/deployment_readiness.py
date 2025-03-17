"""
Deployment Readiness Check for Squirll

This management command performs a comprehensive deployment readiness assessment:
- Runs system health checks
- Validates environment configuration
- Checks security settings
- Verifies external service dependencies
- Provides deployment recommendations
- Generates deployment checklist

Usage:
    python manage.py deployment_readiness
    python manage.py deployment_readiness --environment production
    python manage.py deployment_readiness --export-report
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Any

from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.management import call_command
from django.core.management.color import no_style
from django.db import connection

from .system_health_check import Command as HealthCheckCommand, HealthCheckResult


class DeploymentReadinessResult:
    """Represents deployment readiness assessment result."""
    
    def __init__(self, category: str, status: str, message: str, recommendations: List[str] = None):
        self.category = category
        self.status = status  # 'READY', 'NOT_READY', 'WARNING', 'INFO'
        self.message = message
        self.recommendations = recommendations or []
        self.timestamp = datetime.now()
    
    def __str__(self):
        status_symbols = {
            'READY': '✅',
            'NOT_READY': '❌',
            'WARNING': '⚠️',
            'INFO': 'ℹ️'
        }
        return f"{status_symbols.get(self.status, '?')} {self.category}: {self.message}"


class Command(BaseCommand):
    help = 'Comprehensive deployment readiness assessment for Squirll'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--environment',
            type=str,
            default='production',
            help='Target deployment environment (development, staging, production)',
        )
        parser.add_argument(
            '--export-report',
            action='store_true',
            help='Export detailed report to JSON file',
        )
        parser.add_argument(
            '--skip-health-check',
            action='store_true',
            help='Skip the system health check',
        )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.results: List[DeploymentReadinessResult] = []
        self.health_check_results: List[HealthCheckResult] = []
        self.environment = 'production'
        self.export_report = False
    
    def handle(self, *args, **options):
        self.environment = options['environment']
        self.export_report = options['export_report']
        
        self.stdout.write(self.style.SUCCESS('🚀 Deployment Readiness Assessment'))
        self.stdout.write(f"Target Environment: {self.environment}")
        self.stdout.write("=" * 60)
        
        # Run system health check first
        if not options['skip_health_check']:
            self.run_health_check()
        
        # Run deployment-specific checks
        self.check_environment_configuration()
        self.check_security_settings()
        self.check_production_readiness()
        self.check_performance_settings()
        self.check_monitoring_setup()
        self.check_backup_and_recovery()
        self.check_external_dependencies()
        
        # Generate deployment report
        self.generate_deployment_report()
        
        # Export report if requested
        if self.export_report:
            self.export_deployment_report()
        
        # Generate deployment checklist
        self.generate_deployment_checklist()
        
        # Exit with appropriate code
        not_ready_checks = [r for r in self.results if r.status == 'NOT_READY']
        if not_ready_checks:
            self.stdout.write(self.style.ERROR(f"\n❌ Deployment NOT READY: {len(not_ready_checks)} critical issues found"))
            exit(1)
        else:
            self.stdout.write(self.style.SUCCESS(f"\n✅ Deployment READY for {self.environment}!"))
    
    def run_health_check(self):
        """Run the comprehensive health check."""
        self.stdout.write(self.style.HTTP_INFO('Running System Health Check...'))
        
        # Create a health check command instance
        health_check = HealthCheckCommand()
        health_check.environment = self.environment
        health_check.verbose = False
        
        try:
            # Run all health check components
            health_check.run_all_components()
            self.health_check_results = health_check.results
            
            # Analyze health check results
            failed_checks = [r for r in self.health_check_results if r.status == 'FAIL']
            warned_checks = [r for r in self.health_check_results if r.status == 'WARN']
            
            if failed_checks:
                self.results.append(DeploymentReadinessResult(
                    'Health Check',
                    'NOT_READY',
                    f'{len(failed_checks)} critical system components failed health check',
                    [f"Fix {r.component}: {r.message}" for r in failed_checks]
                ))
            elif warned_checks:
                self.results.append(DeploymentReadinessResult(
                    'Health Check',
                    'WARNING',
                    f'{len(warned_checks)} system components have warnings',
                    [f"Review {r.component}: {r.message}" for r in warned_checks]
                ))
            else:
                self.results.append(DeploymentReadinessResult(
                    'Health Check',
                    'READY',
                    'All system components passed health check'
                ))
                
        except Exception as e:
            self.results.append(DeploymentReadinessResult(
                'Health Check',
                'NOT_READY',
                f'Health check failed to run: {str(e)}',
                ['Fix health check system before proceeding']
            ))
    
    def check_environment_configuration(self):
        """Check environment-specific configuration."""
        self.stdout.write(self.style.HTTP_INFO('Checking Environment Configuration...'))
        
        # Check environment detection
        detected_env = getattr(settings, 'ENVIRONMENT', 'unknown')
        if detected_env == self.environment:
            self.results.append(DeploymentReadinessResult(
                'Environment Detection',
                'READY',
                f'Environment correctly detected as {detected_env}'
            ))
        else:
            self.results.append(DeploymentReadinessResult(
                'Environment Detection',
                'NOT_READY',
                f'Environment mismatch: detected {detected_env}, expected {self.environment}',
                ['Set correct environment variables', 'Verify settings module']
            ))
        
        # Check critical environment variables
        critical_vars = {
            'production': [
                'SECRET_KEY',
                'REDIS_HOST',
                'REDIS_PASSWORD',
                'AZURE_STORAGE_ACCOUNT_NAME',
                'AZURE_STORAGE_ACCOUNT_KEY',
                'OPENAI_API_KEY',
                'TWILIO_ACCOUNT_SID',
                'TWILIO_ACCOUNT_AUTH_TOKEN',
            ],
            'staging': [
                'SECRET_KEY',
                'AZURE_STORAGE_ACCOUNT_NAME',
                'AZURE_STORAGE_ACCOUNT_KEY',
                'OPENAI_API_KEY',
            ],
            'development': [
                'SECRET_KEY',
            ]
        }
        
        required_vars = critical_vars.get(self.environment, [])
        missing_vars = []
        
        for var in required_vars:
            if not os.environ.get(var):
                missing_vars.append(var)
        
        if missing_vars:
            self.results.append(DeploymentReadinessResult(
                'Environment Variables',
                'NOT_READY',
                f'{len(missing_vars)} required environment variables missing',
                [f'Set {var} environment variable' for var in missing_vars]
            ))
        else:
            self.results.append(DeploymentReadinessResult(
                'Environment Variables',
                'READY',
                f'All {len(required_vars)} required environment variables are set'
            ))
    
    def check_security_settings(self):
        """Check security settings for deployment."""
        self.stdout.write(self.style.HTTP_INFO('Checking Security Settings...'))
        
        security_issues = []
        security_warnings = []
        
        if self.environment == 'production':
            # Critical security settings for production
            security_checks = [
                ('DEBUG', False, 'DEBUG must be False in production'),
                ('SECURE_SSL_REDIRECT', True, 'SSL redirect must be enabled'),
                ('SECURE_HSTS_SECONDS', lambda x: x > 0, 'HSTS must be configured'),
                ('SESSION_COOKIE_SECURE', True, 'Session cookies must be secure'),
                ('CSRF_COOKIE_SECURE', True, 'CSRF cookies must be secure'),
                ('SECURE_CONTENT_TYPE_NOSNIFF', True, 'Content type nosniff must be enabled'),
                ('SECURE_BROWSER_XSS_FILTER', True, 'XSS filter must be enabled'),
                ('X_FRAME_OPTIONS', 'DENY', 'X-Frame-Options must be set to DENY'),
            ]
            
            for setting_name, expected, message in security_checks:
                if hasattr(settings, setting_name):
                    value = getattr(settings, setting_name)
                    if callable(expected):
                        is_valid = expected(value)
                    else:
                        is_valid = value == expected
                    
                    if not is_valid:
                        security_issues.append(f"{setting_name}: {message}")
                else:
                    security_issues.append(f"{setting_name}: Setting not configured")
            
            # Check ALLOWED_HOSTS
            allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
            if not allowed_hosts or allowed_hosts == ['*']:
                security_issues.append('ALLOWED_HOSTS: Must be configured with specific domains')
            
            # Check SECRET_KEY strength
            secret_key = getattr(settings, 'SECRET_KEY', '')
            if len(secret_key) < 50:
                security_issues.append('SECRET_KEY: Must be at least 50 characters long')
            if secret_key == 'dev-secret-key-change-in-production':
                security_issues.append('SECRET_KEY: Must not use development default')
        
        elif self.environment == 'staging':
            # Less strict security for staging
            if getattr(settings, 'DEBUG', True):
                security_warnings.append('DEBUG: Consider disabling DEBUG in staging')
        
        # Check CORS settings
        cors_allow_all = getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False)
        if cors_allow_all and self.environment == 'production':
            security_issues.append('CORS_ALLOW_ALL_ORIGINS: Must be False in production')
        
        # Generate results
        if security_issues:
            self.results.append(DeploymentReadinessResult(
                'Security Settings',
                'NOT_READY',
                f'{len(security_issues)} security issues found',
                security_issues
            ))
        elif security_warnings:
            self.results.append(DeploymentReadinessResult(
                'Security Settings',
                'WARNING',
                f'{len(security_warnings)} security warnings',
                security_warnings
            ))
        else:
            self.results.append(DeploymentReadinessResult(
                'Security Settings',
                'READY',
                'All security settings properly configured'
            ))
    
    def check_production_readiness(self):
        """Check production-specific readiness."""
        self.stdout.write(self.style.HTTP_INFO('Checking Production Readiness...'))
        
        if self.environment != 'production':
            self.results.append(DeploymentReadinessResult(
                'Production Readiness',
                'INFO',
                f'Production checks skipped for {self.environment} environment'
            ))
            return
        
        production_issues = []
        
        # Check database configuration
        db_config = settings.DATABASES.get('default', {})
        if 'sqlite' in db_config.get('ENGINE', '').lower():
            production_issues.append('Database: SQLite not recommended for production')
        
        # Check static files configuration
        if not hasattr(settings, 'STATIC_ROOT'):
            production_issues.append('STATIC_ROOT: Must be configured for production')
        
        # Check media files configuration
        if not hasattr(settings, 'MEDIA_ROOT') and not hasattr(settings, 'AZURE_STORAGE_ACCOUNT_NAME'):
            production_issues.append('Media Storage: Must configure MEDIA_ROOT or Azure Storage')
        
        # Check logging configuration
        if not hasattr(settings, 'LOGGING') or not settings.LOGGING:
            production_issues.append('Logging: Must configure logging for production')
        
        # Check email configuration
        email_backend = getattr(settings, 'EMAIL_BACKEND', '')
        if 'console' in email_backend.lower():
            production_issues.append('Email: Console backend not suitable for production')
        
        if production_issues:
            self.results.append(DeploymentReadinessResult(
                'Production Readiness',
                'NOT_READY',
                f'{len(production_issues)} production issues found',
                production_issues
            ))
        else:
            self.results.append(DeploymentReadinessResult(
                'Production Readiness',
                'READY',
                'All production requirements met'
            ))
    
    def check_performance_settings(self):
        """Check performance-related settings."""
        self.stdout.write(self.style.HTTP_INFO('Checking Performance Settings...'))
        
        performance_recommendations = []
        
        # Check database connection pooling
        if self.environment == 'production':
            db_config = settings.DATABASES.get('default', {})
            if 'CONN_MAX_AGE' not in db_config:
                performance_recommendations.append('Database: Consider setting CONN_MAX_AGE for connection pooling')
        
        # Check caching configuration
        cache_config = settings.CACHES.get('default', {})
        cache_backend = cache_config.get('BACKEND', '')
        
        if 'locmem' in cache_backend and self.environment == 'production':
            performance_recommendations.append('Cache: Use Redis instead of local memory cache in production')
        elif 'redis' in cache_backend:
            self.results.append(DeploymentReadinessResult(
                'Cache Configuration',
                'READY',
                'Redis cache properly configured'
            ))
        
        # Check Celery configuration
        if hasattr(settings, 'CELERY_BROKER_URL'):
            self.results.append(DeploymentReadinessResult(
                'Celery Configuration',
                'READY',
                'Celery properly configured for async tasks'
            ))
        else:
            performance_recommendations.append('Celery: Consider configuring Celery for async task processing')
        
        # Check database indexes
        self.results.append(DeploymentReadinessResult(
            'Database Indexes',
            'INFO',
            'Review database indexes for query performance',
            ['Run EXPLAIN on slow queries', 'Monitor query performance']
        ))
        
        if performance_recommendations:
            self.results.append(DeploymentReadinessResult(
                'Performance Settings',
                'WARNING',
                f'{len(performance_recommendations)} performance recommendations',
                performance_recommendations
            ))
        else:
            self.results.append(DeploymentReadinessResult(
                'Performance Settings',
                'READY',
                'Performance settings optimized'
            ))
    
    def check_monitoring_setup(self):
        """Check monitoring and logging setup."""
        self.stdout.write(self.style.HTTP_INFO('Checking Monitoring Setup...'))
        
        monitoring_issues = []
        
        # Check Application Insights
        if hasattr(settings, 'AZURE_APPLICATION_INSIGHTS_ENABLED'):
            if settings.AZURE_APPLICATION_INSIGHTS_ENABLED:
                self.results.append(DeploymentReadinessResult(
                    'Application Insights',
                    'READY',
                    'Application Insights monitoring enabled'
                ))
            else:
                monitoring_issues.append('Application Insights: Monitoring disabled')
        else:
            monitoring_issues.append('Application Insights: Not configured')
        
        # Check Sentry configuration
        sentry_dsn = getattr(settings, 'SENTRY_DSN', '')
        if sentry_dsn:
            self.results.append(DeploymentReadinessResult(
                'Sentry Error Tracking',
                'READY',
                'Sentry error tracking configured'
            ))
        else:
            monitoring_issues.append('Sentry: Error tracking not configured')
        
        # Check logging configuration
        if hasattr(settings, 'LOGGING') and settings.LOGGING:
            self.results.append(DeploymentReadinessResult(
                'Logging Configuration',
                'READY',
                'Logging properly configured'
            ))
        else:
            monitoring_issues.append('Logging: Not properly configured')
        
        if monitoring_issues:
            self.results.append(DeploymentReadinessResult(
                'Monitoring Setup',
                'WARNING',
                f'{len(monitoring_issues)} monitoring issues found',
                monitoring_issues
            ))
        else:
            self.results.append(DeploymentReadinessResult(
                'Monitoring Setup',
                'READY',
                'All monitoring systems configured'
            ))
    
    def check_backup_and_recovery(self):
        """Check backup and recovery procedures."""
        self.stdout.write(self.style.HTTP_INFO('Checking Backup and Recovery...'))
        
        backup_recommendations = [
            'Database: Ensure automated database backups are configured',
            'Media Files: Ensure Azure Blob Storage has backup policies',
            'Configuration: Backup environment configuration and secrets',
            'Recovery: Test recovery procedures regularly',
            'Monitoring: Monitor backup success/failure',
        ]
        
        self.results.append(DeploymentReadinessResult(
            'Backup and Recovery',
            'INFO',
            'Review backup and recovery procedures',
            backup_recommendations
        ))
    
    def check_external_dependencies(self):
        """Check external service dependencies."""
        self.stdout.write(self.style.HTTP_INFO('Checking External Dependencies...'))
        
        dependencies = []
        
        # Check configured external services
        if hasattr(settings, 'OPENAI_API_KEY') and settings.OPENAI_API_KEY:
            dependencies.append('OpenAI API: Configured ✓')
        
        if hasattr(settings, 'TWILIO_ACCOUNT_SID') and settings.TWILIO_ACCOUNT_SID:
            dependencies.append('Twilio API: Configured ✓')
        
        if hasattr(settings, 'AZURE_STORAGE_ACCOUNT_NAME') and settings.AZURE_STORAGE_ACCOUNT_NAME:
            dependencies.append('Azure Blob Storage: Configured ✓')
        
        if hasattr(settings, 'DOCUMENT_INTELLIGENCE_ENDPOINT') and settings.DOCUMENT_INTELLIGENCE_ENDPOINT:
            dependencies.append('Azure Document Intelligence: Configured ✓')
        
        if hasattr(settings, 'GOOGLE_OAUTH2_CLIENT_ID') and settings.GOOGLE_OAUTH2_CLIENT_ID:
            dependencies.append('Google OAuth: Configured ✓')
        
        self.results.append(DeploymentReadinessResult(
            'External Dependencies',
            'READY',
            f'{len(dependencies)} external services configured',
            dependencies
        ))
    
    def generate_deployment_report(self):
        """Generate comprehensive deployment report."""
        self.stdout.write(self.style.HTTP_INFO('\n📊 Deployment Readiness Report'))
        self.stdout.write("=" * 60)
        
        # Count results by status
        status_counts = {}
        for result in self.results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        
        # Display summary
        total_checks = len(self.results)
        ready_checks = status_counts.get('READY', 0)
        not_ready_checks = status_counts.get('NOT_READY', 0)
        warning_checks = status_counts.get('WARNING', 0)
        info_checks = status_counts.get('INFO', 0)
        
        self.stdout.write(f"Total Checks: {total_checks}")
        self.stdout.write(f"✅ Ready: {ready_checks}")
        self.stdout.write(f"❌ Not Ready: {not_ready_checks}")
        self.stdout.write(f"⚠️  Warnings: {warning_checks}")
        self.stdout.write(f"ℹ️  Info: {info_checks}")
        
        # Calculate deployment readiness score
        if total_checks > 0:
            readiness_score = (ready_checks / total_checks) * 100
            self.stdout.write(f"\nDeployment Readiness Score: {readiness_score:.1f}%")
        
        # Show all results
        for result in self.results:
            self.stdout.write(f"\n{result}")
            if result.recommendations:
                for rec in result.recommendations:
                    self.stdout.write(f"  → {rec}")
    
    def generate_deployment_checklist(self):
        """Generate deployment checklist."""
        self.stdout.write(self.style.HTTP_INFO(f'\n📋 Deployment Checklist for {self.environment}'))
        self.stdout.write("=" * 60)
        
        checklist = []
        
        # Pre-deployment
        checklist.extend([
            "□ Run system health check",
            "□ Run deployment readiness assessment",
            "□ Review and test all environment variables",
            "□ Verify database migrations are up to date",
            "□ Test all external API connections",
            "□ Review security settings",
            "□ Backup current production data (if applicable)",
        ])
        
        # Deployment
        checklist.extend([
            "□ Deploy application code",
            "□ Run database migrations",
            "□ Collect static files",
            "□ Start/restart application services",
            "□ Start Celery workers",
            "□ Verify WebSocket connectivity",
        ])
        
        # Post-deployment
        checklist.extend([
            "□ Test critical user workflows",
            "□ Verify monitoring and logging",
            "□ Test receipt upload functionality",
            "□ Test email receipt processing",
            "□ Check error rates and performance",
            "□ Verify backup systems",
        ])
        
        for item in checklist:
            self.stdout.write(item)
        
        self.stdout.write(f"\n📅 Deployment assessment completed at {datetime.now()}")
    
    def export_deployment_report(self):
        """Export deployment report to JSON file."""
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'environment': self.environment,
            'results': [
                {
                    'category': r.category,
                    'status': r.status,
                    'message': r.message,
                    'recommendations': r.recommendations,
                    'timestamp': r.timestamp.isoformat()
                }
                for r in self.results
            ],
            'health_check_results': [
                {
                    'component': r.component,
                    'status': r.status,
                    'message': r.message,
                    'details': r.details,
                    'timestamp': r.timestamp.isoformat()
                }
                for r in self.health_check_results
            ]
        }
        
        filename = f'deployment_readiness_{self.environment}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        with open(filename, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        self.stdout.write(f"\n📄 Deployment report exported to {filename}") 