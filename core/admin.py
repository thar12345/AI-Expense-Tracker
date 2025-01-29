from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import UserProfile, UsageTracker, EmailVerification, PasswordReset

@admin.register(UserProfile)
class UserProfileAdmin(UserAdmin):
    list_display = ('username', 'email', 'squirll_id', 'subscription_type', 'is_email_verified', 'is_staff', 'is_active')
    list_filter = ('subscription_type', 'is_email_verified', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'squirll_id', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'phone_number')}),
        ('Email Verification', {'fields': ('is_email_verified', 'email_verified_at')}),
        ('Squirll Settings', {'fields': ('squirll_id', 'subscription_type')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'squirll_id', 'subscription_type'),
        }),
    )
    
    readonly_fields = ('email_verified_at',)

@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'token', 'created_at', 'expires_at', 'is_used', 'is_expired')
    list_filter = ('is_used', 'created_at', 'expires_at')
    search_fields = ('user__username', 'user__email', 'token')
    readonly_fields = ('token', 'created_at', 'expires_at', 'is_expired')
    ordering = ('-created_at',)
    
    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = 'Expired'

@admin.register(UsageTracker)
class UsageTrackerAdmin(admin.ModelAdmin):
    list_display = ('user', 'usage_type', 'date', 'count')
    list_filter = ('usage_type', 'date')
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'date'
    ordering = ('-date', 'user')

@admin.register(PasswordReset)
class PasswordResetAdmin(admin.ModelAdmin):
    list_display = ('user', 'token', 'created_at', 'expires_at', 'is_used', 'is_expired')
    list_filter = ('is_used', 'created_at', 'expires_at')
    search_fields = ('user__email', 'user__username', 'token')
    readonly_fields = ('token', 'created_at', 'expires_at', 'is_expired')
    ordering = ('-created_at',)

    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = 'Expired'
