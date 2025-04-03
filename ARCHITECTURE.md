# CLAUDE.md - Comprehensive Project Guide

This file provides comprehensive guidance to Claude Code (claude.ai/code) when working with the Squirll expense management system.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Project Architecture](#project-architecture)
3. [Database Models & Relationships](#database-models--relationships)
4. [API Endpoints & Views](#api-endpoints--views)
5. [Service Layer Architecture](#service-layer-architecture)
6. [Authentication & Authorization](#authentication--authorization)
7. [Real-time Communication](#real-time-communication)
8. [Settings & Environment Management](#settings--environment-management)
9. [Azure Cloud Integrations](#azure-cloud-integrations)
10. [Testing Strategy](#testing-strategy)
11. [Common Development Patterns](#common-development-patterns)
12. [Performance & Optimization](#performance--optimization)
13. [Security Considerations](#security-considerations)
14. [Deployment & Infrastructure](#deployment--infrastructure)
15. [Troubleshooting Guide](#troubleshooting-guide)

---

## Quick Start

### Essential Setup
```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Environment setup
cp .env.example .env  # Configure your environment variables

# Database setup
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

### Running the Application
```bash
# Development server
python manage.py runserver

# With specific environment
python manage.py runserver --settings=squirll.settings.development

# Run Celery worker (separate terminal)
celery -A squirll worker --loglevel=info

# Run Celery beat scheduler (separate terminal)
celery -A squirll beat --loglevel=info
```

### Testing
```bash
# Run all tests
python manage.py test

# Run with pytest (configured in pytest.ini)
pytest

# Run tests for specific app
pytest receipt_mgmt/tests/

# Run single test file
pytest receipt_mgmt/tests/test_categorization.py

# Run tests with coverage
pytest --cov=.
```

---

## Project Architecture

### Multi-Environment Settings Structure
```
squirll/settings/
├── __init__.py
├── base.py              # Common settings and configurations
├── development.py       # Development environment (Redis optional)
├── production.py        # Production environment (Redis required)
├── staging.py          # Staging environment
└── env_utils.py        # Environment validation utilities
```

### Core Apps Architecture

#### **core** - Foundation & Authentication
- **Purpose**: User management, authentication, base models, shared utilities
- **Key Models**: `UserProfile`, `UsageTracker`
- **Services**: Phone authentication, Google OAuth, JWT token management
- **Utilities**: QR code generation, database connection testing

#### **receipt_mgmt** - Receipt Processing Engine
- **Purpose**: Receipt OCR, AI categorization, expense tracking
- **Key Models**: `Receipt`, `Item`, `Tag`
- **Services**: 
  - Image processing (OpenAI GPT-4 Vision, Azure Document Intelligence)
  - AI categorization (OpenAI GPT-4o-mini)
  - Receipt parsing from email/image
  - Azure Blob Storage integration
- **Utilities**: Azure storage management, image stitching

#### **email_mgmt** - Email Processing & Management
- **Purpose**: Email ingestion, parsing, categorization
- **Key Models**: `Email`
- **Services**: Email classification (marketing vs transactional), company extraction
- **Integration**: SendGrid Inbound Parse webhook

#### **analytics** - Reporting & Analytics
- **Purpose**: Expense analytics, report generation
- **Key Features**: Category spend analysis, time-based reporting, PDF/CSV exports
- **Services**: Report generation, usage tracking

---

## Database Models & Relationships

### User Management (`core.models`)

#### UserProfile (Custom User Model)
```python
class UserProfile(AbstractUser):
    # Standard Django fields: username, email, password, first_name, last_name
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    
    # Subscription management
    subscription_type = models.CharField(
        max_length=10,
        choices=[('free', 'Free'), ('premium', 'Premium')],
        default='free',
        db_index=True
    )
    
    # Email receipts integration
    squirll_id = models.EmailField(
        unique=True, null=True, blank=True,
        help_text="Pseudo e-mail to receive email receipts"
    )
    
    @property
    def is_premium(self) -> bool:
        return self.subscription_type == 'premium'
```

#### UsageTracker (Usage Monitoring)
```python
class UsageTracker(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="trackers")
    usage_type = models.CharField(max_length=50, choices=[
        ('receipt_upload', 'Receipt Upload'),
        ('chatbot_use', 'Chatbot Use'),
        ('report_upload', 'Report Download'),
    ])
    date = models.DateField(default=datetime.date.today)
    count = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ('user', 'usage_type', 'date')
```

### Receipt Management (`receipt_mgmt.models`)

#### Receipt (Core Receipt Model)
```python
class Receipt(models.Model):
    # Receipt categorization using integer choices for performance
    class ReceiptType(models.IntegerChoices):
        GROCERIES = 1, 'Groceries'
        APPAREL = 2, 'Apparel'
        DINING_OUT = 3, 'Dining Out'
        ELECTRONICS = 4, 'Electronics'
        # ... 17 total categories
    
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="receipts")
    
    # Merchant information
    company = models.CharField(max_length=255)
    company_phone = models.CharField(max_length=255, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    country_region = models.TextField(blank=True, null=True)
    
    # Transaction details
    date = models.DateField()
    time = models.TimeField(blank=True, null=True)
    sub_total = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    tax = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    tax_rate = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    tip = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    # Classification
    receipt_type = models.IntegerField(choices=ReceiptType.choices, default=ReceiptType.OTHER)
    
    # Currency information
    receipt_currency_symbol = models.CharField(blank=True, max_length=5)
    receipt_currency_code = models.CharField(blank=True, max_length=5)
    
    # Metadata
    item_count = models.PositiveIntegerField(default=0)
    raw_email = models.TextField(blank=True, null=True)  # For email receipts
    raw_images = models.JSONField(default=list, blank=True)  # Azure blob URLs
    manual_entry = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Relationships
    tags = models.ManyToManyField("Tag", blank=True, related_name="receipts")
    
    # Database indexes for performance
    class Meta:
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'company', '-created_at']),
            models.Index(fields=['user', 'receipt_type', '-created_at']),
        ]
        ordering = ['-created_at']
```

#### Item (Receipt Line Items)
```python
class Item(models.Model):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="items")
    
    # Product information
    description = models.TextField(default="Unknown")
    product_id = models.TextField(blank=True)
    
    # Quantity and pricing
    quantity = models.DecimalField(blank=True, null=True, default=1, decimal_places=5, max_digits=10)
    quantity_unit = models.TextField(blank=True, null=True, default="Unit(s)")
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # AI categorization
    item_category = models.IntegerField(
        choices=Receipt.ReceiptType.choices,
        default=Receipt.ReceiptType.OTHER
    )
    
    class Meta:
        indexes = [
            models.Index(fields=['receipt', 'id']),
            models.Index(fields=['item_category']),
        ]
```

#### Tag (User-defined Tags)
```python
class Tag(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=50)
    
    class Meta:
        unique_together = ("user", "name")
```

### Email Management (`email_mgmt.models`)

#### Email (Email Processing)
```python
class Email(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="emails")
    
    # Email metadata
    sender = models.TextField(help_text="The full 'From' header")
    subject = models.CharField(max_length=255, blank=True, null=True)
    company = models.CharField(max_length=255, default="Miscellaneous")
    
    # Email content
    html = models.TextField(help_text="HTML version of the email body")
    text_content = models.TextField(blank=True, null=True)
    raw_email = models.TextField(help_text="Complete raw MIME email content")
    headers = models.TextField(blank=True, null=True)
    attachments = models.JSONField(default=dict)
    
    # Classification
    MARKETING = "marketing"
    MESSAGE = "message"
    CATEGORY_CHOICES = [
        (MARKETING, "Marketing / Promotions"),
        (MESSAGE, "Primary / Messages"),
    ]
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default=MESSAGE, db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'company', '-created_at']),
            models.Index(fields=['user', 'category', '-created_at']),
        ]
        ordering = ['-created_at']
```

---

## API Endpoints & Views

### Authentication Endpoints (`core/urls.py`)

```python
# Authentication
POST /core/auth/signup/           # User registration
POST /core/auth/login/            # User login
POST /core/auth/google/           # Google OAuth login

# JWT Token Management
POST /core/token/refresh/         # Refresh access token
POST /core/token/blacklist/       # Blacklist refresh token

# User Onboarding
POST /core/user/set-squirll-id/   # Set email receipt ID
POST /core/user/set-phone/        # Initiate phone verification
POST /core/user/auth-set-phone/   # Complete phone verification

# User Profile
GET  /core/user/profile/          # Get user profile

# Utilities
GET  /core/qr-code/generate/      # Generate QR code
GET  /core/test-db-connection/    # Test database connectivity
```

### Receipt Management Endpoints (`receipt_mgmt/urls.py`)

```python
# Receipt Upload
POST /receipt-mgmt/receipt/upload/image/       # Upload receipt images (OpenAI)
POST /receipt-mgmt/receipt/upload/image-azure/ # Upload receipt images (Azure DI)
POST /receipt-mgmt/receipt/upload/manual/      # Manual receipt entry

# Receipt Retrieval
GET  /receipt-mgmt/receipts/                   # List receipts (filtered, paginated)
GET  /receipt-mgmt/receipts/by-vendor/         # Group receipts by vendor
GET  /receipt-mgmt/receipts/<int:pk>/          # Receipt detail
GET  /receipt-mgmt/receipts/search/            # Smart search (company + items)

# Receipt Images
GET  /receipt-mgmt/receipt/<int:receipt_id>/image/<int:idx>/ # Get receipt image URL

# Tag Management
GET  /receipt-mgmt/tag/listall/                # List all user tags
POST /receipt-mgmt/tag/add/                    # Add tag to receipt
POST /receipt-mgmt/tag/remove/                 # Remove tag from receipt
DELETE /receipt-mgmt/tag/delete/<int:tag_id>/  # Delete tag
PUT  /receipt-mgmt/tag/edit-name/              # Edit tag name
```

### Email Management Endpoints (`email_mgmt/urls.py`)

```python
# Email Retrieval
GET  /email-mgmt/emails/                # List emails (filtered, paginated)
GET  /email-mgmt/emails/by-vendor/      # Group emails by company
GET  /email-mgmt/emails/<int:pk>/       # Email detail

# Email Ingestion (SendGrid Webhook)
POST /email-mgmt/emails/create/         # Email ingestion endpoint
```

### Analytics Endpoints (`analytics/urls.py`)

```python
# Analytics
GET  /analytics/category-spend/         # Spending by category
GET  /analytics/weekly-total/           # Weekly spending total

# Report Generation
GET  /analytics/report/select-receipts/pdf/<str:receipt_ids>/ # PDF report
GET  /analytics/report/select-receipts/csv/<str:receipt_ids>/ # CSV report
```

### View Classes & Patterns

#### Generic Views Pattern
```python
class ReceiptListView(ListAPIView):
    serializer_class = ReceiptListSerializer
    filterset_class = ReceiptFilter
    ordering_fields = ["created_at", "total", "date"]
    ordering = ["-created_at"]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Receipt.objects.filter(user=self.request.user)\
                             .select_related('user')\
                             .prefetch_related('items', 'tags')
```

#### Function-Based Views Pattern
```python
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def receipt_upload_image(request):
    # 1. Validate input
    # 2. Process business logic
    # 3. Save to database
    # 4. Send signals/notifications
    # 5. Return response
```

---

## Service Layer Architecture

### Receipt Processing Services (`receipt_mgmt/services/`)

#### `img_receipt_engine.py` - Azure Document Intelligence
```python
def extract_receipt(image, *, endpoint: str, key: str, poll_timeout: int = 60) -> Dict[str, Any]:
    """
    Parse receipt image with Azure Document Intelligence.
    
    Process:
    1. Load image as bytes
    2. Call Azure Document Intelligence API
    3. Extract structured data (merchant, amounts, items)
    4. Format for ReceiptCreateSerializer
    5. Return structured receipt data
    """
```

#### `receipt_parsing.py` - OpenAI Receipt Processing
```python
def receipt_upload_image(request):
    """
    Process receipt images using OpenAI GPT-4 Vision.
    
    Process:
    1. Collect uploaded images
    2. Convert to base64 for OpenAI
    3. Send to GPT-4 Vision with structured schema
    4. Parse JSON response
    5. Validate with serializer
    6. Upload images to Azure Blob Storage
    7. Save receipt to database
    8. Send completion signal
    """

def receipt_upload_email(html_content, user):
    """
    Process email receipts using OpenAI GPT-4o-mini.
    
    Process:
    1. Extract HTML content
    2. Send to GPT-4o-mini with receipt schema
    3. Parse structured response
    4. Validate and save to database
    """
```

#### `spending_categorization.py` - AI Item Categorization
```python
def categorize_receipt_items(receipt: Receipt) -> Dict[str, any]:
    """
    Categorize receipt items using OpenAI GPT-4o-mini.
    
    Process:
    1. Extract item descriptions and product IDs
    2. Send to OpenAI with categorization guidelines
    3. Parse structured response
    4. Bulk update item categories
    5. Set receipt category to mode of item categories
    6. Return categorization statistics
    """
```

#### `receipt_image.py` - Azure Document Intelligence Integration
```python
def receipt_upload_image_azure(request):
    """
    Process receipt images using Azure Document Intelligence.
    
    Process:
    1. Validate uploaded images
    2. Stitch multiple images vertically
    3. Send to Azure Document Intelligence
    4. Parse structured response
    5. Validate and save receipt
    6. Upload original images to Azure Blob
    7. Trigger AI categorization
    8. Send completion signal
    """
```

### Core Services (`core/services/`)

#### `phone_auth.py` - Phone Verification
```python
def send_phone_verification_otp(user, phone_number) -> str:
    """Send OTP via Twilio and cache for verification."""

def verify_and_set_phone(user, otp_code_provided) -> str:
    """Verify OTP and set phone number on user account."""
```

### Email Services (`email_mgmt/services/`)

#### `email_processor.py` - Email Classification
```python
def is_marketing(raw_headers: str, subject: str) -> bool:
    """
    Classify email as marketing or transactional.
    
    Classification logic:
    1. Check for List-Unsubscribe/List-ID headers
    2. Detect ESP fingerprints (MailChimp, Klaviyo, etc.)
    3. Keyword analysis in subject line
    4. Return True for marketing, False for transactional
    """

def company_from_fromhdr(from_hdr: str) -> str:
    """Extract company name from email From header."""
```

---

## Authentication & Authorization

### JWT Authentication Strategy
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
}
```

### Authentication Flows

#### Standard Email/Password
1. `POST /core/auth/signup/` - Create account + return JWT tokens
2. `POST /core/auth/login/` - Authenticate + return JWT tokens
3. `POST /core/token/refresh/` - Refresh access token
4. `POST /core/token/blacklist/` - Logout (blacklist refresh token)

#### Google OAuth
1. Frontend obtains Google ID token
2. `POST /core/auth/google/` - Verify token + create/login user
3. Returns JWT tokens for subsequent API calls

#### Phone Verification
1. `POST /core/user/set-phone/` - Send OTP via Twilio
2. `POST /core/user/auth-set-phone/` - Verify OTP + set phone number

### Permission Classes
```python
# All API endpoints require authentication
permission_classes = [IsAuthenticated]

# Exception: SendGrid webhook endpoints (no auth required)
# Exception: Database connection test endpoint
```

### User Subscription System
```python
class UserProfile(AbstractUser):
    subscription_type = models.CharField(
        choices=[('free', 'Free'), ('premium', 'Premium')],
        default='free'
    )
    
    @property
    def is_premium(self) -> bool:
        return self.subscription_type == 'premium'
```

---

## Real-time Communication

### WebSocket Architecture

#### Consumer (`core/consumers.py`)
```python
class UserNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user_id = self.scope['url_route']['kwargs']['user_id']
        self.group_name = f"user_{self.user_id}"
        # Join user-specific group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
    
    async def new_receipt_notification(self, event):
        """Handle receipt upload notifications."""
        await self.send(json.dumps({
            "type": "new_receipt_notification",
            "receipt_id": event.get("receipt_id"),
        }))
    
    async def new_email_notification(self, event):
        """Handle email received notifications."""
        await self.send(json.dumps({
            "type": "new_email_notification",
            "email_id": event.get("email_id"),
            "subject": event.get("subject"),
            "category": event.get("category"),
            "company": event.get("company"),
        }))
```

#### Signal Handlers
```python
@receiver(receipt_uploaded)
def handle_receipt_uploaded(sender, user, receipt_id, **kwargs):
    """Send WebSocket notification when receipt is uploaded."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user.id}",
        {
            "type": "new_receipt_notification",
            "receipt_id": receipt_id,
        }
    )

@receiver(email_received)
def handle_email_received(sender, user, email_id, subject, category, company, **kwargs):
    """Send WebSocket notification when email is received."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{user.id}",
        {
            "type": "new_email_notification",
            "email_id": email_id,
            "subject": subject,
            "category": category,
            "company": company,
        }
    )
```

### WebSocket URL Pattern
```python
# squirll/routing.py
websocket_urlpatterns = [
    re_path(r'^ws/notify/(?P<user_id>\d+)/$', UserNotificationConsumer.as_asgi()),
]
```

---

## Settings & Environment Management

### Environment Validation (`squirll/settings/env_utils.py`)
```python
class EnvValidator:
    """Validates environment-specific configuration."""
    
    def __init__(self, environment: str):
        self.environment = environment
        self.errors = []
    
    def validate_database_config(self) -> dict:
        """Validate database configuration."""
    
    def validate_redis_config(self) -> dict:
        """Validate Redis configuration (optional in dev)."""
    
    def validate_azure_config(self) -> dict:
        """Validate Azure service configurations."""
    
    def validate_twilio_config(self) -> dict:
        """Validate Twilio configuration."""
```

### Environment-Specific Settings

#### Development (`development.py`)
- Redis optional with secure SSL (falls back to in-memory when Redis env vars not set)
- Debug mode enabled
- Permissive CORS for development
- Console logging
- Optional Application Insights

#### Production (`production.py`)
- Redis required with secure SSL connections
- Debug mode disabled
- Strict CORS policies
- HTTPS enforcement with SSL redirects
- HSTS security headers (31536000 seconds)
- Secure cookie settings (SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE)
- Additional security headers (SECURE_CONTENT_TYPE_NOSNIFF, SECURE_BROWSER_XSS_FILTER, X_FRAME_OPTIONS)
- Structured logging with Application Insights integration
- Required Application Insights

#### Staging (`staging.py`)
- Inherits from production settings
- Debug mode disabled
- UAT-specific CORS and CSRF origins
- Enhanced logging for debugging

#### Base Settings (`base.py`)
- Common configuration shared across environments
- Third-party app configuration (DRF, CORS, Channels)
- Middleware setup and security configuration
- JWT settings for authentication
- Celery configuration for async tasks
- OpenAI API integration for receipt processing
- Azure services configuration (Storage, Document Intelligence, Application Insights)
- Twilio configuration for phone verification
- Google OAuth configuration

---

## Azure Cloud Integrations

### Azure Document Intelligence
```python
# Service: receipt_mgmt/services/img_receipt_engine.py
def extract_receipt(image, *, endpoint: str, key: str) -> Dict[str, Any]:
    """
    Extract structured receipt data using Azure Document Intelligence.
    
    Features:
    - Prebuilt receipt model
    - Merchant information extraction
    - Line item parsing
    - Currency and amount detection
    - Tax and tip calculation
    """
```

### Azure Blob Storage
```python
# Service: receipt_mgmt/utils/azure_utils.py
def upload_receipt_image(image_data: bytes, content_type: str, *, user_id: int) -> str:
    """
    Upload receipt image to private Azure Blob Storage.
    
    Features:
    - User-specific blob organization
    - Content type validation
    - Unique blob naming
    - Private container access
    """

def make_private_download_url(blob_name: str, expires_in_hours: int = 24) -> str:
    """Generate time-limited SAS URL for private blob access."""
```

### Azure Application Insights
```python
# Configuration in base.py
OPENCENSUS = {
    'TRACE': {
        'SAMPLER': 'opencensus.trace.samplers.ProbabilitySampler(rate=0.1)',
        'EXPORTER': 'opencensus.ext.azure.trace_exporter.AzureExporter(...)',
    }
}
```

---

## Testing Strategy

### Test Structure
Each app has comprehensive test coverage:

```
app_name/tests/
├── __init__.py
├── test_models.py          # Model tests
├── test_views.py           # API endpoint tests
├── test_serializers.py     # Serialization tests
├── test_services.py        # Business logic tests
├── test_signals.py         # Signal handling tests
└── test_integration.py     # Integration tests
```

### Testing Patterns

#### Model Tests
```python
class ReceiptModelTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(...)
        self.receipt = Receipt.objects.create(...)
    
    def test_receipt_creation(self):
        """Test receipt model creation and validation."""
    
    def test_receipt_categorization(self):
        """Test receipt type categorization."""
```

#### API Tests
```python
class ReceiptAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(...)
        self.client.force_authenticate(user=self.user)
    
    def test_receipt_list_view(self):
        """Test receipt list endpoint."""
    
    def test_receipt_upload_image(self):
        """Test receipt image upload endpoint."""
```

#### Service Tests
```python
class ReceiptProcessingTestCase(TestCase):
    @patch('openai.chat.completions.create')
    def test_receipt_parsing(self, mock_openai):
        """Test receipt parsing service with mocked OpenAI."""
```

### Test Configuration
```python
# pytest.ini
[tool:pytest]
DJANGO_SETTINGS_MODULE = squirll.settings.development
python_files = tests.py test_*.py *_tests.py
python_classes = Test*
python_functions = test_*
addopts = --reuse-db --tb=short
```

### System Health Testing

#### Health Check Validation
```bash
# Test all system components
python manage.py system_health_check

# Test specific components
python manage.py system_health_check --component redis
python manage.py system_health_check --component azure

# Production readiness validation
python manage.py deployment_readiness --environment production
```

#### Integration Testing
- **26 System Components**: Database, Redis, Azure services, APIs, WebSocket
- **Security Validation**: All production security settings verified
- **Performance Monitoring**: Connection timeouts, response times
- **Error Handling**: Comprehensive error reporting and recommendations

---

## Common Development Patterns

### Serializer Patterns

#### Create Serializer with Nested Objects
```python
class ReceiptCreateSerializer(serializers.ModelSerializer):
    items = ItemSerializer(many=True)
    
    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        receipt = Receipt.objects.create(**validated_data)
        
        for item_data in items_data:
            Item.objects.create(receipt=receipt, **item_data)
        
        return receipt
```

#### List vs Detail Serializers
```python
class ReceiptListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    class Meta:
        model = Receipt
        fields = ["id", "company", "total", "date", "receipt_type"]

class ReceiptSerializer(serializers.ModelSerializer):
    """Complete serializer for detail views."""
    items = ItemSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    
    class Meta:
        model = Receipt
        fields = "__all__"
```

### Filter Patterns

#### Custom Filter Methods
```python
class ReceiptFilter(django_filters.FilterSet):
    date_period = django_filters.CharFilter(method="filter_period")
    
    def filter_period(self, qs, name, value):
        """Filter by predefined periods (7d, 30d, 3m)."""
        mapping = {"7d": 7, "30d": 30, "3m": 90}
        days = mapping.get(value)
        if days:
            return qs.filter(created_at__gte=timezone.now() - timedelta(days=days))
        return qs
```

### Signal Patterns

#### Usage Tracking
```python
@receiver(receipt_uploaded)
def handle_receipt_uploaded(sender, user, receipt_id, **kwargs):
    """Update usage statistics when receipt is uploaded."""
    today = timezone.now().date()
    with transaction.atomic():
        usage_record, _ = UsageTracker.objects.select_for_update().get_or_create(
            user=user,
            usage_type=UsageTracker.RECEIPT_UPLOAD,
            date=today
        )
        usage_record.count = F('count') + 1
        usage_record.save()
```

### Error Handling Patterns

#### Service Layer Exceptions
```python
class PhoneAuthError(Exception):
    """Base class for phone auth errors."""
    pass

class OTPGenerationError(PhoneAuthError):
    """Error during OTP generation or sending."""
    pass

class InvalidOTPError(PhoneAuthError):
    """Invalid OTP provided."""
    pass
```

#### API Error Responses
```python
try:
    result = some_service_call()
    return Response({"status": "success", "data": result})
except ServiceError as e:
    logger.error(f"Service error: {str(e)}")
    return Response(
        {"error": str(e)},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
```

---

## Performance & Optimization

### Database Optimization

#### Strategic Indexing
```python
class Meta:
    indexes = [
        # Main list view (user's receipts by date)
        models.Index(fields=['user', '-created_at']),
        # Company grouping with dates
        models.Index(fields=['user', 'company', '-created_at']),
        # Receipt type filtering
        models.Index(fields=['user', 'receipt_type', '-created_at']),
    ]
```

#### Query Optimization
```python
def get_queryset(self):
    return Receipt.objects.filter(user=self.request.user)\
                         .select_related('user')\
                         .prefetch_related(
                             Prefetch("items", Item.objects.only("id", "description", "total_price")),
                             Prefetch("tags", Tag.objects.only("id", "name"))
                         )
```

### Caching Strategy

#### Redis Configuration
```python
# Production caching
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "rediss://...",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# Development fallback
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
```

### Celery Task Processing

#### Asynchronous Tasks
```python
# squirll/celery.py
app = Celery('squirll')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Task configuration
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes
```

### Image Processing Optimization

#### Image Stitching
```python
def _stitch_images_vertically(files) -> bytes:
    """
    Stitch multiple receipt images vertically for better OCR.
    
    Process:
    1. Open all images with PIL
    2. Calculate total height
    3. Create new image with combined dimensions
    4. Paste images vertically
    5. Return as bytes
    """
```

---

## Security Considerations

### Authentication Security

#### JWT Token Management
```python
# Short-lived access tokens
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
# Rotating refresh tokens
REFRESH_TOKEN_LIFETIME = timedelta(days=7)
ROTATE_REFRESH_TOKENS = True
BLACKLIST_AFTER_ROTATION = True
```

#### Phone Verification Security
```python
# OTP expires after 2 minutes
cache.set(f"phone_otp_for_user_{user.id}", otp_data, timeout=120)

# Rate limiting on sensitive endpoints
@throttle_classes([AnonRateThrottle])
def sensitive_endpoint(request):
    pass
```

### Data Protection

#### User Data Isolation
```python
# All queries filtered by user
def get_queryset(self):
    return Receipt.objects.filter(user=self.request.user)
```

#### Secure File Storage
```python
# Private Azure Blob Storage
def upload_receipt_image(image_data: bytes, content_type: str, *, user_id: int) -> str:
    """Upload to private container with user-specific paths."""
    blob_name = f"user_{user_id}/{uuid.uuid4()}.{ext}"
    # Upload to private container
```

### HTTPS & Security Headers

#### Production Security (Enterprise-Grade)
```python
# HTTPS enforcement
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Security headers (fully implemented)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# HSTS (1 year duration)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Secure cookies
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

#### Security Validation
- **Health Check**: Comprehensive security settings validation
- **Deployment Readiness**: Automated security audit before deployment
- **Environment Validation**: Production security requirements enforcement
- **Redis Security**: SSL/TLS encryption for all Redis connections

---

## Deployment & Infrastructure

### Azure Infrastructure

#### Resource Organization
```
Development: rg-squirll-dev-015
├── app-squirll-services-dev-015 (Backend API)
├── app-squirll-web-dev-015 (Frontend)
├── pg-squirll-dev-015 (PostgreSQL)
├── redis-squirll-dev-015 (Redis Cache)
├── stgsquirlldev015 (Storage Account)
└── ai-squirll-dev-015 (Application Insights)

UAT: rg-squirll-uat-015
├── app-squirll-services-uat-rdy (Backend API)
├── redis-squirll-uat-rdy (Redis Cache)
└── Similar structure...
```

#### Infrastructure as Code
```
.github/infrastructure/
├── bicep/
│   ├── main.bicep                # Main infrastructure template
│   ├── modules/
│   │   ├── app-services.bicep    # App Service Plan and Web Apps
│   │   ├── database.bicep        # PostgreSQL Flexible Server
│   │   ├── redis.bicep           # Redis Cache
│   │   └── storage.bicep         # Storage Account
│   └── environments/
│       ├── develop.bicepparam
│       └── uat.bicepparam
└── scripts/
    └── deploy.sh                 # Deployment script
```

### Environment Variables

#### Required Variables
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/db

# Azure Services
AZURE_STORAGE_ACCOUNT_NAME=storage_account
AZURE_STORAGE_ACCOUNT_KEY=storage_key
DOCUMENT_INTELLIGENCE_ENDPOINT=https://...
DOCUMENT_INTELLIGENCE_KEY=key

# Redis
REDIS_HOST=redis-host
REDIS_PORT=6380
REDIS_PASSWORD=redis_password

# Twilio
TWILIO_ACCOUNT_SID=twilio_sid
TWILIO_ACCOUNT_AUTH_TOKEN=twilio_token
TWILIO_PHONE_NUMBER=+1234567890

# OpenAI
OPENAI_API_KEY=openai_key

# Google OAuth
GOOGLE_OAUTH2_CLIENT_ID=google_client_id
GOOGLE_OAUTH2_CLIENT_SECRET=google_secret
```

### CI/CD Pipeline

#### Azure Pipelines
```yaml
# azure-pipelines.yml
strategy:
  matrix:
    Python38:
      python.version: '3.8'
    Python39:
      python.version: '3.9'
    Python310:
      python.version: '3.10'

steps:
- task: UsePythonVersion@0
  inputs:
    versionSpec: '$(python.version)'
  displayName: 'Use Python $(python.version)'

- script: |
    python -m pip install --upgrade pip
    pip install -r requirements.txt
  displayName: 'Install dependencies'

- script: |
    python manage.py test
  displayName: 'Run tests'
```

---

## Troubleshooting Guide

### Common Issues

#### Redis Connection Issues
```python
# Check Redis configuration
redis_host = os.environ.get("REDIS_HOST")
redis_password = os.environ.get("REDIS_PASSWORD")

# Development fallback
if not redis_host:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
```

#### Database Connection Problems
```python
# Test database connectivity
GET /core/test-db-connection/

# Check environment variables
DATABASE_URL=postgresql://user:pass@host:5432/db
```

#### Azure Service Issues
```python
# Verify Azure credentials
AZURE_STORAGE_ACCOUNT_NAME=...
AZURE_STORAGE_ACCOUNT_KEY=...
DOCUMENT_INTELLIGENCE_ENDPOINT=...
DOCUMENT_INTELLIGENCE_KEY=...
```

### Development Tips

#### Local Development Setup
```bash
# Use development settings
export DJANGO_SETTINGS_MODULE=squirll.settings.development

# Optional Redis (falls back to in-memory)
export REDIS_HOST=localhost
export REDIS_PORT=6379
```

#### Testing Receipts
```python
# Test receipt upload
POST /receipt-mgmt/receipt/upload/image/
Content-Type: multipart/form-data
Files: receipt_images

# Test manual receipt entry
POST /receipt-mgmt/receipt/upload/manual/
{
    "company": "Test Store",
    "total": 100.00,
    "date": "2024-01-15",
    "items": [...]
}
```

### Logging & Monitoring

#### Development Logging
```python
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[{levelname}] {asctime} {name} | {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
```

#### Production Monitoring
```python
# Application Insights integration
OPENCENSUS = {
    'TRACE': {
        'SAMPLER': 'opencensus.trace.samplers.ProbabilitySampler(rate=0.1)',
        'EXPORTER': 'opencensus.ext.azure.trace_exporter.AzureExporter(...)',
    }
}
```

---

## Custom Management Commands

### System Health Check
```bash
# Comprehensive system health check
python manage.py system_health_check
python manage.py system_health_check --verbose
python manage.py system_health_check --component redis
python manage.py system_health_check --environment production
python manage.py system_health_check --timeout 30
```

**Health Check Components:**
- Settings configuration validation
- Database connectivity (PostgreSQL)
- Redis connectivity (cache and channels)
- Azure services (Blob Storage, Document Intelligence, Application Insights)
- OpenAI API connection
- Twilio API connection
- Google OAuth configuration
- Celery worker connectivity
- WebSocket functionality
- Email configuration
- End-to-end integration workflows

### Deployment Readiness Assessment
```bash
# Production deployment readiness check
python manage.py deployment_readiness
python manage.py deployment_readiness --environment production
python manage.py deployment_readiness --export-report
python manage.py deployment_readiness --skip-health-check
```

**Deployment Checks:**
- System health verification
- Environment configuration validation
- Security settings audit
- Production readiness verification
- Performance settings review
- Monitoring setup validation
- Backup and recovery verification
- External dependencies validation
- Deployment checklist generation

### Receipt Categorization
```bash
# Categorize receipt items using AI
python manage.py categorize_items --help
python manage.py categorize_items --receipt-id 123
python manage.py categorize_items --user-email user@example.com --dry-run
python manage.py categorize_items --all
```

---

This comprehensive guide provides Claude Code with detailed understanding of the Squirll project architecture, patterns, and best practices. Use this information to work effectively with the codebase, understanding the relationships between models, the service layer architecture, and the various integration patterns used throughout the application.