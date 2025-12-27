"""Comprehensive tests for multi-region data protection compliance.

Tests verify:
1. Healthcare scenario works with multiple regulations
2. Compliance verification for each regulation
3. Compliance requirements match expectations
4. Anonymization is consistent across regulations
5. GDPR, CCPA, PIPEDA, LGPD, PIPL, Privacy Act, POPIA support
"""

import pytest
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import (
    RegulationType,
    ComplianceVerifier,
    PersonalDataCategories,
    REGULATION_GUIDANCE,
)


class TestComplianceFramework:
    """Tests for basic compliance framework functionality."""

    def test_regulation_type_enum(self):
        """Test RegulationType enum has all required regulations."""
        regulations = [
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ]
        assert len(regulations) == 7

    def test_regulation_values(self):
        """Test regulation type values are lowercase strings."""
        assert RegulationType.GDPR.value == "gdpr"
        assert RegulationType.CCPA.value == "ccpa"
        assert RegulationType.PIPEDA.value == "pipeda"
        assert RegulationType.LGPD.value == "lgpd"
        assert RegulationType.PIPL.value == "pipl"
        assert RegulationType.PRIVACY_ACT.value == "privacy_act"
        assert RegulationType.POPIA.value == "popia"

    def test_regulation_guidance_coverage(self):
        """Test REGULATION_GUIDANCE has entries for all regulations."""
        regulations = [
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ]
        for regulation in regulations:
            assert regulation in REGULATION_GUIDANCE
            guidance = REGULATION_GUIDANCE[regulation]
            assert "name" in guidance
            assert "region" in guidance
            assert "effective_date" in guidance
            assert "scope" in guidance
            assert "key_principles" in guidance
            assert "anonymization_standard" in guidance
            assert "consent_requirement" in guidance
            assert "data_subject_rights" in guidance
            assert "penalty" in guidance

    def test_personal_data_categories(self):
        """Test PersonalDataCategories has all expected categories."""
        categories = [
            PersonalDataCategories.DIRECT_IDENTIFIERS,
            PersonalDataCategories.QUASI_IDENTIFIERS,
            PersonalDataCategories.HEALTH_DATA,
            PersonalDataCategories.GENETIC_DATA,
            PersonalDataCategories.BIOMETRIC_DATA,
            PersonalDataCategories.FINANCIAL_DATA,
            PersonalDataCategories.LOCATION_DATA,
            PersonalDataCategories.COMMUNICATION_DATA,
            PersonalDataCategories.EMPLOYMENT_DATA,
            PersonalDataCategories.EDUCATION_DATA,
            PersonalDataCategories.RACIAL_ETHNIC_DATA,
            PersonalDataCategories.POLITICAL_DATA,
            PersonalDataCategories.RELIGIOUS_DATA,
            PersonalDataCategories.UNION_DATA,
            PersonalDataCategories.CHILDREN_DATA,
        ]
        assert len(categories) == 15

    def test_categories_apply_to_regulation(self):
        """Test that categories properly report which regulations apply to them."""
        # Direct identifiers should apply to all regulations
        direct_ids = PersonalDataCategories.DIRECT_IDENTIFIERS
        for regulation in [
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
        ]:
            assert direct_ids.applies_to(regulation)

        # Political data only applies to specific regulations (not CCPA)
        political = PersonalDataCategories.POLITICAL_DATA
        assert political.applies_to(RegulationType.GDPR)
        assert not political.applies_to(RegulationType.CCPA)

    def test_compliance_verifier_initialization(self):
        """Test ComplianceVerifier initializes correctly."""
        verifier = ComplianceVerifier(RegulationType.GDPR)
        assert verifier.regulation == RegulationType.GDPR
        assert len(verifier.categories) > 0

    def test_compliance_verifier_categories(self):
        """Test ComplianceVerifier has correct categories for each regulation."""
        # GDPR should have all 15 categories
        gdpr_verifier = ComplianceVerifier(RegulationType.GDPR)
        assert len(gdpr_verifier.categories) == 15

        # Political data should only be in some regulations
        pipl_verifier = ComplianceVerifier(RegulationType.PIPL)
        political_in_pipl = any(
            c.name == "Political Affiliation" for c in pipl_verifier.categories
        )
        assert not political_in_pipl  # PIPL doesn't include political data


