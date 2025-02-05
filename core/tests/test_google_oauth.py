import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture()
def api_client() -> APIClient:
    """Provides an API client for testing"""
    return APIClient()


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """Clear the throttle cache before each test to avoid rate limiting issues"""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# Google OAuth tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_google_login_success(api_client, monkeypatch):
    """Test successful Google OAuth login with new user creation"""
    # Mock the verification function to return valid payload
    def mock_verify(token):
        return {
            "email": "googleuser@example.com",
            "given_name": "Google",
            "family_name": "User",
            "email_verified": True,
            "aud": "test-client-id",
            "iss": "https://accounts.google.com"
        }, None
    
    monkeypatch.setattr("core.views.verify_google_id_token", mock_verify)
    
    response = api_client.post(reverse("google-login"), {
        "id_token": "mock_valid_token"
    }, format="json")
    
    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["new_user"] is True
    
    # Verify user was created in database
    user = User.objects.get(email="googleuser@example.com")
    assert user.first_name == "Google"
    assert user.last_name == "User"
    assert user.username == "googleuser@example.com"
    assert not user.has_usable_password()  # Should have unusable password


@pytest.mark.django_db
def test_google_login_existing_user(api_client, monkeypatch):
    """Test Google OAuth login with existing user"""
    # Create existing user
    existing_user = User.objects.create_user(
        email="existing@example.com",
        username="existing@example.com",
        first_name="Old",
        last_name="Name"
    )
    
    # Mock verification to return existing user's email
    def mock_verify(token):
        return {
            "email": "existing@example.com",
            "given_name": "New",
            "family_name": "UpdatedName",
            "email_verified": True,
            "aud": "test-client-id",
            "iss": "https://accounts.google.com"
        }, None
    
    monkeypatch.setattr("core.views.verify_google_id_token", mock_verify)
    
    response = api_client.post(reverse("google-login"), {
        "id_token": "mock_valid_token"
    }, format="json")
    
    assert response.status_code == 200
    assert response.data["new_user"] is False
    
    # Verify user info was updated
    existing_user.refresh_from_db()
    assert existing_user.first_name == "New"  # Should be updated
    assert existing_user.last_name == "UpdatedName"  # Should be updated


def test_google_login_invalid_token(api_client, monkeypatch):
    """Test Google OAuth with invalid token"""
    def mock_verify(token):
        return None, "Invalid ID token"
    
    monkeypatch.setattr("core.views.verify_google_id_token", mock_verify)
    
    response = api_client.post(reverse("google-login"), {
        "id_token": "invalid_token"
    }, format="json")
    
    assert response.status_code == 401
    assert response.data["detail"] == "Invalid ID token"


def test_google_login_missing_token(api_client):
    """Test Google OAuth without providing id_token"""
    response = api_client.post(reverse("google-login"), {}, format="json")
    
    assert response.status_code == 400
    assert "id_token is required" in response.data["detail"]


def test_google_login_malformed_token(api_client):
    """Test Google OAuth with malformed token data"""
    # Test with non-string token
    response = api_client.post(reverse("google-login"), {
        "id_token": 123  # Not a string
    }, format="json")
    
    assert response.status_code == 400
    assert "Invalid token format" in response.data["detail"]


def test_google_login_verification_error(api_client, monkeypatch):
    """Test Google OAuth when verification service fails"""
    def mock_verify(token):
        return None, "Google account email is not verified"
    
    monkeypatch.setattr("core.views.verify_google_id_token", mock_verify)
    
    response = api_client.post(reverse("google-login"), {
        "id_token": "unverified_email_token"
    }, format="json")
    
    assert response.status_code == 401
    assert "not verified" in response.data["detail"]


def test_google_login_database_error(api_client, monkeypatch):
    """Test Google OAuth when database operations fail"""
    def mock_verify(token):
        return {
            "email": "dbtest@example.com",
            "given_name": "DB",
            "family_name": "Test",
            "email_verified": True,
            "aud": "test-client-id",
            "iss": "https://accounts.google.com"
        }, None
    
    # Mock User.objects.get_or_create to raise an exception
    def mock_get_or_create(*args, **kwargs):
        raise Exception("Database connection failed")
    
    monkeypatch.setattr("core.views.verify_google_id_token", mock_verify)
    monkeypatch.setattr("core.views.User.objects.get_or_create", mock_get_or_create)
    
    response = api_client.post(reverse("google-login"), {
        "id_token": "valid_token"
    }, format="json")
    
    assert response.status_code == 500
    assert "error occurred during authentication" in response.data["detail"]


@pytest.mark.django_db 
def test_google_login_email_case_insensitive(api_client, monkeypatch):
    """Test that email addresses are handled case-insensitively"""
    # Create user with lowercase email
    existing_user = User.objects.create_user(
        email="testuser@example.com",
        username="testuser@example.com",
        first_name="Test",
        last_name="User"
    )
    
    # Mock verification to return uppercase email
    def mock_verify(token):
        return {
            "email": "TESTUSER@EXAMPLE.COM",  # Uppercase
            "given_name": "Test",
            "family_name": "User",
            "email_verified": True,
            "aud": "test-client-id",
            "iss": "https://accounts.google.com"
        }, None
    
    monkeypatch.setattr("core.views.verify_google_id_token", mock_verify)
    
    response = api_client.post(reverse("google-login"), {
        "id_token": "mock_valid_token"
    }, format="json")
    
    assert response.status_code == 200
    assert response.data["new_user"] is False  # Should find existing user
    
    # Should still be only one user in the database
    assert User.objects.filter(email__iexact="testuser@example.com").count() == 1


@pytest.mark.django_db
def test_google_login_subscription_type_default(api_client, monkeypatch):
    """Test that new Google OAuth users get the default FREE subscription"""
    def mock_verify(token):
        return {
            "email": "newuser@example.com",
            "given_name": "New",
            "family_name": "User",
            "email_verified": True,
            "aud": "test-client-id",
            "iss": "https://accounts.google.com"
        }, None
    
    monkeypatch.setattr("core.views.verify_google_id_token", mock_verify)
    
    response = api_client.post(reverse("google-login"), {
        "id_token": "mock_valid_token"
    }, format="json")
    
    assert response.status_code == 200
    
    # Verify user was created with FREE subscription
    user = User.objects.get(email="newuser@example.com")
    assert user.subscription_type == User.FREE
    assert not user.is_premium


def test_google_login_rate_limiting_concept(api_client, monkeypatch):
    """Test that rate limiting configuration exists (conceptual test)"""
    # This is a simplified test that just verifies the throttle class exists
    # and is properly configured, without actually triggering rate limits
    from core.views import OAuthRateThrottle
    from django.conf import settings
    
    # Verify the throttle class exists
    assert OAuthRateThrottle is not None
    assert OAuthRateThrottle.scope == 'oauth'
    
    # Verify the rate is configured in settings
    assert 'oauth' in settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
    assert settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['oauth'] == '10/min' 