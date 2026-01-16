"""Real-world anonymization scenarios.

Provides ready-to-use anonymization profiles for common business domains:
- E-commerce: Customer data, orders, payments
- Healthcare: HIPAA-compliant PHI anonymization
- Financial: Loan applications, credit data
- SaaS: User accounts, subscription data
- Multi-tenant: Data isolation with deterministic seeding

Each scenario includes:
- Pre-configured strategy profiles
- Batch anonymization support
- Domain-specific validation
- Usage examples

Usage:
    >>> from confiture.scenarios import ECommerceScenario
    >>> data = {"first_name": "John", "email": "john@example.com"}
    >>> anonymized = ECommerceScenario.anonymize(data)
"""

# Import strategies to ensure registration (must come before scenario imports)
import confiture.core.anonymization.strategies  # noqa: F401
from confiture.scenarios.ecommerce import ECommerceScenario
from confiture.scenarios.financial import FinancialScenario
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.multi_tenant import MultiTenantScenario
from confiture.scenarios.saas import SaaSScenario

__all__ = [
    "ECommerceScenario",
    "HealthcareScenario",
    "FinancialScenario",
    "SaaSScenario",
    "MultiTenantScenario",
]
