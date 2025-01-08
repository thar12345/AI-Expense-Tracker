"""
Django settings loader for squirll project.
"""
import os
from .base import *

# Load environment-specific settings
environment = os.environ.get('DJANGO_ENV', 'development')

if environment == 'production':
    from .production import *
elif environment == 'staging':
    from .staging import *
else:
    from .development import * 