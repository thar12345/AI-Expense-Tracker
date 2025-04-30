# AI Expense Tracker

A full-stack expense tracking platform built with Django REST Framework, featuring OCR-powered receipt scanning, automated expense categorization using AI, and real-time analytics dashboards.

## Features

- **Smart Receipt Scanning** - Upload receipt images and extract data automatically using OCR (OpenAI GPT-4 Vision & Azure Document Intelligence)
- **AI-Powered Categorization** - Automatic expense categorization using GPT-4o-mini across 17 spending categories
- **Email Integration** - Forward receipts via email for automatic processing with SendGrid Inbound Parse
- **Real-time Analytics** - Interactive dashboards with spending breakdowns by category, vendor, and time period
- **Report Generation** - Export expense reports in PDF and CSV formats
- **AI Chatbot** - Natural language queries for expense data with FAISS vector search
- **Gamification** - Achievement system to encourage consistent expense tracking
- **Multi-platform Auth** - OAuth support for Google and Apple, plus phone verification via Twilio

## Tech Stack

**Backend:**
- Python 3.10+
- Django 4.x & Django REST Framework
- PostgreSQL
- Redis (caching & WebSocket channels)
- Celery (async task processing)

**AI & Cloud Services:**
- OpenAI GPT-4 Vision & GPT-4o-mini
- Azure Document Intelligence
- Azure Blob Storage
- Azure Application Insights

**Integrations:**
- SendGrid (email processing)
- Twilio (phone verification)
- Google OAuth 2.0
- Apple Sign-In

## Project Structure

```
├── core/                 # User auth, profiles, utilities
├── receipt_mgmt/         # Receipt processing & OCR engine
├── email_mgmt/           # Email ingestion & classification
├── analytics/            # Reporting & analytics
├── chatbot/              # AI chatbot with vector search
├── gamification/         # Achievement & rewards system
└── management/           # Admin tools & health checks
```

## Quick Start

```bash
# Clone and setup
git clone https://github.com/thar12345/receipt-management-software.git
cd receipt-management-software

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env with your configuration

# Run migrations
python manage.py migrate

# Start development server
python manage.py runserver
```

## API Endpoints

### Authentication
- `POST /core/auth/signup/` - User registration
- `POST /core/auth/login/` - User login
- `POST /core/auth/google/` - Google OAuth
- `POST /core/token/refresh/` - Refresh JWT token

### Receipts
- `POST /receipt-mgmt/receipt/upload/image/` - Upload receipt image
- `GET /receipt-mgmt/receipts/` - List receipts (filtered, paginated)
- `GET /receipt-mgmt/receipts/by-vendor/` - Group by vendor
- `GET /receipt-mgmt/receipts/search/` - Smart search

### Analytics
- `GET /analytics/category-spend/` - Spending by category
- `GET /analytics/weekly-total/` - Weekly totals
- `GET /analytics/report/select-receipts/pdf/<ids>/` - PDF export

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/db

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# OpenAI
OPENAI_API_KEY=your_key

# Azure
AZURE_STORAGE_ACCOUNT_NAME=account
AZURE_STORAGE_ACCOUNT_KEY=key
DOCUMENT_INTELLIGENCE_ENDPOINT=https://...
DOCUMENT_INTELLIGENCE_KEY=key

# Twilio
TWILIO_ACCOUNT_SID=sid
TWILIO_ACCOUNT_AUTH_TOKEN=token
TWILIO_PHONE_NUMBER=+1234567890
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=.

# Run specific app tests
pytest receipt_mgmt/tests/
```

## License

MIT License
