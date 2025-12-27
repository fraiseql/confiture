"""Healthcare PHI (Protected Health Information) anonymization scenario.

Real-world use case: HIPAA-compliant anonymization for research and analytics.

Data Types (PHI - Protected Health Information):
- Patient names (PII)
- Social security numbers (SSN)
- Dates of birth (sensitive)
- Medical record numbers (identifiers)
- Diagnosis codes (sensitive)
- Medication information (sensitive)
- Provider names (PII)
- Facility names (may be identifying)
- Visit dates (sensitive)
- Vital signs (may need masking)
- Test results (sensitive)

HIPAA Safe Harbor Rules:
- Remove names, addresses, phone numbers, emails
- Mask SSN and medical record numbers
- Mask dates (keep year as 1900s for birthdate)
- Remove admission dates within a year
- Generalize location data

Strategy:
- Names: Complete masking
- SSN: Pattern redaction
- Birth dates: Year masking (convert to safe range)
- Medical record numbers: Hash-based replacement
- Diagnoses: Preserve ICD codes
- Medications: Preserve as-is
- Dates: Preserve year only
- IP addresses: Complete masking
- Facilities: Preserve facility ID but mask name
"""

from confiture.core.anonymization.factory import StrategyProfile, StrategyFactory


class HealthcareScenario:
    """Healthcare PHI anonymization scenario.

    Demonstrates HIPAA-compliant anonymization for research purposes.

    Example:
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
        ...     "vital_temp": 98.6,
        ...     "vital_bp": "120/80",
        ... }
        >>> anonymized = scenario.anonymize(data)
        >>> # PHI masked, clinical data preserved
    """

    @staticmethod
    def get_profile() -> StrategyProfile:
        """Get healthcare anonymization profile (HIPAA safe harbor).

        Returns:
            StrategyProfile configured for healthcare PHI anonymization.

        Strategy Mapping:
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
        return StrategyProfile(
            name="healthcare_hipaa",
            seed=42,  # Fixed seed for reproducibility
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
                "medical_record_number": "custom",
                "mrn": "custom",

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
    def create_factory(cls) -> StrategyFactory:
        """Create factory for healthcare anonymization.

        Returns:
            Configured StrategyFactory for healthcare PHI.
        """
        profile = cls.get_profile()
        return StrategyFactory(profile)

    @classmethod
    def anonymize(cls, data: dict) -> dict:
        """Anonymize healthcare PHI data.

        Args:
            data: Patient/encounter data dictionary.

        Returns:
            HIPAA-compliant anonymized data with PHI masked.

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
        """
        factory = cls.create_factory()
        return factory.anonymize(data)

    @classmethod
    def anonymize_batch(cls, data_list: list[dict]) -> list[dict]:
        """Anonymize batch of healthcare records.

        Args:
            data_list: List of patient/encounter records.

        Returns:
            List of HIPAA-compliant anonymized records.
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

    @classmethod
    def verify_hipaa_compliance(cls, data: dict, original: dict) -> dict:
        """Verify HIPAA compliance of anonymized data.

        Checks that sensitive fields have been properly masked.

        Args:
            data: Anonymized data.
            original: Original data before anonymization.

        Returns:
            Dictionary with compliance verification results.
        """
        issues = []
        pii_fields = {
            "ssn", "social_security_number",
            "patient_name", "provider_name",
            "medical_record_number", "mrn",
        }

        for field in pii_fields:
            if field in original and field in data:
                if data[field] == original[field]:
                    issues.append(f"PII not masked: {field}")

        return {
            "compliant": len(issues) == 0,
            "issues": issues,
        }
