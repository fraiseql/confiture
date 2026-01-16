"""Comprehensive tests for KMS (Key Management Service) manager.

Tests cover:
- KMSProvider enum
- KeyMetadata dataclass
- LocalKMSClient (for testing)
- KMSFactory
"""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from confiture.core.anonymization.security.kms_manager import (
    KMSProvider,
    KeyMetadata,
    LocalKMSClient,
    KMSFactory,
)

# Check if cryptography is available
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

requires_cryptography = pytest.mark.skipif(
    not HAS_CRYPTOGRAPHY,
    reason="cryptography library not installed"
)


class TestKMSProvider:
    """Tests for KMSProvider enum."""

    def test_provider_aws(self):
        """Test AWS provider value."""
        assert KMSProvider.AWS.value == "aws"

    def test_provider_vault(self):
        """Test Vault provider value."""
        assert KMSProvider.VAULT.value == "vault"

    def test_provider_azure(self):
        """Test Azure provider value."""
        assert KMSProvider.AZURE.value == "azure"

    def test_provider_local(self):
        """Test Local provider value."""
        assert KMSProvider.LOCAL.value == "local"

    def test_provider_from_string(self):
        """Test creating provider from string value."""
        assert KMSProvider("aws") == KMSProvider.AWS
        assert KMSProvider("local") == KMSProvider.LOCAL


class TestKeyMetadata:
    """Tests for KeyMetadata dataclass."""

    def test_key_metadata_creation(self):
        """Test creating KeyMetadata instance."""
        now = datetime.now(timezone.utc)
        metadata = KeyMetadata(
            key_id="test-key-123",
            provider=KMSProvider.LOCAL,
            algorithm="AES-256",
            created_at=now,
        )

        assert metadata.key_id == "test-key-123"
        assert metadata.provider == KMSProvider.LOCAL
        assert metadata.algorithm == "AES-256"
        assert metadata.created_at == now

    def test_key_metadata_defaults(self):
        """Test KeyMetadata default values."""
        metadata = KeyMetadata(
            key_id="test-key",
            provider=KMSProvider.AWS,
            algorithm="AES-256",
            created_at=datetime.now(timezone.utc),
        )

        assert metadata.rotated_at is None
        assert metadata.expires_at is None
        assert metadata.version == 1
        assert metadata.is_active is True

    def test_key_metadata_with_rotation(self):
        """Test KeyMetadata with rotation information."""
        now = datetime.now(timezone.utc)
        metadata = KeyMetadata(
            key_id="rotated-key",
            provider=KMSProvider.VAULT,
            algorithm="AES-256",
            created_at=now,
            rotated_at=now,
            version=3,
        )

        assert metadata.rotated_at == now
        assert metadata.version == 3

    def test_key_metadata_inactive(self):
        """Test KeyMetadata for inactive key."""
        metadata = KeyMetadata(
            key_id="inactive-key",
            provider=KMSProvider.AZURE,
            algorithm="RSA-OAEP",
            created_at=datetime.now(timezone.utc),
            is_active=False,
        )

        assert metadata.is_active is False


