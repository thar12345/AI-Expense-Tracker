"""
Staging settings for squirll project.
Similar to production but with additional debugging capabilities.
Uses Redis for caching and channels (inherited from production).
"""
from .production import *  # Import production settings as base
from .env_utils import EnvValidator

# Initialize staging environment validator
env_validator = EnvValidator("staging")

DEBUG = False  # Disable debug in staging for production-like behavior

ALLOWED_HOSTS = [
    # Staging/UAT backend
    "app-squirll-services-uat-rdy.azurewebsites.net",
    # Staging/UAT frontend
    "app-squirll-web-uat-rdy.azurewebsites.net",
]

# CORS settings for staging - include UAT web frontend
CORS_ALLOWED_ORIGINS = [
    "https://app-squirll-web-uat-rdy.azurewebsites.net",
]

# CSRF settings for staging
CSRF_TRUSTED_ORIGINS = [
    "https://app-squirll-services-uat-rdy.azurewebsites.net",
    "https://app-squirll-web-uat-rdy.azurewebsites.net",
]

# Redis configuration inherited from production settings
# No need to override - staging uses the same Redis setup as production

# Override any production settings that need to be different in staging
LOGGING["root"]["level"] = "DEBUG"  # More verbose logging in staging

# Validate staging settings
env_validator.validate_and_raise() 
