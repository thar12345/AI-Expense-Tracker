from django.contrib import admin
from .models import Email

@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = ('subject', 'sender', 'user', 'company', 'category', 'created_at')
    list_filter = ('category', 'company', 'created_at', 'user')
    search_fields = ('subject', 'sender', 'company', 'user__username', 'user__email')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'sender', 'subject', 'company', 'category')
        }),
        ('Content', {
            'fields': ('html', 'text_content')
        }),
        ('Metadata', {
            'fields': ('created_at', 'headers')
        }),
        ('Raw Data', {
            'classes': ('collapse',),
            'fields': ('raw_email', 'attachments')
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
