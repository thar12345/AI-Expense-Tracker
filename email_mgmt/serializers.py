from rest_framework import serializers
from .models import Email

class EmailSerializer(serializers.ModelSerializer):
    """
    Main serializer for Email model that handles both creation and detailed representation.
    
    This serializer includes all fields necessary for storing a complete email record,
    including the raw email content, headers, and attachments. It's used primarily
    by the email ingestion endpoint that receives data from SendGrid.
    
    Fields:
        - All basic email fields (sender, subject, html)
        - Full MIME content (raw_email, headers)
        - Attachment data
        - Metadata (company, category, created_at)
    """
    class Meta:
        model = Email
        fields = [
            'id',
            'sender',
            'subject',
            'html',
            'text_content',
            'raw_email',
            'headers',
            'attachments',
            'company',
            'category',
            'created_at',
        ]
        read_only_fields = ['created_at', 'id']

class EmailListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for list views and email previews.
    
    This serializer includes only the essential fields needed for displaying
    emails in lists or preview cards. It intentionally omits heavy fields
    like raw_email and html content to reduce payload size.
    
    Used by:
        - EmailListView
        - EmailByCompanyView (for preview lists)
    """
    class Meta:
        model = Email
        fields = ["id", "subject", "category", "company", "created_at"]

class EmailDetailSerializer(serializers.ModelSerializer):
    """
    Complete serializer that exposes all Email model fields.
    
    Used for detailed single-email views where the full email content,
    including raw data and attachments, needs to be available.
    """
    class Meta:
        model = Email
        fields = "__all__"
        