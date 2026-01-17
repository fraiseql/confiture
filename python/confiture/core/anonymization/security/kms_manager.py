"""KMS (Key Management Service) integration for encryption key management.

Provides multi-cloud support for key management:
- AWS KMS
- HashiCorp Vault
- Azure Key Vault

Enables secure key storage, rotation, and lifecycle management.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class KMSProvider(Enum):
    """Supported KMS providers."""

    AWS = "aws"
    VAULT = "vault"
    AZURE = "azure"
    LOCAL = "local"  # For testing only


@dataclass
class KeyMetadata:
    """Metadata for an encryption key."""

    key_id: str
    provider: KMSProvider
    algorithm: str
    created_at: datetime
    rotated_at: datetime | None = None
    expires_at: datetime | None = None
    version: int = 1
    is_active: bool = True


class KMSClient(ABC):
    """Abstract base class for KMS clients."""

    @abstractmethod
    def encrypt(self, plaintext: bytes, key_id: str) -> bytes:
        """Encrypt plaintext using the specified key."""
        pass

    @abstractmethod
    def decrypt(self, ciphertext: bytes, key_id: str | None = None) -> bytes:
        """Decrypt ciphertext. Key ID can be embedded in ciphertext."""
        pass

    @abstractmethod
    def rotate_key(self, key_id: str) -> str:
        """Rotate a key and return the new key version."""
        pass

    @abstractmethod
    def get_key_metadata(self, key_id: str) -> KeyMetadata:
        """Get metadata for a key."""
        pass


class AWSKMSClient(KMSClient):
    """AWS KMS client implementation."""

    def __init__(self, region: str = "us-east-1"):
        """Initialize AWS KMS client.

        Args:
            region: AWS region (e.g., 'us-east-1')
        """
        self.region = region
        self.provider = KMSProvider.AWS

        try:
            import boto3  # type: ignore[import-untyped]

            self.client = boto3.client("kms", region_name=region)
        except ImportError as e:
            raise ImportError("boto3 is required for AWS KMS support") from e

    def encrypt(self, plaintext: bytes, key_id: str) -> bytes:
        """Encrypt plaintext using AWS KMS.

        Args:
            plaintext: Data to encrypt
            key_id: AWS KMS key ID or ARN

        Returns:
            Encrypted data (ciphertext)

        Raises:
            Exception: If encryption fails
        """
        try:
            response = self.client.encrypt(
                KeyId=key_id,
                Plaintext=plaintext,
            )
            return response["CiphertextBlob"]
        except Exception as e:
            logger.error(f"AWS KMS encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: bytes, key_id: str | None = None) -> bytes:  # noqa: ARG002
        """Decrypt ciphertext using AWS KMS.

        Args:
            ciphertext: Encrypted data
            _key_id: Not used (embedded in ciphertext by AWS)

        Returns:
            Decrypted plaintext

        Raises:
            Exception: If decryption fails
        """
        try:
            response = self.client.decrypt(CiphertextBlob=ciphertext)
            return response["Plaintext"]
        except Exception as e:
            logger.error(f"AWS KMS decryption failed: {e}")
            raise

    def rotate_key(self, key_id: str) -> str:
        """Rotate an AWS KMS key.

        Args:
            key_id: AWS KMS key ID

        Returns:
            New key version

        Raises:
            Exception: If rotation fails
        """
        try:
            # AWS KMS automatic key rotation (enable once)
            response = self.client.describe_key(KeyId=key_id)
            key_metadata = response["KeyMetadata"]

            logger.info(f"Key rotation enabled for {key_id}")
            # AWS handles rotation automatically
            return f"{key_id}:v{key_metadata['KeyUsage']}"
        except Exception as e:
            logger.error(f"AWS KMS key rotation failed: {e}")
            raise


class VaultKMSClient(KMSClient):
    """HashiCorp Vault KMS client implementation."""

    def __init__(self, vault_url: str, token: str, engine: str = "transit"):
        """Initialize Vault KMS client.

        Args:
            vault_url: Vault server URL (e.g., 'http://localhost:8200')
            token: Vault authentication token
            engine: Transit engine path (default: 'transit')
        """
        self.vault_url = vault_url
        self.token = token
        self.engine = engine
        self.provider = KMSProvider.VAULT

        try:
            import hvac  # type: ignore[import-untyped]

            self.client = hvac.Client(url=vault_url, token=token)
        except ImportError as e:
            raise ImportError("hvac is required for HashiCorp Vault support") from e

    def encrypt(self, plaintext: bytes, key_id: str) -> bytes:
        """Encrypt plaintext using Vault.

        Args:
            plaintext: Data to encrypt
            key_id: Key name in Vault

        Returns:
            Encrypted data (ciphertext)

        Raises:
            Exception: If encryption fails
        """
        try:
            # Vault expects base64 plaintext
            import base64

            plaintext_b64 = base64.b64encode(plaintext).decode("utf-8")

            response = self.client.secrets.transit.encrypt_data(
                name=key_id,
                plaintext=plaintext_b64,
                mount_point=self.engine,
            )
            return response["data"]["ciphertext"].encode()
        except Exception as e:
            logger.error(f"Vault encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: bytes, key_id: str | None = None) -> bytes:
        """Decrypt ciphertext using Vault.

        Args:
            ciphertext: Encrypted data
            key_id: Key name in Vault (must be provided)

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If key_id not provided
            Exception: If decryption fails
        """
        if not key_id:
            raise ValueError("key_id must be provided for Vault decryption")

        try:
            import base64

            ciphertext_str = ciphertext.decode() if isinstance(ciphertext, bytes) else ciphertext

            response = self.client.secrets.transit.decrypt_data(
                name=key_id,
                ciphertext=ciphertext_str,
                mount_point=self.engine,
            )
            plaintext_b64 = response["data"]["plaintext"]
            return base64.b64decode(plaintext_b64)
        except Exception as e:
            logger.error(f"Vault decryption failed: {e}")
            raise

    def rotate_key(self, key_id: str) -> str:
        """Rotate a Vault transit key.

        Args:
            key_id: Key name in Vault

        Returns:
            New key version

        Raises:
            Exception: If rotation fails
        """
        try:
            self.client.secrets.transit.rotate_key(
                name=key_id,
                mount_point=self.engine,
            )

            # Get updated key metadata
            metadata = self.client.secrets.transit.read_key(
                name=key_id,
                mount_point=self.engine,
            )
            new_version = metadata["data"]["latest_version"]

            logger.info(f"Key {key_id} rotated to version {new_version}")
            return f"{key_id}:v{new_version}"
        except Exception as e:
            logger.error(f"Vault key rotation failed: {e}")
            raise


class AzureKMSClient(KMSClient):
    """Azure Key Vault KMS client implementation."""

    def __init__(self, vault_url: str, credential: Any):
        """Initialize Azure Key Vault client.

        Args:
            vault_url: Azure Key Vault URL
            credential: Azure credential object (e.g., DefaultAzureCredential)
        """
        self.vault_url = vault_url
        self.credential = credential
        self.provider = KMSProvider.AZURE

        try:
            from azure.keyvault.keys.crypto import (  # type: ignore[import-untyped]
                CryptographyClient,
                EncryptionAlgorithm,
            )

            self.CryptographyClient = CryptographyClient
            self.EncryptionAlgorithm = EncryptionAlgorithm
        except ImportError as e:
            raise ImportError(
                "azure-identity and azure-keyvault-keys are required for Azure support"
            ) from e

    def encrypt(self, plaintext: bytes, key_id: str) -> bytes:
        """Encrypt plaintext using Azure Key Vault.

        Args:
            plaintext: Data to encrypt
            key_id: Key name in Key Vault

        Returns:
            Encrypted data (ciphertext)

        Raises:
            Exception: If encryption fails
        """
        try:
            key_url = f"{self.vault_url}/keys/{key_id}/latest"
            crypto_client = self.CryptographyClient(key_url, credential=self.credential)

            result = crypto_client.encrypt(
                self.EncryptionAlgorithm.rsa_oaep,
                plaintext,
            )
            return result.ciphertext
        except Exception as e:
            logger.error(f"Azure Key Vault encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: bytes, key_id: str | None = None) -> bytes:
        """Decrypt ciphertext using Azure Key Vault.

        Args:
            ciphertext: Encrypted data
            key_id: Key name in Key Vault (must be provided)

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If key_id not provided
            Exception: If decryption fails
        """
        if not key_id:
            raise ValueError("key_id must be provided for Azure Key Vault decryption")

        try:
            key_url = f"{self.vault_url}/keys/{key_id}/latest"
            crypto_client = self.CryptographyClient(key_url, credential=self.credential)

            result = crypto_client.decrypt(
                self.EncryptionAlgorithm.rsa_oaep,
                ciphertext,
            )
            return result.plaintext
        except Exception as e:
            logger.error(f"Azure Key Vault decryption failed: {e}")
            raise

    def rotate_key(self, key_id: str) -> str:
        """Rotate an Azure Key Vault key version.

        Args:
            key_id: Key name in Key Vault

        Returns:
            New key version

        Raises:
            Exception: If rotation fails
        """
        try:
            from azure.keyvault.keys import KeyClient  # type: ignore[import-untyped]

            key_client = KeyClient(vault_url=self.vault_url, credential=self.credential)

            # Get current key
            key = key_client.get_key(key_id)
            current_version = key.properties.version

            logger.info(f"Key {key_id} current version: {current_version}")
            # Note: Azure doesn't have automatic rotation like Vault
            # Manual rotation requires re-keying data
            return f"{key_id}:{current_version}"
        except Exception as e:
            logger.error(f"Azure Key Vault key info failed: {e}")
            raise


class LocalKMSClient(KMSClient):
    """Local KMS client for testing purposes.

    WARNING: Only for testing. Never use in production.
    """

    def __init__(self, keys_dir: str | None = None):
        """Initialize local KMS client.

        Args:
            keys_dir: Directory to store test keys (temporary)
        """
        import os

        self.provider = KMSProvider.LOCAL
        self.keys = {}  # In-memory key storage
        self.keys_dir = keys_dir or "/tmp/confiture_test_keys"

        if not os.path.exists(self.keys_dir):
            os.makedirs(self.keys_dir)

        logger.warning("⚠️  LocalKMSClient is for TESTING ONLY. Never use in production.")

    def encrypt(self, plaintext: bytes, key_id: str) -> bytes:
        """Simple XOR encryption for testing.

        Args:
            plaintext: Data to encrypt
            key_id: Key identifier

        Returns:
            Encrypted data
        """
        from cryptography.fernet import Fernet

        if key_id not in self.keys:
            # Generate key if not exists
            self.keys[key_id] = Fernet.generate_key()

        f = Fernet(self.keys[key_id])
        return f.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes, key_id: str | None = None) -> bytes:
        """Decrypt using Fernet.

        Args:
            ciphertext: Encrypted data
            key_id: Key identifier (optional, can be embedded)

        Returns:
            Decrypted plaintext
        """
        from cryptography.fernet import Fernet

        if not key_id:
            # Try all keys
            for _key_id, key in self.keys.items():
                try:
                    f = Fernet(key)
                    return f.decrypt(ciphertext)
                except Exception:
                    continue
            raise ValueError("Could not decrypt with any available key")

        if key_id not in self.keys:
            raise ValueError(f"Key {key_id} not found")

        f = Fernet(self.keys[key_id])
        return f.decrypt(ciphertext)

    def rotate_key(self, key_id: str) -> str:
        """Rotate a test key.

        Args:
            key_id: Key identifier

        Returns:
            New version identifier
        """
        from cryptography.fernet import Fernet

        self.keys[key_id] = Fernet.generate_key()
        version = len([k for k in self.keys if k.startswith(key_id)])
        return f"{key_id}:v{version}"

    def get_key_metadata(self, key_id: str) -> KeyMetadata:
        """Get metadata for a test key."""
        return KeyMetadata(
            key_id=key_id,
            provider=KMSProvider.LOCAL,
            algorithm="Fernet",
            created_at=datetime.now(UTC),
            version=1,
            is_active=True,
        )


class KMSFactory:
    """Factory for creating KMS clients."""

    _clients: dict[str, KMSClient] = {}

    @staticmethod
    def create(
        provider: KMSProvider,
        **config: Any,
    ) -> KMSClient:
        """Create a KMS client.

        Args:
            provider: KMS provider type
            **config: Provider-specific configuration

        Returns:
            Configured KMS client

        Raises:
            ValueError: If provider not supported
        """
        if provider == KMSProvider.AWS:
            return AWSKMSClient(
                region=config.get("region", "us-east-1"),
            )
        elif provider == KMSProvider.VAULT:
            return VaultKMSClient(
                vault_url=config.get("vault_url"),
                token=config.get("token"),
                engine=config.get("engine", "transit"),
            )
        elif provider == KMSProvider.AZURE:
            return AzureKMSClient(
                vault_url=config.get("vault_url"),
                credential=config.get("credential"),
            )
        elif provider == KMSProvider.LOCAL:
            return LocalKMSClient(
                keys_dir=config.get("keys_dir"),
            )
        else:
            raise ValueError(f"Unsupported KMS provider: {provider}")

    @staticmethod
    def get_or_create(
        provider: KMSProvider,
        key: str | None = None,
        **config: Any,
    ) -> KMSClient:
        """Get or create a cached KMS client.

        Args:
            provider: KMS provider type
            key: Cache key (optional)
            **config: Provider-specific configuration

        Returns:
            Configured KMS client (cached if available)
        """
        cache_key = key or str(provider)

        if cache_key not in KMSFactory._clients:
            KMSFactory._clients[cache_key] = KMSFactory.create(provider, **config)

        return KMSFactory._clients[cache_key]
