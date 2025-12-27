"""SaaS (Software-as-a-Service) user data anonymization scenario.

Real-world use case: Anonymizing user accounts, billing, and usage data for analytics.

Data Types:
- User names (PII)
- Email addresses (PII)
- Phone numbers (PII)
- Organization names (sensitive - may be identifying)
- Billing addresses (PII)
- Payment methods (PCI-DSS)
- IP addresses (tracking/privacy)
- User agents (sensitive)
- Usage metrics (preserve for analytics)
- Subscription tier (preserve for analysis)
- Account creation date (preserve)
- Last login (sensitive - preserve year/month)
- Feature usage (preserve for product analytics)
- Billing amounts (preserve for financial analysis)

Strategy:
- Names: Firstname/lastname masking
- Email: Email redaction
- Phone: Phone masking
- Organization: Name initials
- Billing address: Address masking
- Credit cards: Last 4 only
- IP addresses: Complete masking
- Timestamps: Preserve year/month
- Usage metrics: Preserve for analytics
- Subscription data: Preserve
"""

from confiture.core.anonymization.factory import StrategyProfile, StrategyFactory


class SaaSScenario:
    """SaaS user data anonymization scenario.

    Demonstrates anonymizing user and account data while preserving product
    analytics and usage metrics.

    Example:
        >>> scenario = SaaSScenario()
        >>> data = {
        ...     "user_id": "USR-789456",
        ...     "user_name": "john.smith",
        ...     "first_name": "John",
        ...     "last_name": "Smith",
        ...     "text_redaction": "john.smith@acmecorp.com",
        ...     "text_redaction": "555-123-4567",
        ...     "organization_name": "Acme Corporation",
        ...     "organization_type": "Enterprise",
        ...     "billing_address": "123 Business Park",
        ...     "billing_city": "San Francisco",
        ...     "billing_state": "CA",
        ...     "billing_country": "US",
        ...     "card_last4": "4242",
        ...     "card_type": "Visa",
        ...     "subscription_tier": "Enterprise",
        ...     "monthly_cost": 999,
        ...     "seats": 50,
        ...     "created_at": "2023-01-15",
        ...     "last_login": "2024-12-15",
        ...     "login_ip": "192.168.1.100",
        ...     "monthly_api_calls": 5000000,
        ...     "storage_gb": 500,
        ...     "features_enabled": ["analytics", "api", "sso"],
        ... }
        >>> anonymized = scenario.anonymize(data)
        >>> # PII masked, usage data preserved
    """

    @staticmethod
    def get_profile() -> StrategyProfile:
        """Get SaaS data anonymization profile.

        Returns:
            StrategyProfile configured for SaaS user and account data.

        Strategy Mapping:
            - user_id: preserve (business identifier)
            - user_name: email or hash (username anonymization)
            - first_name: firstname masking
            - last_name: lastname masking
            - email: email redaction
            - phone: phone masking
            - organization_name: name initials
            - billing_address: address masking
            - billing_city: preserve (location for reporting)
            - billing_state: preserve
            - billing_country: preserve
            - card: credit card (last 4)
            - subscription_tier: preserve (business data)
            - monthly_cost: preserve (financial data)
            - seats: preserve (business metric)
            - created_at: preserve (business metric)
            - last_login: date masking (preserve year/month)
            - login_ip: IP masking
            - api_calls: preserve (usage metric)
            - storage: preserve (usage metric)
            - features: preserve (product data)
        """
        return StrategyProfile(
            name="saas_users",
            seed=42,  # Fixed seed for reproducibility
            columns={
                # User identifiers - preserve
                "user_id": "preserve",
                "account_id": "preserve",
                "tenant_id": "preserve",
                "organization_id": "preserve",

                # User PII - mask
                "user_name": "text_redaction",
                "username": "text_redaction",
                "handle": "text_redaction",
                "first_name": "name",
                "last_name": "name",
                "full_name": "name",
                "display_name": "name",

                # Contact - redact
                "email": "text_redaction",
                "backup_email": "text_redaction",
                "phone": "text_redaction",
                "phone_number": "text_redaction",
                "mobile": "text_redaction",

                # Organization - mask name
                "organization_name": "name",
                "org_name": "name",
                "company_name": "name",
                "team_name": "name",
                "workspace_name": "name",

                # Organization metadata - preserve
                "organization_type": "preserve",
                "industry": "preserve",
                "company_size": "preserve",
                "organization_role": "preserve",
                "role": "preserve",
                "permission_level": "preserve",

                # Billing address - mask
                "billing_address": "address",
                "billing_street": "address",
                "billing_address2": "address",
                "billing_city": "preserve",
                "billing_state": "preserve",
                "billing_zip": "preserve",
                "billing_country": "preserve",

                # Shipping address - mask
                "shipping_address": "address",
                "shipping_city": "preserve",
                "shipping_state": "preserve",
                "shipping_country": "preserve",

                # Payment - PCI-DSS compliant
                "card_number": "credit_card",
                "card_last4": "preserve",
                "card_type": "preserve",
                "card_brand": "preserve",
                "card_expiry": "preserve",
                "billing_method": "preserve",

                # Subscription/pricing - preserve
                "subscription_id": "preserve",
                "subscription_tier": "preserve",
                "subscription_plan": "preserve",
                "subscription_status": "preserve",
                "monthly_cost": "preserve",
                "annual_cost": "preserve",
                "price": "preserve",
                "seats": "preserve",
                "licenses": "preserve",
                "user_limit": "preserve",
                "api_limit": "preserve",
                "storage_limit": "preserve",

                # Dates - preserve year/month
                "created_at": "preserve",
                "created_date": "preserve",
                "signup_date": "date",
                "updated_at": "preserve",
                "deleted_at": "preserve",
                "last_login": "date",
                "last_login_date": "date",
                "last_activity": "date",
                "trial_end_date": "date",
                "billing_cycle_date": "preserve",

                # Usage metrics - preserve for analytics
                "monthly_api_calls": "preserve",
                "api_calls": "preserve",
                "requests_used": "preserve",
                "storage_gb": "preserve",
                "storage_used": "preserve",
                "data_transferred": "preserve",
                "sessions": "preserve",
                "active_users": "preserve",
                "page_views": "preserve",
                "events_processed": "preserve",

                # Activity - preserve for analytics
                "login_count": "preserve",
                "failed_login_count": "preserve",
                "actions_count": "preserve",
                "documents_created": "preserve",
                "integrations_active": "preserve",

                # Technical - mask
                "login_ip": "ip_address",
                "ip_address": "ip_address",
                "last_ip": "ip_address",
                "user_agent": "text_redaction",
                "device_id": "custom",
                "device_type": "preserve",
                "browser": "preserve",
                "os": "preserve",

                # Features - preserve
                "features_enabled": "preserve",
                "add_ons": "preserve",
                "integrations": "preserve",
                "api_key_count": "preserve",
                "sso_enabled": "preserve",
                "mfa_enabled": "preserve",
                "audit_logs": "preserve",

                # Status/metadata - preserve
                "status": "preserve",
                "account_status": "preserve",
                "verified": "preserve",
                "is_admin": "preserve",
                "is_active": "preserve",
                "tags": "preserve",
            },
            defaults="preserve",
        )

    @classmethod
    def create_factory(cls) -> StrategyFactory:
        """Create factory for SaaS data anonymization.

        Returns:
            Configured StrategyFactory for SaaS user/account data.
        """
        profile = cls.get_profile()
        return StrategyFactory(profile)

    @classmethod
    def anonymize(cls, data: dict) -> dict:
        """Anonymize SaaS user/account data.

        Args:
            data: User, account, or organization data dictionary.

        Returns:
            Anonymized data with PII masked and usage metrics preserved.

        Example:
            >>> data = {
            ...     "user_id": "USR-789456",
            ...     "first_name": "John",
            ...     "text_redaction": "john@example.com",
            ...     "organization_name": "Acme Corp",
            ...     "monthly_cost": 999,
            ...     "api_calls": 5000000,
            ... }
            >>> result = SaaSScenario.anonymize(data)
            >>> result["user_id"]  # Preserved
            'USR-789456'
            >>> result["first_name"]  # Anonymized
            'Michael'
            >>> result["text_redaction"]  # Redacted
            '[EMAIL]'
            >>> result["organization_name"]  # Masked
            'ABC'
            >>> result["monthly_cost"]  # Preserved
            999
        """
        factory = cls.create_factory()
        return factory.anonymize(data)

    @classmethod
    def anonymize_batch(cls, data_list: list[dict]) -> list[dict]:
        """Anonymize batch of SaaS records.

        Args:
            data_list: List of user/account/organization records.

        Returns:
            List of anonymized SaaS data records.
        """
        factory = cls.create_factory()
        return [factory.anonymize(record) for record in data_list]

    @classmethod
    def get_strategy_info(cls) -> dict:
        """Get information about strategies used.

        Returns:
            Dictionary mapping column names to strategy names.
        """
        profile = cls.get_profile()
        factory = StrategyFactory(profile)
        return factory.list_column_strategies()
