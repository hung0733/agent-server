# pyright: reportMissingImports=false
"""
Cryptographic utilities for secure data storage.

This module provides Fernet-based encryption/decryption utilities
for securely storing sensitive data like API keys in the database.
"""
from __future__ import annotations

import os
import base64
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionKeyError(Exception):
    """Exception raised when encryption key is missing or invalid."""
    pass


class DecryptionError(Exception):
    """Exception raised when decryption fails."""
    pass


def get_encryption_key() -> bytes:
    """Get the encryption key from environment variable.
    
    The encryption key should be a base64-encoded Fernet key.
    If not set, raises EncryptionKeyError.
    
    To generate a new key:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        print(key.decode())  # Store this in LLM_ENCRYPTION_KEY env var
    
    Returns:
        The encryption key as bytes.
        
    Raises:
        EncryptionKeyError: If LLM_ENCRYPTION_KEY environment variable is not set.
    """
    key = os.getenv("LLM_ENCRYPTION_KEY")
    if key is None:
        raise EncryptionKeyError(
            "LLM_ENCRYPTION_KEY environment variable is not set. "
            "Please set it to a valid Fernet key. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return key.encode() if isinstance(key, str) else key


def derive_key_from_password(password: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from a password.
    
    This uses PBKDF2 with SHA256 to derive a key suitable for Fernet.
    
    Args:
        password: The password to derive the key from.
        salt: A random salt (should be at least 16 bytes).
        
    Returns:
        A base64-encoded key suitable for Fernet.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key


class CryptoManager:
    """Manager for encryption/decryption operations using Fernet.
    
    This class provides a simple interface for encrypting and decrypting
    sensitive data like API keys. It uses Fernet (AES-128 in CBC mode with
    PKCS7 padding and HMAC authentication) for secure symmetric encryption.
    
    Example:
        crypto = CryptoManager()
        encrypted = crypto.encrypt("my-api-key")
        decrypted = crypto.decrypt(encrypted)
    """
    
    _instance: Optional["CryptoManager"] = None
    _fernet: Optional[Fernet] = None
    
    def __new__(cls) -> "CryptoManager":
        """Singleton pattern to avoid re-initializing Fernet."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize the CryptoManager with the encryption key."""
        if self._fernet is None:
            key = get_encryption_key()
            self._fernet = Fernet(key)
    
    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance.
        
        This is primarily useful for testing with different keys.
        """
        cls._instance = None
        cls._fernet = None
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string value.
        
        Args:
            plaintext: The string to encrypt.
            
        Returns:
            The encrypted value as a base64-encoded string.
            
        Raises:
            EncryptionKeyError: If encryption key is not configured.
        """
        if self._fernet is None:
            raise EncryptionKeyError("Encryption key not initialized")
        
        encrypted = self._fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted string value.
        
        Args:
            ciphertext: The encrypted value as a base64-encoded string.
            
        Returns:
            The decrypted plaintext string.
            
        Raises:
            DecryptionError: If decryption fails (wrong key or corrupted data).
        """
        if self._fernet is None:
            raise EncryptionKeyError("Encryption key not initialized")
        
        try:
            decrypted = self._fernet.decrypt(ciphertext.encode())
            return decrypted.decode()
        except InvalidToken as e:
            raise DecryptionError(
                "Failed to decrypt value. This may indicate the encryption key "
                "has changed or the data is corrupted."
            ) from e


def encrypt_api_key(api_key: str) -> str:
    """Convenience function to encrypt an API key.
    
    Args:
        api_key: The plain text API key to encrypt.
        
    Returns:
        The encrypted API key as a base64-encoded string.
    """
    return CryptoManager().encrypt(api_key)


def decrypt_api_key(encrypted_key: str) -> str:
    """Convenience function to decrypt an API key.
    
    Args:
        encrypted_key: The encrypted API key as a base64-encoded string.
        
    Returns:
        The decrypted plain text API key.
    """
    return CryptoManager().decrypt(encrypted_key)


def generate_key() -> str:
    """Generate a new Fernet encryption key.
    
    This is a utility function for generating a new encryption key
    that should be stored securely in the LLM_ENCRYPTION_KEY environment
    variable.
    
    Returns:
        A new Fernet key as a base64-encoded string.
    """
    return Fernet.generate_key().decode()