# Multi-Region Data Protection Compliance Guide

**Table of Contents**
1. [Overview](#overview)
2. [Supported Regulations](#supported-regulations)
3. [Compliance Framework](#compliance-framework)
4. [Healthcare Scenario](#healthcare-scenario)
5. [Compliance Verification](#compliance-verification)
6. [Global Deployment](#global-deployment)
7. [Regulation Selection](#regulation-selection)
8. [FAQ](#faq)

---

## Overview

Confiture provides a comprehensive multi-region data protection framework supporting 7 major global regulations. Deploy the same anonymization pipeline across different regions while maintaining compliance with local requirements.

### Supported Regions

| Regulation | Region | Coverage | Effective Date |
|-----------|--------|----------|-----------------|
| **GDPR** | EU/EEA | 27 EU states + EEA | May 25, 2018 |
| **CCPA** | California, USA | California residents | January 1, 2020 |
| **PIPEDA** | Canada | Canadian private sector | January 1, 2004 |
| **LGPD** | Brazil | Brazilian residents | September 18, 2020 |
| **PIPL** | China | Mainland China | November 1, 2021 |
| **Privacy Act** | Australia | Australian citizens | December 21, 1988 |
| **POPIA** | South Africa | South African citizens | July 1, 2020 |

---

## Supported Regulations

### 1. GDPR - General Data Protection Regulation

**Region**: European Union / European Economic Area
**Applies To**: Organizations processing data of EU/EEA residents

**Key Principles**:
- Lawfulness, fairness, transparency
- Purpose limitation
- Data minimization
- Accuracy
- Storage limitation
- Integrity and confidentiality
- Accountability

**Anonymization Standard**: Irreversible de-identification with no re-identification risk

**Data Subject Rights**:
- Right to access
- Right to rectification
- Right to erasure (right to be forgotten)
- Right to restrict processing
- Right to data portability
- Right to object
- Rights related to automated decision making

**Penalties**: Up to €20M or 4% global revenue

**Implementation**:
```python
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

# Anonymize for GDPR
data = {...}
anonymized = HealthcareScenario.anonymize(data, RegulationType.GDPR)

# Verify GDPR compliance
result = HealthcareScenario.verify_compliance(data, anonymized, RegulationType.GDPR)
```

---

### 2. CCPA - California Consumer Privacy Act

**Region**: California, United States
**Applies To**: Businesses collecting data of California residents

**Key Principles**:
- Transparency
- Consumer rights
- Non-discrimination
- Opt-out mechanism

**Anonymization Standard**: Aggregate consumer information where individual identity cannot be determined

**Consumer Rights**:
- Right to know what personal information is collected
- Right to delete personal information
- Right to opt-out of sale/sharing
- Right to non-discrimination for exercising rights

**Penalties**: Up to $7,500 per violation

**Implementation**:
```python
# Anonymize for CCPA
anonymized = HealthcareScenario.anonymize(data, RegulationType.CCPA)

# Verify CCPA compliance
result = HealthcareScenario.verify_compliance(data, anonymized, RegulationType.CCPA)
```

---

### 3. PIPEDA - Personal Information Protection and Electronic Documents Act

**Region**: Canada
**Applies To**: Canadian private sector organizations

**Key Principles**:
- Accountability
- Identifying purposes
- Consent
- Limiting collection
- Limiting use, disclosure
- Accuracy
- Safeguarding
- Openness
- Access
- Challenging compliance

**Anonymization Standard**: Removal of identifying information with minimal re-identification risk

**Data Subject Rights**:
- Right to access
- Right to correct inaccuracies
- Right to challenge non-compliance

**Penalties**: Up to CAD $100,000 per violation

---

### 4. LGPD - Lei Geral de Proteção de Dados

**Region**: Brazil
**Applies To**: All organizations processing data of Brazilian residents

**Key Principles**:
- Respect for privacy
- Self-determination
- Free access
- Quality
- Transparency
- Security
- Prevention
- Non-discrimination
- Accountability

**Anonymization Standard**: Irreversible de-identification making re-identification impossible

**Data Subject Rights**:
- Right to access
- Right to rectification
- Right to deletion
- Right to data portability
- Right to oppose processing

**Penalties**: Up to BRL 50M or 2% annual revenue

---

### 5. PIPL - Personal Information Protection Law

**Region**: China (People's Republic of)
**Applies To**: Entities processing personal information in China

**Key Principles**:
- Legal basis
- Purpose limitation
- Data minimization
- Accuracy and timeliness
- Integrity and confidentiality
- Accountability

**Anonymization Standard**: Irreversible de-identification with no re-identification possibility

**Data Subject Rights**:
- Right to access
- Right to rectification
- Right to deletion
- Right to know processing rules

**Penalties**: Up to CNY 50M or 5% annual revenue

---

### 6. Privacy Act - Australia

**Region**: Australia
**Applies To**: Australian government agencies and private sector organizations

**Key Principles**:
- Collection
- Use and disclosure
- Data quality
- Data security
- Openness
- Access and correction
- Unique identifiers
- Anonymity
- Transborder data flows

**Anonymization Standard**: De-identification making re-identification not practically possible

**Data Subject Rights**:
- Right to access
- Right to correction
- Right to lodge complaints

**Penalties**: Up to AUD 2.5M for serious breaches

---

### 7. POPIA - Protection of Personal Information Act

**Region**: South Africa
**Applies To**: All organizations processing personal information

**Key Principles**:
- Lawfulness
- Purpose limitation
- Accountability
- Openness
- Security
- Access
- Accuracy
- Transience

**Anonymization Standard**: Complete removal of personal information with no re-identification risk

**Data Subject Rights**:
- Right to access
- Right to object
- Right to rectification
- Right to erasure

**Penalties**: Up to ZAR 10M or 10% annual revenue

---

## Compliance Framework

### Core Components

#### 1. RegulationType Enum

```python
from confiture.scenarios.compliance import RegulationType

# Access regulation types
RegulationType.GDPR
RegulationType.CCPA
RegulationType.PIPEDA
RegulationType.LGPD
RegulationType.PIPL
RegulationType.PRIVACY_ACT
RegulationType.POPIA
```

#### 2. PersonalDataCategories

Defines 15 personal data categories across regulations:

```python
from confiture.scenarios.compliance import PersonalDataCategories

# Check which regulations apply to a category
direct_ids = PersonalDataCategories.DIRECT_IDENTIFIERS
for regulation in [RegulationType.GDPR, RegulationType.CCPA]:
    applies = direct_ids.applies_to(regulation)
    print(f"{regulation.value}: {applies}")
```

**Categories**:
1. Direct Identifiers (names, emails, phones)
2. Quasi-Identifiers (age, zip code, employment date)
3. Health Data (diagnosis, medication)
4. Genetic Data (DNA profiles, ancestry)
5. Biometric Data (fingerprints, facial recognition)
6. Financial Data (bank accounts, salaries)
7. Location Data (IP address, GPS)
8. Communication Data (emails, call logs)
9. Employment Data (employer name, job title)
10. Education Data (school, grades)
11. Racial/Ethnic Data (ethnicity, race)
12. Political Affiliation (party, voting)
13. Religious/Philosophical Beliefs
14. Trade Union Membership
15. Children's Data

#### 3. ComplianceVerifier

Verifies anonymization meets regulation requirements:

```python
from confiture.scenarios.compliance import ComplianceVerifier, RegulationType

verifier = ComplianceVerifier(RegulationType.GDPR)

# Verify anonymization
original = {...}
anonymized = {...}
result = verifier.verify_anonymization(original, anonymized)

print(f"Compliant: {result['compliant']}")
print(f"Issues: {result['issues']}")
print(f"Masked fields: {result['masked_fields']}")
```

#### 4. Regulation Guidance

Detailed guidance for each regulation:

```python
from confiture.scenarios.compliance import REGULATION_GUIDANCE, RegulationType

guidance = REGULATION_GUIDANCE[RegulationType.GDPR]

# Access guidance data
name = guidance["name"]                      # "General Data Protection Regulation (GDPR)"
region = guidance["region"]                  # "European Union / European Economic Area"
principles = guidance["key_principles"]      # List of 7 principles
rights = guidance["data_subject_rights"]     # List of 7 rights
penalties = guidance["penalty"]              # "Up to €20M or 4% global revenue"
```

---

## Healthcare Scenario

### Basic Usage

```python
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

# Sample healthcare data
data = {
    "patient_id": "PAT-2024-001",
    "patient_name": "John Smith",
    "ssn": "123-45-6789",
    "email": "john@example.com",
    "date_of_birth": "1965-03-12",
    "diagnosis": "E11",
    "medication": "Metformin 500mg",
    "visit_date": "2024-12-15",
    "provider_name": "Dr. Sarah Johnson",
    "facility_name": "St. Mary's Hospital",
}

# Anonymize for GDPR (default)
anonymized = HealthcareScenario.anonymize(data)

# Anonymize for specific regulation
anonymized_ccpa = HealthcareScenario.anonymize(data, RegulationType.CCPA)
anonymized_gdpr = HealthcareScenario.anonymize(data, RegulationType.GDPR)
```

### Batch Processing

```python
# Process multiple records
patient_records = [
    {...},
    {...},
    {...},
]

# Anonymize batch for specific regulation
anonymized_batch = HealthcareScenario.anonymize_batch(
    patient_records,
    RegulationType.GDPR
)
```

### Compliance Verification

```python
# Verify compliance
result = HealthcareScenario.verify_compliance(
    original=data,
    anonymized=anonymized,
    regulation=RegulationType.GDPR
)

# Check result
print(f"Compliant: {result['compliant']}")
print(f"Masked fields: {result['masked_fields']}")
print(f"Preserved fields: {result['preserved_fields']}")
print(f"Issues: {result['issues']}")
```

### Compliance Requirements

```python
# Get regulation-specific requirements
requirements = HealthcareScenario.get_compliance_requirements(RegulationType.GDPR)

print(f"Regulation: {requirements['regulation']}")
print(f"Total categories: {requirements['total_categories']}")
print(f"Requires anonymization: {requirements['requires_anonymization']}")
print(f"Requires explicit consent: {requirements['requires_explicit_consent']}")
```

---

## Compliance Verification

### Verification Results

```python
result = HealthcareScenario.verify_compliance(original, anonymized, regulation)

# Result structure:
{
    "compliant": True,                      # Boolean compliance status
    "regulation": "gdpr",                   # Regulation checked
    "masked_fields": ["name", "email"],     # Fields anonymized
    "preserved_fields": ["id", "diagnosis"], # Fields kept unchanged
    "issues": [],                           # Compliance issues found
    "masked_count": 2,                      # Number of masked fields
    "preserved_count": 2,                   # Number of preserved fields
}
```

### Interpreting Results

```python
# Fully compliant
if result["compliant"] and len(result["issues"]) == 0:
    print("✅ Data anonymization meets regulation requirements")

# Has issues
if result["issues"]:
    for issue in result["issues"]:
        print(f"⚠️ {issue}")

# No PII masked
if result["masked_count"] == 0:
    print("⚠️ Warning: No PII fields were masked")
```

### Per-Field Verification

```python
# Check specific fields
sensitive_fields = ["name", "email", "ssn", "medical_record_number"]

for field in sensitive_fields:
    if field in result["masked_fields"]:
        print(f"✅ {field} was anonymized")
    else:
        print(f"❌ {field} was NOT anonymized")
```

---

## Global Deployment

### Single Region Deployment

```python
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

# EU deployment - GDPR only
class EUAnonymizer:
    def anonymize(self, data):
        return HealthcareScenario.anonymize(data, RegulationType.GDPR)

# US deployment - CCPA only
class USAnonymizer:
    def anonymize(self, data):
        return HealthcareScenario.anonymize(data, RegulationType.CCPA)
```

### Multi-Region Deployment

```python
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

class GlobalAnonymizer:
    """Handle anonymization for multiple regions."""

    REGION_REGULATIONS = {
        "EU": RegulationType.GDPR,
        "US": RegulationType.CCPA,
        "CA": RegulationType.PIPEDA,
        "BR": RegulationType.LGPD,
        "CN": RegulationType.PIPL,
        "AU": RegulationType.PRIVACY_ACT,
        "ZA": RegulationType.POPIA,
    }

    def anonymize(self, data, region):
        """Anonymize data for specific region."""
        regulation = self.REGION_REGULATIONS.get(region)
        if not regulation:
            raise ValueError(f"Unknown region: {region}")

        return HealthcareScenario.anonymize(data, regulation)

    def verify(self, original, anonymized, region):
        """Verify compliance for region."""
        regulation = self.REGION_REGULATIONS[region]
        return HealthcareScenario.verify_compliance(
            original, anonymized, regulation
        )

# Usage
anonymizer = GlobalAnonymizer()

# EU data
eu_data = {...}
eu_anonymized = anonymizer.anonymize(eu_data, "EU")
eu_result = anonymizer.verify(eu_data, eu_anonymized, "EU")

# US data
us_data = {...}
us_anonymized = anonymizer.anonymize(us_data, "US")
us_result = anonymizer.verify(us_data, us_anonymized, "US")
```

### Database Anonymization Pipeline

```python
import sqlite3
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

def anonymize_patient_table(db_path, region):
    """Anonymize patient table for region."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get regulation for region
    region_map = {
        "EU": RegulationType.GDPR,
        "US": RegulationType.CCPA,
        # ... more regions
    }
    regulation = region_map[region]

    # Read and anonymize
    cursor.execute("SELECT * FROM patients")
    patients = cursor.fetchall()

    anonymized_patients = []
    for patient in patients:
        patient_dict = {
            "patient_id": patient[0],
            "patient_name": patient[1],
            "ssn": patient[2],
            # ... more fields
        }
        anon = HealthcareScenario.anonymize(patient_dict, regulation)
        anonymized_patients.append(anon)

    # Save anonymized data
    for anon in anonymized_patients:
        cursor.execute(
            "INSERT INTO patients_anonymized VALUES (?, ?, ...)",
            (anon["patient_id"], anon["patient_name"], anon["ssn"], ...)
        )

    conn.commit()
    conn.close()
```

---

## Regulation Selection

### Decision Matrix

| Scenario | Regulation | Reason |
|----------|-----------|--------|
| EU customers | GDPR | Mandatory for EU residents |
| California customers | CCPA | Mandatory for California residents |
| Canadian data | PIPEDA | Mandatory for Canada |
| Brazilian data | LGPD | Mandatory for Brazil |
| China operations | PIPL | Mandatory for China |
| Australian data | Privacy Act | Mandatory for Australia |
| South Africa data | POPIA | Mandatory for South Africa |
| Multi-region | GDPR | Most restrictive, covers all regions safely |

### Selecting Strictest Regulation

For organizations operating across multiple regions, use the strictest regulation:

```python
from confiture.scenarios.compliance import RegulationType

# Strictness order (most to least strict):
# 1. GDPR - Most comprehensive
# 2. LGPD - Very comprehensive
# 3. PIPL - Comprehensive
# 4. Privacy Act - Comprehensive
# 5. POPIA - Comprehensive
# 6. PIPEDA - Comprehensive
# 7. CCPA - Least comprehensive

# For multi-region, use GDPR
regulation = RegulationType.GDPR  # Safe for all regions
```

### Custom Regulation Selection

```python
def get_applicable_regulations(user_data):
    """Get applicable regulations based on user location."""
    user_regions = user_data["regions"]  # List of regions user is in

    regulations = set()
    region_map = {
        "EU": RegulationType.GDPR,
        "US": RegulationType.CCPA,
        "CA": RegulationType.PIPEDA,
        # ... more mappings
    }

    for region in user_regions:
        if region in region_map:
            regulations.add(region_map[region])

    # Return most restrictive
    return max(regulations, key=lambda r: get_strictness_score(r))
```

---

## FAQ

### Q: Do I need to support all 7 regulations?

**A**: No. Support only the regulations applicable to your users' regions. Use GDPR as a safe default for global operations.

### Q: Can I use GDPR for non-EU data?

**A**: Yes. GDPR is the most comprehensive regulation and provides safe anonymization for any region. However, for compliance certification, use the applicable regulation for the user's location.

### Q: How do I know which regulation applies?

**A**: Use the user's location/jurisdiction. If users are in multiple regions, use the most restrictive regulation.

| User Location | Applicable Regulation |
|---------------|----------------------|
| EU/EEA | GDPR |
| California | CCPA |
| Canada | PIPEDA |
| Brazil | LGPD |
| China | PIPL |
| Australia | Privacy Act |
| South Africa | POPIA |
| Multiple regions | Use strictest (GDPR recommended) |

### Q: What's the difference between anonymization and pseudonymization?

**A**:
- **Anonymization**: Irreversible removal of PII. User cannot be re-identified.
- **Pseudonymization**: Replacement with pseudonym. User could theoretically be re-identified with additional data.

Confiture provides anonymization (irreversible).

### Q: How do I handle cross-border data transfers?

**A**:
1. Anonymize data according to destination regulation
2. GDPR allows cross-border transfer of anonymized data
3. For pseudonymized data, use Standard Contractual Clauses (SCCs)

```python
# Transfer EU data to US (CCPA compliant)
us_anonymized = HealthcareScenario.anonymize(eu_data, RegulationType.CCPA)
# Safe to transfer: anonymized data is not regulated
```

### Q: Can I change regulations for existing data?

**A**: Yes, re-anonymize using new regulation:

```python
# Original anonymization for GDPR
gdpr_anonymized = HealthcareScenario.anonymize(original, RegulationType.GDPR)

# Later, anonymize for CCPA
ccpa_anonymized = HealthcareScenario.anonymize(original, RegulationType.CCPA)

# Note: Always anonymize from original data, not from previously anonymized data
```

### Q: Is seed-based anonymization reversible?

**A**: No. Even with the seed, the anonymization is mathematically irreversible. The seed only ensures reproducibility (same input + same seed = same output).

### Q: How do I audit compliance?

**A**: Use compliance verification:

```python
# Verify compliance for audit trail
result = HealthcareScenario.verify_compliance(original, anonymized, regulation)

# Log compliance result
audit_log = {
    "timestamp": datetime.now(),
    "regulation": result["regulation"],
    "compliant": result["compliant"],
    "masked_fields": result["masked_fields"],
    "issues": result["issues"],
}
# Save to compliance audit log
```

### Q: What if a field doesn't match any strategy?

**A**: Use the `defaults` setting in profile:

```python
profile = StrategyProfile(
    columns={
        "known_field": "name",
    },
    defaults="preserve"  # Unknown fields are preserved
)
```

---

## See Also

- [Anonymization Strategy Framework](./anonymization-strategy-framework.md)
- [Performance Benchmarking](./performance-benchmarking.md)
- [Real-World Scenarios](./real-world-scenarios.md)
- [API Reference](../api/)
