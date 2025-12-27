"""Healthcare PHI (Protected Health Information) anonymization scenario.

Real-world use case: Compliant anonymization for research across multiple regions.

Supports multiple data protection regulations:
- HIPAA (USA) - Safe Harbor rules for de-identification
- GDPR (EU/EEA) - General Data Protection Regulation
- PIPEDA (Canada) - Personal Information Protection Act
- LGPD (Brazil) - Lei Geral de Proteção de Dados
- PIPL (China) - Personal Information Protection Law
- Privacy Act (Australia) - Privacy Act 1988
- POPIA (South Africa) - Protection of Personal Information Act

Data Types (PHI - Protected Health Information):
- Patient names (PII)
- Social security numbers / Tax IDs (SSN)
- Dates of birth (sensitive)
- Medical record numbers (identifiers)
- Diagnosis codes (sensitive)
- Medication information (sensitive)
- Provider names (PII)
- Facility names (may be identifying)
- Visit dates (sensitive)
- Vital signs (may need masking)
- Test results (sensitive)

Strategy:
- Names: Complete masking
- SSN/Tax IDs: Pattern redaction
- Birth dates: Year masking
- Medical record numbers: Hash-based replacement
- Diagnoses: Preserve ICD codes
- Medications: Preserve as-is
- Dates: Preserve year only
- IP addresses: Complete masking
- Facilities: Preserve facility ID but mask name
"""

from confiture.core.anonymization.factory import StrategyProfile, StrategyFactory
from confiture.scenarios.compliance import RegulationType, ComplianceVerifier, PersonalDataCategories