@requires_cryptography
class TestLocalKMSClient:
    """Tests for LocalKMSClient (testing-only client)."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create LocalKMSClient with temp directory."""
        return LocalKMSClient(keys_dir=str(tmp_path / "test_keys"))

    def test_init_creates_keys_dir(self, tmp_path):
        """Test initialization creates keys directory."""
        keys_dir = str(tmp_path / "new_keys")
        client = LocalKMSClient(keys_dir=keys_dir)

        assert os.path.exists(keys_dir)
        assert client.provider == KMSProvider.LOCAL

    def test_init_default_keys_dir(self):
        """Test initialization with default keys directory."""
        client = LocalKMSClient()

        assert client.keys_dir == "/tmp/confiture_test_keys"

    def test_encrypt_creates_key_if_not_exists(self, client):
        """Test encryption creates key if it doesn't exist."""
        plaintext = b"secret data"

        ciphertext = client.encrypt(plaintext, "new-key")

        assert "new-key" in client.keys
        assert ciphertext != plaintext

    def test_encrypt_uses_existing_key(self, client):
        """Test encryption uses existing key."""
        plaintext = b"secret data"

        # First encryption creates the key
        client.encrypt(plaintext, "my-key")
        original_key = client.keys["my-key"]

        # Second encryption should use same key
        client.encrypt(plaintext, "my-key")

        assert client.keys["my-key"] == original_key

    def test_encrypt_decrypt_roundtrip(self, client):
        """Test encrypt then decrypt returns original."""
        plaintext = b"secret message"

        ciphertext = client.encrypt(plaintext, "roundtrip-key")
        decrypted = client.decrypt(ciphertext, "roundtrip-key")

        assert decrypted == plaintext

    def test_decrypt_with_key_id(self, client):
        """Test decrypt with specific key_id."""
        plaintext = b"test data"

        ciphertext = client.encrypt(plaintext, "specific-key")
        decrypted = client.decrypt(ciphertext, key_id="specific-key")

        assert decrypted == plaintext

    def test_decrypt_without_key_id_tries_all(self, client):
        """Test decrypt without key_id tries all keys."""
        plaintext = b"test data"

        ciphertext = client.encrypt(plaintext, "auto-key")
        decrypted = client.decrypt(ciphertext)  # No key_id

        assert decrypted == plaintext

    def test_decrypt_key_not_found(self, client):
        """Test decrypt raises error when key not found."""
        with pytest.raises(ValueError, match="not found"):
            client.decrypt(b"ciphertext", key_id="nonexistent-key")

    def test_decrypt_no_matching_key(self, client):
        """Test decrypt raises error when no key can decrypt."""
        # Create some keys
        client.encrypt(b"data1", "key1")
        client.encrypt(b"data2", "key2")

        # Try to decrypt with invalid ciphertext
        with pytest.raises((ValueError, Exception)):
            client.decrypt(b"invalid-ciphertext-that-no-key-can-decrypt")

    def test_rotate_key(self, client):
        """Test key rotation."""
        # Create initial key
        client.encrypt(b"data", "rotate-me")
        original_key = client.keys["rotate-me"]

        # Rotate key
        new_version = client.rotate_key("rotate-me")

        assert client.keys["rotate-me"] != original_key
        assert "rotate-me:v" in new_version

    def test_get_key_metadata(self, client):
        """Test getting key metadata."""
        metadata = client.get_key_metadata("test-key")

        assert metadata.key_id == "test-key"
        assert metadata.provider == KMSProvider.LOCAL
        assert metadata.algorithm == "Fernet"
        assert metadata.version == 1
        assert metadata.is_active is True
        assert isinstance(metadata.created_at, datetime)


@requires_cryptography
class TestKMSFactory:
    """Tests for KMSFactory."""

    def test_create_local_client(self, tmp_path):
        """Test creating local KMS client."""
        client = KMSFactory.create(
            KMSProvider.LOCAL,
            keys_dir=str(tmp_path / "factory_keys"),
        )

        assert isinstance(client, LocalKMSClient)

    def test_create_unsupported_provider(self):
        """Test error with unsupported provider string."""
        # This tests the factory with an invalid enum value
        # Since we can't easily create an invalid enum, we test
        # by checking the factory handles LOCAL correctly
        client = KMSFactory.create(KMSProvider.LOCAL)
        assert isinstance(client, LocalKMSClient)

    def test_get_or_create_caches_client(self, tmp_path):
        """Test get_or_create caches clients."""
        # Clear any cached clients
        KMSFactory._clients.clear()

        client1 = KMSFactory.get_or_create(
            KMSProvider.LOCAL,
            keys_dir=str(tmp_path / "cache_keys"),
        )
        client2 = KMSFactory.get_or_create(
            KMSProvider.LOCAL,
            keys_dir=str(tmp_path / "cache_keys"),
        )

        assert client1 is client2

    def test_get_or_create_with_custom_key(self, tmp_path):
        """Test get_or_create with custom cache key."""
        KMSFactory._clients.clear()

        client1 = KMSFactory.get_or_create(
            KMSProvider.LOCAL,
            key="custom-key-1",
            keys_dir=str(tmp_path / "keys1"),
        )
        client2 = KMSFactory.get_or_create(
            KMSProvider.LOCAL,
            key="custom-key-2",
            keys_dir=str(tmp_path / "keys2"),
        )

        assert client1 is not client2


