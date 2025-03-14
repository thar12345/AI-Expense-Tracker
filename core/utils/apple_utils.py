from typing import Tuple, Optional
import jwt
import requests
from django.conf import settings
import logging
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import json
import time

logger = logging.getLogger(__name__)

# Apple's public key endpoint
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"

# Cache for Apple's public keys
_apple_keys_cache = {}
_apple_keys_cache_time = 0
CACHE_DURATION = 3600  # 1 hour in seconds


def _get_apple_public_keys() -> Optional[dict]:
    """
    Fetch Apple's public keys with caching.
    Returns the keys dict or None if there's an error.
    """
    global _apple_keys_cache, _apple_keys_cache_time
    
    current_time = time.time()
    
    # Check if we have cached keys that are still valid
    if (_apple_keys_cache and 
        current_time - _apple_keys_cache_time < CACHE_DURATION):
        return _apple_keys_cache
    
    try:
        response = requests.get(APPLE_KEYS_URL, timeout=10)
        response.raise_for_status()
        keys_data = response.json()
        
        # Cache the keys
        _apple_keys_cache = keys_data
        _apple_keys_cache_time = current_time
        
        return keys_data
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Apple public keys: {str(e)}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in Apple keys response: {str(e)}")
        return None


def _get_apple_public_key(kid: str) -> Optional[str]:
    """
    Get Apple's public key for the given key ID.
    Returns the public key as a PEM string or None if not found.
    """
    keys_data = _get_apple_public_keys()
    if not keys_data:
        return None
    
    for key_data in keys_data.get("keys", []):
        if key_data.get("kid") == kid:
            try:
                # Convert JWK to PEM format
                from cryptography.hazmat.primitives.asymmetric import rsa
                from cryptography.hazmat.primitives import serialization
                import base64
                
                # Decode the modulus and exponent
                n = int.from_bytes(
                    base64.urlsafe_b64decode(key_data["n"] + "=="), 
                    'big'
                )
                e = int.from_bytes(
                    base64.urlsafe_b64decode(key_data["e"] + "=="), 
                    'big'
                )
                
                # Create RSA public key
                public_key = rsa.RSAPublicNumbers(e, n).public_key()
                
                # Convert to PEM format
                pem = public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                )
                
                return pem.decode('utf-8')
                
            except Exception as e:
                logger.error(f"Failed to convert Apple JWK to PEM: {str(e)}")
                return None
    
    logger.warning(f"Apple public key not found for kid: {kid}")
    return None


def verify_apple_id_token(token: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Verify an Apple ID token and return the payload.
    
    Returns:
        Tuple[Optional[dict], Optional[str]]: (payload, error_message)
        If verification fails, payload is None and error is a user-friendly message.
    """
    try:
        # Decode the token header to get the key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        if not kid:
            logger.warning("Apple ID token missing key ID in header")
            return None, "Invalid token format"
        
        # Get the public key for verification
        public_key = _get_apple_public_key(kid)
        if not public_key:
            logger.warning(f"Could not retrieve Apple public key for kid: {kid}")
            return None, "Unable to verify token"
        
        # Verify the token
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=settings.APPLE_OAUTH_CLIENT_ID,
                issuer="https://appleid.apple.com"
            )
        except jwt.ExpiredSignatureError:
            logger.warning("Apple ID token has expired")
            return None, "Token has expired"
        except jwt.InvalidAudienceError:
            logger.warning("Apple ID token has invalid audience")
            return None, "Invalid token audience"
        except jwt.InvalidIssuerError:
            logger.warning("Apple ID token has invalid issuer")
            return None, "Invalid token issuer"
        except jwt.InvalidTokenError as e:
            logger.warning(f"Apple ID token is invalid: {str(e)}")
            return None, "Invalid token"
        
        # Additional validation checks
        if not payload.get("email"):
            logger.warning("Apple ID token missing email claim")
            return None, "Email not provided by Apple"
        
        # Check if email is verified (Apple emails are always verified)
        if not payload.get("email_verified", True):
            logger.warning("Apple ID token indicates unverified email")
            return None, "Email not verified by Apple"
    
        
        logger.info("Apple ID token verified successfully")
        return payload, None
        
    except Exception as e:
        logger.error(f"Unexpected error verifying Apple ID token: {str(e)}")
        return None, "Authentication service temporarily unavailable" 