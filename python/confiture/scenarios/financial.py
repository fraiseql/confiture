"""Financial services PII and sensitive data anonymization scenario.

Real-world use case: Anonymizing loan applications, credit data, and financial records.

Data Types:
- Applicant names (PII)
- Social security numbers (PII - highly sensitive)
- Email addresses (PII)
- Phone numbers (PII)
- Physical addresses (PII)
- Employment information (sensitive)
- Income data (sensitive)
- Credit scores (sensitive)
- Bank account information (PCI-DSS)
- Loan amounts (preserve for analysis)
- Interest rates (preserve for analysis)
- Credit limit (preserve for analysis)
- Dates (application, decision, disbursement)
- Employment dates (sensitive)

Strategy:
- Names: Complete masking
- SSN: Pattern redaction (###-##-XXXX)
- Email: Email redaction
- Phone: Phone masking
- Addresses: Field preservation (state/zip)
- Employment: Name masking + dates
- Income: Preserve (business data)
- Credit scores: Preserve (business data)
- Bank accounts: Hash replacement
- Loan amounts: Preserve (business data)
- Dates: Preserve year/month
"""

from confiture.core.anonymization.factory import StrategyFactory, StrategyProfile


class FinancialScenario:
    """Financial services data anonymization scenario.

    Demonstrates anonymizing loan applications and credit data while preserving
    financial analytics data.

    Example:
        >>> scenario = FinancialScenario()
        >>> data = {
        ...     "application_id": "APP-2024-001",
        ...     "applicant_name": "John Smith",
        ...     "ssn": "123-45-6789",
        ...     "text_redaction": "john.smith@example.com",
        ...     "text_redaction": "555-123-4567",
        ...     "address": "123 Main St, Anytown, CA 90210",
        ...     "employment_name": "Acme Corp",
        ...     "employment_address": "456 Corporate Blvd",
        ...     "employment_start": "2015-06-01",
        ...     "employment_end": "2024-01-15",
        ...     "annual_income": 75000,
        ...     "credit_score": 750,
        ...     "bank_account": "4532194857632145",
        ...     "loan_amount": 250000,
        ...     "interest_rate": 4.5,
        ...     "loan_term": 30,
        ...     "application_date": "2024-11-01",
        ...     "decision_date": "2024-11-15",
        ... }
        >>> anonymized = scenario.anonymize(data)
        >>> # PII masked, financial metrics preserved
    """

    @staticmethod
    def get_profile() -> StrategyProfile:
        """Get financial data anonymization profile.

        Returns:
            StrategyProfile configured for financial data anonymization.

        Strategy Mapping:
            - application_id: preserve (business identifier)
            - applicant_name: name masking
            - ssn: SSN pattern redaction
            - email: email redaction
            - phone: phone masking
            - address: address masking (preserve state/zip)
            - employment_name: name masking
            - employment_address: address masking
            - employment dates: date masking (preserve year/month)
            - income: preserve (business data)
            - credit_score: preserve (business data)
            - bank_account: custom hash
            - loan_amount: preserve (business data)
            - interest_rate: preserve (business data)
            - application_date: date masking
        """
        return StrategyProfile(
            name="financial_services",
            seed=42,  # Fixed seed for reproducibility
            columns={
                # Application identifiers - preserve
                "application_id": "preserve",
                "loan_id": "preserve",
                "account_id": "preserve",
                "reference_number": "preserve",
                # Applicant PII - mask
                "applicant_name": "name",
                "first_name": "name",
                "last_name": "name",
                "full_name": "name",
                "co_applicant_name": "name",
                # Sensitive identifiers - redact
                "ssn": "text_redaction",
                "social_security_number": "text_redaction",
                "tax_id": "text_redaction",
                "ein": "text_redaction",
                # Contact - redact
                "email": "text_redaction",
                "phone": "text_redaction",
                "phone_number": "text_redaction",
                "cell_phone": "text_redaction",
                "work_phone": "text_redaction",
                # Address - preserve with masking
                "address": "address",
                "street_address": "address",
                "city": "preserve",
                "state": "preserve",
                "zip": "preserve",
                "postal_code": "preserve",
                "country": "preserve",
                # Employment - mask employer name but preserve dates
                "employer_name": "name",
                "employment_name": "name",
                "job_title": "preserve",
                "position": "preserve",
                "employment_address": "address",
                "employment_start_date": "date",
                "employment_end_date": "date",
                "employment_duration": "preserve",
                "years_employed": "preserve",
                # Financial metrics - preserve
                "annual_income": "preserve",
                "income": "preserve",
                "gross_income": "preserve",
                "net_income": "preserve",
                "monthly_income": "preserve",
                "other_income": "preserve",
                "total_assets": "preserve",
                "total_liabilities": "preserve",
                # Credit data - preserve
                "credit_score": "preserve",
                "fico_score": "preserve",
                "credit_limit": "preserve",
                "available_credit": "preserve",
                "outstanding_balance": "preserve",
                "debt_to_income": "preserve",
                "payment_history": "preserve",
                # Bank/Payment - hash accounts
                "bank_account": "custom",
                "bank_account_number": "custom",
                "routing_number": "custom",
                "card_number": "credit_card",
                "account_number": "custom",
                # Loan details - preserve
                "loan_amount": "preserve",
                "principal": "preserve",
                "interest_rate": "preserve",
                "apr": "preserve",
                "loan_term": "preserve",
                "monthly_payment": "preserve",
                "loan_type": "preserve",
                "loan_purpose": "preserve",
                "collateral": "preserve",
                # Dates - mask to year/month
                "application_date": "date",
                "decision_date": "date",
                "approval_date": "date",
                "disbursement_date": "date",
                "closing_date": "date",
                "maturity_date": "date",
                "payment_due_date": "preserve",
                # Document references
                "document_id": "preserve",
                "document_type": "preserve",
                "verification_status": "preserve",
                # IP/technical - mask
                "ip_address": "ip_address",
                "device_id": "preserve",
            },
            defaults="preserve",
        )

    @classmethod
    def create_factory(cls) -> StrategyFactory:
        """Create factory for financial data anonymization.

        Returns:
            Configured StrategyFactory for financial services.
        """
        profile = cls.get_profile()
        return StrategyFactory(profile)

    @classmethod
    def anonymize(cls, data: dict) -> dict:
        """Anonymize financial services data.

        Args:
            data: Loan application or account data dictionary.

        Returns:
            Anonymized data with PII masked and financial metrics preserved.

        Example:
            >>> data = {
            ...     "application_id": "APP-2024-001",
            ...     "applicant_name": "John Smith",
            ...     "ssn": "123-45-6789",
            ...     "annual_income": 75000,
            ...     "credit_score": 750,
            ... }
            >>> result = FinancialScenario.anonymize(data)
            >>> result["application_id"]  # Preserved
            'APP-2024-001'
            >>> result["applicant_name"]  # Anonymized
            'Michael Johnson'
            >>> result["ssn"]  # Redacted
            '[REDACTED]'
            >>> result["annual_income"]  # Preserved
            75000
        """
        factory = cls.create_factory()
        return factory.anonymize(data)

    @classmethod
    def anonymize_batch(cls, data_list: list[dict]) -> list[dict]:
        """Anonymize batch of financial records.

        Args:
            data_list: List of loan/account records.

        Returns:
            List of anonymized financial records.
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
