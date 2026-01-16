"""E-commerce customer data anonymization scenario.

Real-world use case: Anonymizing customer data for analytics while protecting PII.

Data Types:
- Customer names (PII)
- Email addresses (PII)
- Phone numbers (PII)
- Physical addresses (PII)
- Birth dates (sensitive)
- Payment methods (PCI-DSS)
- Order totals (safe to keep)
- Order dates (may need masking)

Strategy:
- Names: Firstname/lastname format
- Emails: Email redaction pattern
- Phone: Phone masking
- Addresses: Field preservation (city, state only)
- Dates: Month/year only
- Credit cards: Last 4 digits only
- Order totals: Preserve as-is
- Order dates: Preserve year/month
"""

from confiture.core.anonymization.factory import StrategyFactory, StrategyProfile


class ECommerceScenario:
    """E-commerce data anonymization scenario.

    Demonstrates anonymizing customer data while preserving business analytics data.

    Example:
        >>> scenario = ECommerceScenario()
        >>> data = {
        ...     "customer_id": "CUST-12345",
        ...     "first_name": "John",
        ...     "last_name": "Doe",
        ...     "email": "john.doe@example.com",
        ...     "phone": "555-123-4567",
        ...     "address": "123 Main St, Anytown, CA 90210",
        ...     "birth_date": "1985-06-15",
        ...     "payment_method": "Visa",
        ...     "card_number": "4242424242424242",
        ...     "order_total": 129.99,
        ...     "order_date": "2024-12-15",
        ... }
        >>> anonymized = scenario.anonymize(data)
        >>> # PII masked, business data preserved
    """

    @staticmethod
    def get_profile() -> StrategyProfile:
        """Get E-commerce anonymization profile.

        Returns:
            StrategyProfile configured for e-commerce data.

        Strategy Mapping:
            - customer_id: preserve (business identifier)
            - first_name: name masking (firstname only)
            - last_name: name masking (lastname only)
            - email: email redaction
            - phone: phone masking
            - address: address masking (city/state only)
            - birth_date: date masking (preserve year/month)
            - payment_method: preserve (business data)
            - card_number: credit card masking (last 4)
            - order_total: preserve (business data)
            - order_date: date masking (preserve year/month)
        """
        return StrategyProfile(
            name="ecommerce",
            seed=42,  # Fixed seed for reproducibility
            columns={
                # Identifiers - preserve
                "customer_id": "preserve",
                "order_id": "preserve",

                # PII - mask
                "first_name": "name",
                "last_name": "name",
                "full_name": "name",
                "customer_name": "name",

                # Contact - redact
                "email": "text_redaction",
                "phone": "text_redaction",
                "phone_number": "text_redaction",

                # Address - preserve with masking
                "address": "address",
                "street": "address",
                "city": "preserve",  # Often kept for analytics
                "state": "preserve",
                "zip": "preserve",
                "postal_code": "preserve",

                # Sensitive dates - mask month/year
                "birth_date": "date",
                "dob": "date",
                "date_of_birth": "date",

                # Payment - PCI-DSS compliant
                "payment_method": "preserve",
                "payment_type": "preserve",
                "card_type": "preserve",
                "card_number": "credit_card",

                # Business data - preserve
                "order_total": "preserve",
                "order_amount": "preserve",
                "subtotal": "preserve",
                "tax": "preserve",
                "shipping": "preserve",
                "discount": "preserve",
                "quantity": "preserve",
                "product_id": "preserve",
                "sku": "preserve",

                # Dates - preserve with masking
                "order_date": "date",
                "purchase_date": "date",
                "created_at": "date",
                "updated_at": "date",
                "shipped_date": "date",
                "delivered_date": "date",

                # Location data
                "ip_address": "ip_address",
                "country": "preserve",
                "region": "preserve",
            },
            defaults="preserve",
        )

    @classmethod
    def create_factory(cls) -> StrategyFactory:
        """Create factory for e-commerce anonymization.

        Returns:
            Configured StrategyFactory for e-commerce data.
        """
        profile = cls.get_profile()
        return StrategyFactory(profile)

    @classmethod
    def anonymize(cls, data: dict) -> dict:
        """Anonymize e-commerce data.

        Args:
            data: Customer/order data dictionary.

        Returns:
            Anonymized data with PII masked and business data preserved.

        Example:
            >>> data = {
            ...     "customer_id": "CUST-12345",
            ...     "first_name": "John",
            ...     "email": "john@example.com",
            ...     "order_total": 129.99,
            ... }
            >>> result = ECommerceScenario.anonymize(data)
            >>> result["customer_id"]  # Preserved
            'CUST-12345'
            >>> result["first_name"]  # Anonymized
            'Michael'
            >>> result["email"]  # Redacted
            '[EMAIL]'
            >>> result["order_total"]  # Preserved
            129.99
        """
        factory = cls.create_factory()
        return factory.anonymize(data)

    @classmethod
    def anonymize_batch(cls, data_list: list[dict]) -> list[dict]:
        """Anonymize batch of e-commerce data.

        Args:
            data_list: List of customer/order data dictionaries.

        Returns:
            List of anonymized data records.

        Example:
            >>> data = [
            ...     {"customer_id": "CUST-1", "first_name": "John", ...},
            ...     {"customer_id": "CUST-2", "first_name": "Jane", ...},
            ... ]
            >>> results = ECommerceScenario.anonymize_batch(data)
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
