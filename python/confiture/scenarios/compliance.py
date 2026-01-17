"""Data protection and privacy compliance standards.

Implements anonymization profiles and verification rules for major global
data protection regulations:

- GDPR (EU/EEA): General Data Protection Regulation
- CCPA (USA/California): California Consumer Privacy Act
- PIPEDA (Canada): Personal Information Protection and Electronic Documents Act
- LGPD (Brazil): Lei Geral de Proteção de Dados
- PIPL (China): Personal Information Protection Law
- Privacy Act (Australia): Privacy Act 1988
- POPIA (South Africa): Protection of Personal Information Act

Each regulation defines:
- Personal data categories requiring protection
- Anonymization thresholds
- Verification requirements
- Consent and opt-out mechanisms
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RegulationType(Enum):
    """Enumeration of major data protection regulations."""

    GDPR = "gdpr"  # EU/EEA
    CCPA = "ccpa"  # California, USA
    PIPEDA = "pipeda"  # Canada
    LGPD = "lgpd"  # Brazil
    PIPL = "pipl"  # China
    PRIVACY_ACT = "privacy_act"  # Australia
    POPIA = "popia"  # South Africa
    GENERIC = "generic"  # Generic PII protection


@dataclass
class PersonalDataCategory:
    """Definition of a personal data category under regulations."""

    name: str
    description: str
    regulations: list[RegulationType]
    requires_anonymization: bool
    requires_consent: bool
    retention_period_days: int | None = None
    examples: list[str] | None = None

    def applies_to(self, regulation: RegulationType) -> bool:
        """Check if this category applies to a regulation."""
        return regulation in self.regulations


class PersonalDataCategories:
    """Standard personal data categories across regulations."""

    # Identifiers
    DIRECT_IDENTIFIERS = PersonalDataCategory(
        name="Direct Identifiers",
        description="Information directly identifying a person",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["name", "email", "phone", "passport_number"],
    )

    QUASI_IDENTIFIERS = PersonalDataCategory(
        name="Quasi-Identifiers",
        description="Information that could identify person when combined",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=False,
        examples=["age", "zip_code", "employment_date", "salary_range"],
    )

    # Health data
    HEALTH_DATA = PersonalDataCategory(
        name="Health Data",
        description="Information about physical or mental health",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        retention_period_days=2555,  # 7 years typical
        examples=["diagnosis", "medication", "medical_history", "genetic_data"],
    )

    # Genetic data (special category under GDPR)
    GENETIC_DATA = PersonalDataCategory(
        name="Genetic Data",
        description="Data revealing genetic characteristics",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["dna_profile", "ancestry_data", "genetic_test_results"],
    )

    # Biometric data
    BIOMETRIC_DATA = PersonalDataCategory(
        name="Biometric Data",
        description="Unique biological/behavioral characteristics",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["fingerprint", "facial_recognition", "iris_scan", "voice_print"],
    )

    # Financial data
    FINANCIAL_DATA = PersonalDataCategory(
        name="Financial Data",
        description="Information about financial status and accounts",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        retention_period_days=2555,  # 7 years for compliance
        examples=["bank_account", "credit_card", "salary", "transaction_history"],
    )

    # Location data
    LOCATION_DATA = PersonalDataCategory(
        name="Location Data",
        description="Information about physical location or movements",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["ip_address", "gps_coordinates", "device_location", "travel_history"],
    )

    # Communication data
    COMMUNICATION_DATA = PersonalDataCategory(
        name="Communication Data",
        description="Records of communications and interactions",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=False,
        retention_period_days=365,
        examples=["email_content", "call_logs", "message_history", "browsing_history"],
    )

    # Employment data
    EMPLOYMENT_DATA = PersonalDataCategory(
        name="Employment Data",
        description="Information about employment and professional activities",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=False,
        examples=["employer_name", "job_title", "employment_dates", "salary"],
    )

    # Education data
    EDUCATION_DATA = PersonalDataCategory(
        name="Education Data",
        description="Information about education and training",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=False,
        retention_period_days=3650,  # 10 years typical
        examples=["school_name", "grades", "certificates", "degree"],
    )

    # Racial/ethnic data (special under GDPR, regulated elsewhere)
    RACIAL_ETHNIC_DATA = PersonalDataCategory(
        name="Racial or Ethnic Origin",
        description="Data about racial or ethnic origin",
        regulations=[
            RegulationType.GDPR,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["ethnicity", "race", "ancestry"],
    )

    # Political affiliation (special under GDPR)
    POLITICAL_DATA = PersonalDataCategory(
        name="Political Affiliation",
        description="Data about political opinions or affiliations",
        regulations=[
            RegulationType.GDPR,
            RegulationType.LGPD,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["party_affiliation", "voting_record", "political_donation"],
    )

    # Religious/philosophical data (special under GDPR)
    RELIGIOUS_DATA = PersonalDataCategory(
        name="Religious or Philosophical Beliefs",
        description="Data about religious or philosophical beliefs",
        regulations=[
            RegulationType.GDPR,
            RegulationType.LGPD,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["religion", "belief_system", "church_affiliation"],
    )

    # Trade union membership (special under GDPR)
    UNION_DATA = PersonalDataCategory(
        name="Trade Union Membership",
        description="Data about trade union or professional association membership",
        regulations=[
            RegulationType.GDPR,
            RegulationType.LGPD,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["union_membership", "professional_association"],
    )

    # Children's data (special handling)
    CHILDREN_DATA = PersonalDataCategory(
        name="Children's Data",
        description="Data about children (under 13-16 depending on regulation)",
        regulations=[
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
            RegulationType.LGPD,
            RegulationType.PIPL,
            RegulationType.PRIVACY_ACT,
            RegulationType.POPIA,
        ],
        requires_anonymization=True,
        requires_consent=True,
        examples=["student_id", "school_name", "parental_consent"],
    )

    @classmethod
    def get_for_regulation(cls, regulation: RegulationType) -> list[PersonalDataCategory]:
        """Get all data categories applicable to a regulation."""
        categories = [
            cls.DIRECT_IDENTIFIERS,
            cls.QUASI_IDENTIFIERS,
            cls.HEALTH_DATA,
            cls.GENETIC_DATA,
            cls.BIOMETRIC_DATA,
            cls.FINANCIAL_DATA,
            cls.LOCATION_DATA,
            cls.COMMUNICATION_DATA,
            cls.EMPLOYMENT_DATA,
            cls.EDUCATION_DATA,
            cls.RACIAL_ETHNIC_DATA,
            cls.POLITICAL_DATA,
            cls.RELIGIOUS_DATA,
            cls.UNION_DATA,
            cls.CHILDREN_DATA,
        ]
        return [c for c in categories if c.applies_to(regulation)]


class ComplianceVerifier:
    """Verify anonymization compliance with regulations."""

    def __init__(self, regulation: RegulationType):
        """Initialize verifier for specific regulation.

        Args:
            regulation: Target regulation type
        """
        self.regulation = regulation
        self.categories = PersonalDataCategories.get_for_regulation(regulation)

    def verify_anonymization(
        self, original: dict[str, Any], anonymized: dict[str, Any]
    ) -> dict[str, Any]:
        """Verify that anonymization meets regulation requirements.

        Args:
            original: Original data before anonymization
            anonymized: Data after anonymization

        Returns:
            Dictionary with compliance verification results
        """
        issues = []
        masked_fields = []
        preserved_fields = []

        for field, value in original.items():
            original_val = str(value)
            anon_val = str(anonymized.get(field, ""))

            if original_val != anon_val:
                masked_fields.append(field)
            else:
                preserved_fields.append(field)

        # Check if sensitive categories are masked
        for category in self.categories:
            if category.requires_anonymization:
                for example in category.examples or []:
                    if example in original and example not in masked_fields:
                        issues.append(
                            f"'{example}' ({category.name}) should be anonymized"
                        )

        return {
            "compliant": len(issues) == 0,
            "regulation": self.regulation.value,
            "masked_fields": masked_fields,
            "preserved_fields": preserved_fields,
            "issues": issues,
            "masked_count": len(masked_fields),
            "preserved_count": len(preserved_fields),
        }

    def get_requirements(self) -> dict[str, Any]:
        """Get anonymization requirements for regulation.

        Returns:
            Dictionary with regulation requirements
        """
        requires_consent = [
            c.name for c in self.categories if c.requires_consent
        ]
        requires_anonymization = [
            c.name for c in self.categories if c.requires_anonymization
        ]

        return {
            "regulation": self.regulation.value,
            "total_categories": len(self.categories),
            "requires_anonymization": requires_anonymization,
            "requires_explicit_consent": requires_consent,
            "applicable_categories": [c.name for c in self.categories],
        }


# Regulation-specific guidance
REGULATION_GUIDANCE = {
    RegulationType.GDPR: {
        "name": "General Data Protection Regulation (GDPR)",
        "region": "European Union / European Economic Area",
        "effective_date": "2018-05-25",
        "scope": "Any organization processing data of EU residents",
        "key_principles": [
            "Lawfulness, fairness, transparency",
            "Purpose limitation",
            "Data minimization",
            "Accuracy",
            "Storage limitation",
            "Integrity and confidentiality",
            "Accountability",
        ],
        "anonymization_standard": "Irreversible de-identification with no re-identification risk",
        "consent_requirement": "Explicit opt-in for most processing",
        "data_subject_rights": [
            "Right to access",
            "Right to rectification",
            "Right to erasure (right to be forgotten)",
            "Right to restrict processing",
            "Right to data portability",
            "Right to object",
            "Rights related to automated decision making",
        ],
        "penalty": "Up to €20M or 4% global revenue",
    },
    RegulationType.CCPA: {
        "name": "California Consumer Privacy Act (CCPA)",
        "region": "California, United States",
        "effective_date": "2020-01-01",
        "scope": "Businesses collecting data of California residents",
        "key_principles": [
            "Transparency",
            "Consumer rights",
            "Non-discrimination",
            "Opt-out mechanism",
        ],
        "anonymization_standard": "Aggregate consumer information where individual identity cannot be determined",
        "consent_requirement": "Opt-out mechanism (right to delete, know, opt-out)",
        "data_subject_rights": [
            "Right to know",
            "Right to delete",
            "Right to opt-out",
            "Right to non-discrimination",
        ],
        "penalty": "Up to $7,500 per violation",
    },
    RegulationType.PIPEDA: {
        "name": "Personal Information Protection and Electronic Documents Act",
        "region": "Canada",
        "effective_date": "2004-01-01",
        "scope": "Private sector organizations in Canada",
        "key_principles": [
            "Accountability",
            "Identifying purposes",
            "Consent",
            "Limiting collection",
            "Limiting use",
            "Accuracy",
            "Safeguarding",
            "Openness",
            "Access",
            "Challenging compliance",
        ],
        "anonymization_standard": "Removal of identifying information with minimal re-identification risk",
        "consent_requirement": "Informed consent for collection and use",
        "data_subject_rights": [
            "Right to access",
            "Right to correct inaccuracies",
            "Right to challenge non-compliance",
        ],
        "penalty": "Up to CAD $100,000 per violation",
    },
    RegulationType.LGPD: {
        "name": "Lei Geral de Proteção de Dados (LGPD)",
        "region": "Brazil",
        "effective_date": "2020-09-18",
        "scope": "All organizations processing data of Brazilian residents",
        "key_principles": [
            "Respect for privacy",
            "Self-determination",
            "Free access",
            "Quality",
            "Transparency",
            "Security",
            "Prevention",
            "Non-discrimination",
            "Accountability",
        ],
        "anonymization_standard": "Irreversible de-identification making re-identification impossible",
        "consent_requirement": "Explicit consent required for most processing",
        "data_subject_rights": [
            "Right to access",
            "Right to rectification",
            "Right to deletion",
            "Right to data portability",
            "Right to oppose processing",
        ],
        "penalty": "Up to BRL 50M or 2% annual revenue",
    },
    RegulationType.PIPL: {
        "name": "Personal Information Protection Law (PIPL)",
        "region": "China (People's Republic of)",
        "effective_date": "2021-11-01",
        "scope": "Entities processing personal information in China",
        "key_principles": [
            "Legal basis",
            "Purpose limitation",
            "Data minimization",
            "Accuracy and timeliness",
            "Integrity and confidentiality",
            "Accountability",
        ],
        "anonymization_standard": "Irreversible de-identification with no re-identification possibility",
        "consent_requirement": "Explicit consent and transparency",
        "data_subject_rights": [
            "Right to access",
            "Right to rectification",
            "Right to deletion",
            "Right to know processing rules",
        ],
        "penalty": "Up to CNY 50M or 5% annual revenue",
    },
    RegulationType.PRIVACY_ACT: {
        "name": "Privacy Act 1988 (as amended)",
        "region": "Australia",
        "effective_date": "1988-12-21",
        "scope": "Australian government agencies and private sector organizations",
        "key_principles": [
            "Collection",
            "Use and disclosure",
            "Data quality",
            "Data security",
            "Openness",
            "Access and correction",
            "Unique identifiers",
            "Anonymity",
            "Transborder data flows",
        ],
        "anonymization_standard": "De-identification making re-identification not practically possible",
        "consent_requirement": "Generally required for personal information handling",
        "data_subject_rights": [
            "Right to access",
            "Right to correction",
            "Right to lodge complaints",
        ],
        "penalty": "Up to AUD 2.5M for serious breaches",
    },
    RegulationType.POPIA: {
        "name": "Protection of Personal Information Act (POPIA)",
        "region": "South Africa",
        "effective_date": "2020-07-01",
        "scope": "All organizations processing personal information",
        "key_principles": [
            "Lawfulness",
            "Purpose limitation",
            "Accountability",
            "Openness",
            "Security",
            "Access",
            "Accuracy",
            "Transience",
        ],
        "anonymization_standard": "Complete removal of personal information with no re-identification risk",
        "consent_requirement": "Informed consent required for processing",
        "data_subject_rights": [
            "Right to access",
            "Right to object",
            "Right to rectification",
            "Right to erasure",
        ],
        "penalty": "Up to ZAR 10M or 10% annual revenue",
    },
}
