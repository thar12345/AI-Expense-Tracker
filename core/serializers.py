from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
import re
from rest_framework.validators import UniqueValidator

UserProfile = get_user_model()  # This will be our 'api.UserProfile'
PHONE_PATTERN = re.compile(r'^\+?\d{7,15}$')

class UserSignupSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
        validators=[UniqueValidator(queryset=UserProfile.objects.all(), message="This email address is already in use.")]
    )
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = UserProfile
        fields = ['email', 'password', 'first_name', 'last_name']

    def create(self, validated_data):
        pwd = validated_data.pop("password")
        user = UserProfile(**validated_data)
        user.username = validated_data["email"]          # keep AbstractUser happy
        user.set_password(pwd)
        user.save()
        return user
    

class SquirllIDSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["squirll_id"]

    def validate_squirll_id(self, value: str):
        value = value.lower()
        # Accept either "alice" or "alice@squirll.com"
        local = value.split("@")[0]
        return f"{local}@squirll.com"

    def update(self, instance, validated_data):
        if instance.squirll_id:
            raise serializers.ValidationError("squirll_id was already set.")
        instance.squirll_id = validated_data["squirll_id"]
        instance.save(update_fields=["squirll_id"])
        return instance


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)


class SetPhoneSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value: str) -> str:
        raw = value.strip()

        # ── 1) Format check ────────────────────────────────────────────────────
        if not PHONE_PATTERN.match(raw):
            raise serializers.ValidationError(
                "Enter a valid phone number like +14165551234."
            )

        # normalise → strip the leading "+"; keep only digits
        normalised = raw.lstrip("+")

        # ── 2) Current user must NOT already have a number ────────────────────
        user = self.context["request"].user
        if user.phone_number:
            raise serializers.ValidationError("You already have a phone number on file.")

        # ── 3) Uniqueness across all users ────────────────────────────────────
        if UserProfile.objects.filter(phone_number=normalised).exists():
            raise serializers.ValidationError("This phone number is already in use.")

        return normalised            # **digits-only**, ready for DB/storage


class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Serializer for requesting password reset via email.
    """
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Serializer for confirming password reset with new password.
    """
    token = serializers.UUIDField()
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        """
        Validate password strength according to Squirll requirements:
        - 8+ characters
        - At least 1 number
        - At least 1 symbol
        """
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        
        if not re.search(r'\d', value):
            raise serializers.ValidationError("Password must contain at least one number.")
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
            raise serializers.ValidationError("Password must contain at least one symbol.")
        
        return value

    def validate(self, attrs):
        """
        Validate that the two password fields match.
        """
        new_password = attrs.get('new_password')
        confirm_password = attrs.get('confirm_password')

        if new_password != confirm_password:
            raise serializers.ValidationError("Password confirmation doesn't match.")

        # Use Django's password validation as well
        try:
            validate_password(new_password)
        except Exception as e:
            raise serializers.ValidationError({"new_password": list(e.messages)})

        return attrs
    