class HealthcareScenario:
    """Healthcare PHI anonymization scenario supporting multiple regulations.

    Demonstrates anonymization for research across different regions with
    compliance verification for various data protection regulations.

    Example (Default - HIPAA):
        >>> scenario = HealthcareScenario()
        >>> data = {
        ...     "patient_id": "PAT-00123",
        ...     "patient_name": "John Smith",
        ...     "ssn": "123-45-6789",
        ...     "date_of_birth": "1965-03-12",
        ...     "medical_record_number": "MRN-999888",
        ...     "diagnosis": "E11",  # Type 2 diabetes
        ...     "medication": "Metformin 500mg",
        ...     "visit_date": "2024-12-15",
        ...     "provider_name": "Dr. Sarah Johnson",
        ...     "facility_name": "St. Mary's Hospital",
        ... }
        >>> anonymized = scenario.anonymize(data)
        >>> # PHI masked, clinical data preserved

    Example (GDPR):
        >>> anonymized = scenario.anonymize(data, regulation=RegulationType.GDPR)
        >>> compliant = scenario.verify_compliance(data, anonymized, RegulationType.GDPR)
    """

    # Default seed for reproducibility
    DEFAULT_SEED = 42

    @staticmethod
    def get_profile(regulation: RegulationType = RegulationType.GDPR) -> StrategyProfile:
        """Get healthcare anonymization profile for specified regulation.

        Args:
            regulation: Target data protection regulation. Defaults to GDPR.

        Returns:
            StrategyProfile configured for healthcare PHI anonymization.

        Strategy Mapping (applies to all regulations):
            - patient_id: preserve (study identifier)
            - patient_name: name masking (complete)
            - ssn: text redaction (SSN pattern)
            - date_of_birth: date masking (year conversion to safe range)
            - medical_record_number: custom hash
            - diagnosis: preserve (ICD code)
            - medication: preserve (clinical)
            - visit_date: date masking (year only)
            - provider_name: name masking
            - facility_name: name masking
            - vital signs: preserve (clinical)
            - test results: preserve (clinical)
        """
        profile_name = f"healthcare_{regulation.value}"
        return StrategyProfile(
            name=profile_name,
            seed=HealthcareScenario.DEFAULT_SEED,  # Fixed seed for reproducibility
            columns={
                # Study/research identifiers - preserve
                "patient_id": "preserve",
                "study_id": "preserve",
                "record_id": "preserve",

                # PII - mask completely
                "patient_name": "name",
                "first_name": "name",
                "last_name": "name",
                "provider_name": "name",
                "provider_first": "name",
                "provider_last": "name",

                # Identifiers - redact/mask
                "ssn": "text_redaction",
                "social_security_number": "text_redaction",
                "medical_record_number": "text_redaction",
                "mrn": "text_redaction",

                # Contact - redact
                "email": "text_redaction",
                "phone": "text_redaction",
                "phone_number": "text_redaction",
                "address": "address",

                # Sensitive dates - mask to year only
                "date_of_birth": "date",
                "birth_date": "date",
                "dob": "date",
                "admission_date": "date",
                "discharge_date": "date",
                "visit_date": "date",
                "appointment_date": "date",
                "procedure_date": "date",
                "test_date": "date",

                # Clinical data - preserve
                "diagnosis": "preserve",
                "diagnosis_code": "preserve",
                "icd_code": "preserve",
                "procedure": "preserve",
                "procedure_code": "preserve",
                "medication": "preserve",
                "drug_name": "preserve",
                "dosage": "preserve",
                "route": "preserve",
                "frequency": "preserve",

                # Vital signs - preserve
                "temperature": "preserve",
                "heart_rate": "preserve",
                "blood_pressure": "preserve",
                "respiratory_rate": "preserve",
                "oxygen_saturation": "preserve",
                "weight": "preserve",
                "height": "preserve",
                "bmi": "preserve",

                # Lab results - preserve
                "test_name": "preserve",
                "test_value": "preserve",
                "test_result": "preserve",
                "lab_result": "preserve",
                "reference_range": "preserve",

                # Facility - preserve facility ID but mask name
                "facility_id": "preserve",
                "facility_name": "name",
                "facility_code": "preserve",
                "department": "preserve",
                "ward": "preserve",

                # Location - generalize
                "city": "preserve",
                "state": "preserve",
                "country": "preserve",

                # Metadata - preserve
                "encounter_type": "preserve",
                "admission_type": "preserve",
                "discharge_disposition": "preserve",
                "status": "preserve",

                # IP/technical - mask
                "ip_address": "ip_address",
                "device_id": "preserve",
            },
            defaults="preserve",
        )

    @classmethod
    def create_factory(cls, regulation: RegulationType = RegulationType.GDPR) -> StrategyFactory:
        """Create factory for healthcare anonymization.

        Args:
            regulation: Target data protection regulation. Defaults to GDPR.

        Returns:
            Configured StrategyFactory for healthcare PHI.
        """
        profile = cls.get_profile(regulation)
        return StrategyFactory(profile)

    @classmethod
    def anonymize(cls, data: dict, regulation: RegulationType = RegulationType.GDPR) -> dict:
        """Anonymize healthcare PHI data according to specified regulation.

        Args:
            data: Patient/encounter data dictionary.
            regulation: Target data protection regulation. Defaults to GDPR.

        Returns:
            Compliant anonymized data with PHI masked.

        Example:
            >>> data = {
            ...     "patient_id": "PAT-00123",
            ...     "patient_name": "John Smith",
            ...     "ssn": "123-45-6789",
            ...     "diagnosis": "E11",
            ...     "medication": "Metformin 500mg",
            ... }
            >>> result = HealthcareScenario.anonymize(data)
            >>> result["patient_id"]  # Preserved
            'PAT-00123'
            >>> result["patient_name"]  # Anonymized
            'Michael Johnson'
            >>> result["ssn"]  # Redacted
            '[REDACTED]'
            >>> result["diagnosis"]  # Preserved
            'E11'

            >>> # Use different regulation
            >>> result_ccpa = HealthcareScenario.anonymize(data, RegulationType.CCPA)
        """
        factory = cls.create_factory(regulation)
        return factory.anonymize(data)

    @classmethod
    def anonymize_batch(cls, data_list: list[dict], regulation: RegulationType = RegulationType.GDPR) -> list[dict]:
        """Anonymize batch of healthcare records.

        Args:
            data_list: List of patient/encounter records.
            regulation: Target data protection regulation. Defaults to GDPR.

        Returns:
            List of compliant anonymized records.
        """
        factory = cls.create_factory(regulation)
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

    @classmethod
    def verify_compliance(
        cls, original: dict, anonymized: dict, regulation: RegulationType = RegulationType.GDPR
    ) -> dict:
        """Verify compliance of anonymized data with specified regulation.

        Checks that sensitive fields have been properly masked according to
        the regulation's requirements.

        Args:
            original: Original data before anonymization.
            anonymized: Anonymized data.
            regulation: Target data protection regulation. Defaults to GDPR.

        Returns:
            Dictionary with compliance verification results including:
            - compliant: Boolean indicating compliance status
            - regulation: Name of regulation checked
            - masked_fields: List of fields that were anonymized
            - preserved_fields: List of fields that were preserved
            - issues: List of compliance issues if any
            - masked_count: Number of masked fields
            - preserved_count: Number of preserved fields

        Example:
            >>> data = {
            ...     "patient_id": "PAT-123",
            ...     "patient_name": "John Smith",
            ...     "ssn": "123-45-6789",
            ... }
            >>> anon = HealthcareScenario.anonymize(data, RegulationType.GDPR)
            >>> result = HealthcareScenario.verify_compliance(data, anon, RegulationType.GDPR)
            >>> print(result["compliant"])
            True
        """
        verifier = ComplianceVerifier(regulation)
        return verifier.verify_anonymization(original, anonymized)

    @classmethod
    def get_compliance_requirements(cls, regulation: RegulationType = RegulationType.GDPR) -> dict:
        """Get compliance requirements for specified regulation.

        Args:
            regulation: Target data protection regulation. Defaults to GDPR.

        Returns:
            Dictionary with regulation requirements including applicable
            data categories and consent requirements.

        Example:
            >>> reqs = HealthcareScenario.get_compliance_requirements(RegulationType.GDPR)
            >>> print(reqs["total_categories"])  # Number of applicable categories
            15
        """
        verifier = ComplianceVerifier(regulation)
        return verifier.get_requirements()