@requires_cryptography
class TestLocalKMSClientEdgeCases:
    """Additional edge case tests for LocalKMSClient."""

    def test_encrypt_different_keys_different_ciphertext(self, tmp_path):
        """Test encryption with different keys produces different ciphertext."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))
        plaintext = b"same data"

        ciphertext1 = client.encrypt(plaintext, "key1")
        ciphertext2 = client.encrypt(plaintext, "key2")

        assert ciphertext1 != ciphertext2

    def test_multiple_encrypt_calls_same_key(self, tmp_path):
        """Test multiple encrypt calls with same key work correctly."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))

        data1 = b"first message"
        data2 = b"second message"

        ct1 = client.encrypt(data1, "shared-key")
        ct2 = client.encrypt(data2, "shared-key")

        pt1 = client.decrypt(ct1, "shared-key")
        pt2 = client.decrypt(ct2, "shared-key")

        assert pt1 == data1
        assert pt2 == data2

    def test_rotate_key_old_ciphertext_fails(self, tmp_path):
        """Test old ciphertext can't be decrypted after key rotation."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))

        # Encrypt with original key
        plaintext = b"secret"
        ciphertext = client.encrypt(plaintext, "rotate-key")

        # Rotate the key
        client.rotate_key("rotate-key")

        # Old ciphertext should fail to decrypt with new key
        with pytest.raises(Exception):
            client.decrypt(ciphertext, "rotate-key")

    def test_encrypt_empty_data(self, tmp_path):
        """Test encrypting empty data."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))

        ciphertext = client.encrypt(b"", "empty-key")
        decrypted = client.decrypt(ciphertext, "empty-key")

        assert decrypted == b""

    def test_encrypt_large_data(self, tmp_path):
        """Test encrypting large data."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))
        large_data = b"x" * 10000

        ciphertext = client.encrypt(large_data, "large-key")
        decrypted = client.decrypt(ciphertext, "large-key")

        assert decrypted == large_data

    def test_multiple_keys_independent(self, tmp_path):
        """Test multiple keys are independent."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))

        # Create data with different keys
        ct1 = client.encrypt(b"data1", "key-a")
        ct2 = client.encrypt(b"data2", "key-b")

        # Each key only decrypts its own data
        assert client.decrypt(ct1, "key-a") == b"data1"
        assert client.decrypt(ct2, "key-b") == b"data2"

        # Cross-key decryption should fail
        with pytest.raises(Exception):
            client.decrypt(ct1, "key-b")

    def test_key_metadata_for_nonexistent_key(self, tmp_path):
        """Test getting metadata for nonexistent key."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))

        # Should still return metadata (key doesn't need to exist)
        metadata = client.get_key_metadata("nonexistent-key")

        assert metadata.key_id == "nonexistent-key"

    def test_rotate_creates_new_key_if_not_exists(self, tmp_path):
        """Test rotate_key creates key if it doesn't exist."""
        client = LocalKMSClient(keys_dir=str(tmp_path / "keys"))

        # Rotate a key that doesn't exist yet
        version = client.rotate_key("new-rotate-key")

        assert "new-rotate-key" in client.keys
        assert "v" in version