class TestHealthcareComplianceGDPR:
    """Tests for healthcare scenario with GDPR compliance."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-00123",
            "patient_name": "John Smith",
            "ssn": "123-45-6789",
            "date_of_birth": "1965-03-12",
            "medical_record_number": "MRN-999888",
            "diagnosis": "E11",
            "medication": "Metformin 500mg",
            "visit_date": "2024-12-15",
            "provider_name": "Dr. Sarah Johnson",
            "facility_name": "St. Mary's Hospital",
            "temperature": 98.6,
            "blood_pressure": "120/80",
        }

    def test_anonymize_with_gdpr(self, sample_data):
        """Test anonymization with GDPR regulation."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.GDPR)

        # Check that PII is masked
        assert anonymized["patient_name"] != sample_data["patient_name"]
        assert anonymized["provider_name"] != sample_data["provider_name"]
        assert anonymized["facility_name"] != sample_data["facility_name"]

        # Check that clinical data is preserved
        assert anonymized["diagnosis"] == sample_data["diagnosis"]
        assert anonymized["medication"] == sample_data["medication"]

        # Check that identifiers are preserved
        assert anonymized["patient_id"] == sample_data["patient_id"]

    def test_gdpr_compliance_verification(self, sample_data):
        """Test GDPR compliance verification."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.GDPR)
        result = HealthcareScenario.verify_compliance(
            sample_data, anonymized, RegulationType.GDPR
        )

        assert isinstance(result, dict)
        assert "compliant" in result
        assert "regulation" in result
        assert "masked_fields" in result
        assert "preserved_fields" in result
        assert "issues" in result

        # GDPR is strict, should have masked most PII
        assert "patient_name" in result["masked_fields"]
        assert "provider_name" in result["masked_fields"]
        assert "facility_name" in result["masked_fields"]

    def test_gdpr_requirements(self):
        """Test GDPR compliance requirements."""
        reqs = HealthcareScenario.get_compliance_requirements(RegulationType.GDPR)

        assert reqs["regulation"] == "gdpr"
        assert reqs["total_categories"] == 15
        assert len(reqs["requires_anonymization"]) > 0
        assert len(reqs["requires_explicit_consent"]) > 0


class TestHealthcareComplianceCCPA:
    """Tests for healthcare scenario with CCPA compliance."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-00456",
            "patient_name": "Jane Doe",
            "ssn": "987-65-4321",
            "date_of_birth": "1980-07-22",
            "medical_record_number": "MRN-777666",
            "diagnosis": "J45",
            "medication": "Albuterol inhaler",
            "visit_date": "2024-11-20",
            "provider_name": "Dr. Robert Williams",
            "facility_name": "General Hospital",
        }

    def test_anonymize_with_ccpa(self, sample_data):
        """Test anonymization with CCPA regulation."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.CCPA)

        # Check basic structure is maintained
        assert "patient_id" in anonymized
        assert "diagnosis" in anonymized

        # PII should be masked
        assert anonymized["patient_name"] != sample_data["patient_name"]

    def test_ccpa_compliance_verification(self, sample_data):
        """Test CCPA compliance verification."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.CCPA)
        result = HealthcareScenario.verify_compliance(
            sample_data, anonymized, RegulationType.CCPA
        )

        assert result["regulation"] == "ccpa"
        assert isinstance(result["compliant"], bool)

    def test_ccpa_requirements(self):
        """Test CCPA compliance requirements."""
        reqs = HealthcareScenario.get_compliance_requirements(RegulationType.CCPA)

        assert reqs["regulation"] == "ccpa"
        assert reqs["total_categories"] > 0


class TestHealthcareCompliancePIPEDA:
    """Tests for healthcare scenario with PIPEDA compliance."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-00789",
            "patient_name": "Michael Brown",
            "ssn": "555-55-5555",
            "email": "michael@example.com",
            "diagnosis": "K21",
            "medication": "Omeprazole",
            "visit_date": "2024-12-01",
            "provider_name": "Dr. Lisa Chen",
            "facility_name": "Maple Leaf Clinic",
        }

    def test_anonymize_with_pipeda(self, sample_data):
        """Test anonymization with PIPEDA regulation."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.PIPEDA)

        assert "patient_id" in anonymized
        assert anonymized["patient_id"] == sample_data["patient_id"]

    def test_pipeda_compliance_verification(self, sample_data):
        """Test PIPEDA compliance verification."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.PIPEDA)
        result = HealthcareScenario.verify_compliance(
            sample_data, anonymized, RegulationType.PIPEDA
        )

        assert result["regulation"] == "pipeda"


class TestHealthcareComplianceLGPD:
    """Tests for healthcare scenario with LGPD compliance."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-01011",
            "patient_name": "Maria Santos",
            "ssn": "444-44-4444",
            "city": "São Paulo",
            "diagnosis": "E10",
            "medication": "Insulin",
        }

    def test_anonymize_with_lgpd(self, sample_data):
        """Test anonymization with LGPD regulation."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.LGPD)

        assert "patient_id" in anonymized
        # Clinical data should be preserved
        assert anonymized["diagnosis"] == sample_data["diagnosis"]

    def test_lgpd_requirements(self):
        """Test LGPD compliance requirements."""
        reqs = HealthcareScenario.get_compliance_requirements(RegulationType.LGPD)

        assert reqs["regulation"] == "lgpd"


class TestHealthcareCompliancePIPL:
    """Tests for healthcare scenario with PIPL compliance."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-01213",
            "patient_name": "Wei Wang",
            "ssn": "333-33-3333",
            "diagnosis": "I10",
            "medication": "Amlodipine",
        }

    def test_anonymize_with_pipl(self, sample_data):
        """Test anonymization with PIPL regulation."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.PIPL)

        assert "patient_id" in anonymized

    def test_pipl_requirements(self):
        """Test PIPL compliance requirements."""
        reqs = HealthcareScenario.get_compliance_requirements(RegulationType.PIPL)

        assert reqs["regulation"] == "pipl"


class TestHealthcareCompliancePrivacyAct:
    """Tests for healthcare scenario with Australian Privacy Act compliance."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-01415",
            "patient_name": "James Wilson",
            "ssn": "222-22-2222",
            "city": "Sydney",
            "country": "Australia",
            "diagnosis": "M19",
            "medication": "Paracetamol",
        }

    def test_anonymize_with_privacy_act(self, sample_data):
        """Test anonymization with Privacy Act regulation."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.PRIVACY_ACT)

        assert "patient_id" in anonymized
        assert anonymized["country"] == sample_data["country"]

    def test_privacy_act_requirements(self):
        """Test Privacy Act compliance requirements."""
        reqs = HealthcareScenario.get_compliance_requirements(
            RegulationType.PRIVACY_ACT
        )

        assert reqs["regulation"] == "privacy_act"


class TestHealthcareCompliancePOPIA:
    """Tests for healthcare scenario with POPIA compliance."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-01617",
            "patient_name": "Thabo Dlamini",
            "ssn": "111-11-1111",
            "city": "Johannesburg",
            "country": "South Africa",
            "diagnosis": "R05",
            "medication": "Aspirin",
        }

    def test_anonymize_with_popia(self, sample_data):
        """Test anonymization with POPIA regulation."""
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.POPIA)

        assert "patient_id" in anonymized

    def test_popia_requirements(self):
        """Test POPIA compliance requirements."""
        reqs = HealthcareScenario.get_compliance_requirements(RegulationType.POPIA)

        assert reqs["regulation"] == "popia"


class TestComplianceCrossRegulation:
    """Tests for compliance across multiple regulations."""

    @pytest.fixture
    def sample_data(self):
        """Sample healthcare data for testing."""
        return {
            "patient_id": "PAT-99999",
            "patient_name": "Test Patient",
            "ssn": "999-99-9999",
            "date_of_birth": "1990-05-15",
            "medical_record_number": "MRN-TEST",
            "email": "test@example.com",
            "phone": "555-1234",
            "diagnosis": "Z00",
            "medication": "Vitamin D",
            "visit_date": "2024-12-25",
            "provider_name": "Dr. Test",
            "facility_name": "Test Hospital",
            "temperature": 98.6,
            "blood_pressure": "120/80",
        }

    def test_anonymize_all_regulations(self, sample_data):
        """Test anonymization works with all regulations."""
        regulations = [
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ]

        results = {}
        for regulation in regulations:
            anonymized = HealthcareScenario.anonymize(sample_data, regulation)
            results[regulation] = anonymized

            # All should have patient_id preserved
            assert anonymized["patient_id"] == sample_data["patient_id"]

            # All should have name masked
            assert anonymized["patient_name"] != sample_data["patient_name"]

        # Different regulations can produce different results
        # (depending on implementation details)
        assert len(results) == 7

    def test_verify_compliance_all_regulations(self, sample_data):
        """Test compliance verification works with all regulations."""
        regulations = [
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ]

        for regulation in regulations:
            anonymized = HealthcareScenario.anonymize(sample_data, regulation)
            result = HealthcareScenario.verify_compliance(
                sample_data, anonymized, regulation
            )

            assert "compliant" in result
            assert "regulation" in result
            assert result["regulation"] == regulation.value

    def test_consistency_across_anonymizations(self, sample_data):
        """Test that same regulation produces consistent anonymizations."""
        # Anonymize twice with same regulation (same seed)
        anon1 = HealthcareScenario.anonymize(sample_data, RegulationType.GDPR)
        anon2 = HealthcareScenario.anonymize(sample_data, RegulationType.GDPR)

        # Masked fields should be identical (deterministic hashing)
        assert anon1["patient_name"] == anon2["patient_name"]
        assert anon1["provider_name"] == anon2["provider_name"]

    def test_requirements_match_verifier_categories(self, sample_data):
        """Test that get_compliance_requirements matches verifier categories."""
        regulations = [
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
        ]

        for regulation in regulations:
            reqs = HealthcareScenario.get_compliance_requirements(regulation)
            verifier = ComplianceVerifier(regulation)

            # Count should match
            assert reqs["total_categories"] == len(verifier.categories)


class TestComplianceBatchProcessing:
    """Tests for batch anonymization with compliance verification."""

    @pytest.fixture
    def sample_batch(self):
        """Sample batch of healthcare records."""
        return [
            {
                "patient_id": "PAT-001",
                "patient_name": "Alice Johnson",
                "ssn": "111-22-3333",
                "diagnosis": "J45",
            },
            {
                "patient_id": "PAT-002",
                "patient_name": "Bob Smith",
                "ssn": "444-55-6666",
                "diagnosis": "E11",
            },
            {
                "patient_id": "PAT-003",
                "patient_name": "Carol Williams",
                "ssn": "777-88-9999",
                "diagnosis": "I10",
            },
        ]

    def test_batch_anonymization_gdpr(self, sample_batch):
        """Test batch anonymization with GDPR."""
        anonymized = HealthcareScenario.anonymize_batch(
            sample_batch, RegulationType.GDPR
        )

        assert len(anonymized) == len(sample_batch)

        for original, anon in zip(sample_batch, anonymized):
            # IDs preserved
            assert anon["patient_id"] == original["patient_id"]

            # Names masked
            assert anon["patient_name"] != original["patient_name"]

            # Diagnosis preserved
            assert anon["diagnosis"] == original["diagnosis"]

    def test_batch_compliance_verification(self, sample_batch):
        """Test batch compliance verification."""
        anonymized = HealthcareScenario.anonymize_batch(
            sample_batch, RegulationType.GDPR
        )

        for original, anon in zip(sample_batch, anonymized):
            result = HealthcareScenario.verify_compliance(
                original, anon, RegulationType.GDPR
            )

            assert "compliant" in result
            assert isinstance(result["compliant"], bool)

    def test_batch_deterministic_anonymization(self, sample_batch):
        """Test that batch anonymization is deterministic."""
        batch1 = HealthcareScenario.anonymize_batch(sample_batch, RegulationType.GDPR)
        batch2 = HealthcareScenario.anonymize_batch(sample_batch, RegulationType.GDPR)

        for rec1, rec2 in zip(batch1, batch2):
            assert rec1["patient_name"] == rec2["patient_name"]
            assert rec1["ssn"] == rec2["ssn"]


class TestRegulationGuidance:
    """Tests for regulation guidance data."""

    def test_gdpr_guidance(self):
        """Test GDPR guidance is complete."""
        guidance = REGULATION_GUIDANCE[RegulationType.GDPR]

        assert guidance["name"] == "General Data Protection Regulation (GDPR)"
        assert "European Union" in guidance["region"]
        assert len(guidance["key_principles"]) >= 7
        assert len(guidance["data_subject_rights"]) >= 7
        assert "€20M" in guidance["penalty"] or "4%" in guidance["penalty"]

    def test_ccpa_guidance(self):
        """Test CCPA guidance is complete."""
        guidance = REGULATION_GUIDANCE[RegulationType.CCPA]

        assert guidance["name"] == "California Consumer Privacy Act (CCPA)"
        assert "California" in guidance["region"]
        assert "$7,500" in guidance["penalty"]

    def test_pipeda_guidance(self):
        """Test PIPEDA guidance is complete."""
        guidance = REGULATION_GUIDANCE[RegulationType.PIPEDA]

        assert guidance["name"] == "Personal Information Protection and Electronic Documents Act"
        assert "Canada" in guidance["region"]
        assert "CAD" in guidance["penalty"]

    def test_lgpd_guidance(self):
        """Test LGPD guidance is complete."""
        guidance = REGULATION_GUIDANCE[RegulationType.LGPD]

        assert guidance["name"] == "Lei Geral de Proteção de Dados (LGPD)"
        assert "Brazil" in guidance["region"]

    def test_pipl_guidance(self):
        """Test PIPL guidance is complete."""
        guidance = REGULATION_GUIDANCE[RegulationType.PIPL]

        assert guidance["name"] == "Personal Information Protection Law (PIPL)"
        assert "China" in guidance["region"]

    def test_privacy_act_guidance(self):
        """Test Privacy Act guidance is complete."""
        guidance = REGULATION_GUIDANCE[RegulationType.PRIVACY_ACT]

        assert guidance["name"] == "Privacy Act 1988 (as amended)"
        assert "Australia" in guidance["region"]

    def test_popia_guidance(self):
        """Test POPIA guidance is complete."""
        guidance = REGULATION_GUIDANCE[RegulationType.POPIA]

        assert guidance["name"] == "Protection of Personal Information Act (POPIA)"
        assert "South Africa" in guidance["region"]
