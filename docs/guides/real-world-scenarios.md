# Real-World Scenarios Guide

**Table of Contents**
1. [Overview](#overview)
2. [E-Commerce Scenario](#e-commerce-scenario)
3. [Healthcare Scenario](#healthcare-scenario)
4. [Financial Scenario](#financial-scenario)
5. [SaaS Scenario](#saas-scenario)
6. [Multi-Tenant Scenario](#multi-tenant-scenario)
7. [Common Patterns](#common-patterns)
8. [Integration Examples](#integration-examples)

---

## Overview

This guide demonstrates Confiture usage in real-world application scenarios. Each scenario is fully implemented with strategy profiles, batch processing, and compliance verification.

---

## E-Commerce Scenario

**Use Case**: Anonymize customer data for analytics while preserving order tracking capability.

### Data Structure

```python
from confiture.scenarios.ecommerce import ECommerceScenario

sample_order = {
    "customer_id": "CUST-001234",          # Preserved - for analytics
    "order_id": "ORD-001234",              # Preserved - for tracking
    "first_name": "John",                  # Anonymized - PII
    "last_name": "Smith",                  # Anonymized - PII
    "email": "john.smith@example.com",     # Redacted - PII
    "phone": "555-123-4567",               # Redacted - PII
    "address": "123 Main Street",          # Masked - PII
    "city": "Springfield",                 # Preserved - non-identifying
    "state": "IL",                         # Preserved - non-identifying
    "country": "US",                       # Preserved - non-identifying
    "card_number": "4532-1234-5678-9010",  # Masked - PCI-DSS
    "card_last4": "9010",                  # Preserved - safe
    "card_type": "Visa",                   # Preserved - non-identifying
    "order_total": 199.99,                 # Preserved - analytics
    "ip_address": "192.168.1.100",         # Masked - tracking
}
```

### Usage

```python
# Single record anonymization
anonymized_order = ECommerceScenario.anonymize(sample_order)

# Batch processing
orders = [sample_order, ...]  # List of orders
anonymized_orders = ECommerceScenario.anonymize_batch(orders)

# Get strategy information
strategies = ECommerceScenario.get_strategy_info()
# Returns mapping of column names to strategy names
```

### Results Example

```python
# Original
{
    "customer_id": "CUST-001234",
    "first_name": "John",
    "email": "john.smith@example.com",
    "order_total": 199.99,
}

# Anonymized
{
    "customer_id": "CUST-001234",          # ✓ Preserved
    "first_name": "Michael",               # ✓ Anonymized
    "email": "[EMAIL]",                    # ✓ Redacted
    "order_total": 199.99,                 # ✓ Preserved
}
```

### Key Features

- ✓ Preserves customer IDs for analytics
- ✓ PCI-DSS compliant credit card handling
- ✓ Deterministic name anonymization
- ✓ IP address masking for privacy
- ✓ Batch processing support

---

## Healthcare Scenario

**Use Case**: HIPAA/GDPR compliant PHI anonymization for research and analytics.

### Data Structure

```python
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

patient_record = {
    "patient_id": "PAT-2024-001",          # Preserved - study ID
    "patient_name": "John Smith",          # Anonymized - PII
    "ssn": "123-45-6789",                  # Redacted - PII
    "date_of_birth": "1965-03-12",         # Masked - PII
    "medical_record_number": "MRN-999888", # Redacted - identifier
    "email": "john@example.com",           # Redacted - PII
    "phone": "555-123-4567",               # Redacted - PII
    "address": "123 Oak Street",           # Masked - PII
    "diagnosis": "E11",                    # Preserved - clinical
    "medication": "Metformin 500mg",       # Preserved - clinical
    "visit_date": "2024-12-15",            # Masked - PII
    "provider_name": "Dr. Sarah Johnson",  # Anonymized - PII
    "facility_name": "St. Mary's Hospital",# Anonymized - PII
    "temperature": 98.6,                   # Preserved - clinical
    "blood_pressure": "120/80",            # Preserved - clinical
}
```

### Multi-Regulation Support

```python
# GDPR (EU)
gdpr_anonymized = HealthcareScenario.anonymize(patient_record, RegulationType.GDPR)

# CCPA (California, USA)
ccpa_anonymized = HealthcareScenario.anonymize(patient_record, RegulationType.CCPA)

# HIPAA (USA - not in enum, use closest)
hipaa_anonymized = HealthcareScenario.anonymize(patient_record, RegulationType.CCPA)

# Multi-region (use GDPR for safest anonymization)
multi_region_anonymized = HealthcareScenario.anonymize(patient_record, RegulationType.GDPR)
```

### Compliance Verification

```python
# Verify compliance
result = HealthcareScenario.verify_compliance(
    original=patient_record,
    anonymized=gdpr_anonymized,
    regulation=RegulationType.GDPR
)

if result["compliant"]:
    print("✓ Data meets GDPR requirements")
else:
    print("✗ Compliance issues:")
    for issue in result["issues"]:
        print(f"  - {issue}")
```

### Batch Processing

```python
# Process multiple patient records
patient_records = [
    {...},  # Patient 1
    {...},  # Patient 2
    # ... more patients
]

# Anonymize for GDPR
anonymized_patients = HealthcareScenario.anonymize_batch(
    patient_records,
    RegulationType.GDPR
)

# Verify each record
for original, anonymized in zip(patient_records, anonymized_patients):
    result = HealthcareScenario.verify_compliance(
        original, anonymized, RegulationType.GDPR
    )
    assert result["compliant"], f"Compliance failed for {original['patient_id']}"
```

### Key Features

- ✓ Multi-region compliance (7 regulations)
- ✓ HIPAA-safe harbor compliance
- ✓ Clinical data preservation
- ✓ Deterministic anonymization
- ✓ Compliance verification
- ✓ Batch processing support

---

## Financial Scenario

**Use Case**: Loan application anonymization for credit risk analysis.

### Data Structure

```python
from confiture.scenarios.financial import FinancialScenario

loan_application = {
    "application_id": "APP-2024-001",      # Preserved - tracking
    "applicant_name": "John Smith",        # Anonymized - PII
    "ssn": "123-45-6789",                  # Redacted - PII
    "email": "john@example.com",           # Redacted - PII
    "phone": "555-123-4567",               # Redacted - PII
    "address": "123 Main St",              # Masked - PII
    "city": "Springfield",                 # Preserved - geographic
    "state": "IL",                         # Preserved - geographic
    "zip": "62701",                        # Preserved - geographic
    "employer_name": "Acme Corp",          # Anonymized - PII
    "employment_address": "456 Corp Blvd", # Masked - PII
    "employment_start_date": "2015-06-01", # Masked - PII
    "annual_income": 75000,                # Preserved - analysis
    "credit_score": 750,                   # Preserved - analysis
    "bank_account": "4532194857632145",    # Hashed - security
    "loan_amount": 250000,                 # Preserved - analysis
    "interest_rate": 4.5,                  # Preserved - analysis
    "loan_term": 30,                       # Preserved - analysis
    "application_date": "2024-11-01",      # Masked - PII
}
```

### Usage

```python
# Anonymize
anonymized_app = FinancialScenario.anonymize(loan_application)

# Batch processing for risk analysis
applications = [loan_application, ...]
anonymized_batch = FinancialScenario.anonymize_batch(applications)

# Perform analysis on anonymized data
total_loan_amount = sum(app["loan_amount"] for app in anonymized_batch)
avg_credit_score = sum(app["credit_score"] for app in anonymized_batch) / len(anonymized_batch)
```

### Key Features

- ✓ Preserves financial metrics for analysis
- ✓ Anonymizes employment information
- ✓ Masks dates to preserve temporal patterns
- ✓ Credit score preservation for analytics
- ✓ Secure account number handling

---

## SaaS Scenario

**Use Case**: User account anonymization while preserving product analytics.

### Data Structure

```python
from confiture.scenarios.saas import SaaSScenario

user_account = {
    "user_id": "USR-789456",               # Preserved - analytics
    "first_name": "John",                  # Anonymized - PII
    "last_name": "Smith",                  # Anonymized - PII
    "email": "john@example.com",           # Redacted - PII
    "phone": "555-123-4567",               # Redacted - PII
    "organization_name": "Acme Inc",       # Masked - PII
    "organization_type": "Enterprise",     # Preserved - classification
    "subscription_tier": "Enterprise",     # Preserved - analytics
    "monthly_cost": 999,                   # Preserved - billing
    "seats": 50,                           # Preserved - usage
    "created_at": "2023-01-15",            # Preserved - analytics
    "last_login": "2024-12-15",            # Masked - PII
    "login_ip": "192.168.1.100",           # Masked - tracking
    "monthly_api_calls": 5000000,          # Preserved - usage
    "storage_gb": 500,                     # Preserved - usage
    "features_enabled": ["analytics", "api", "sso"],  # Preserved - product
}
```

### Usage

```python
# Single account
anonymized_user = SaaSScenario.anonymize(user_account)

# Batch for analytics
users = [user_account, ...]
anonymized_users = SaaSScenario.anonymize_batch(users)

# Analyze product usage
total_api_calls = sum(u["monthly_api_calls"] for u in anonymized_users)
total_storage = sum(u["storage_gb"] for u in anonymized_users)
enterprise_users = [u for u in anonymized_users if u["subscription_tier"] == "Enterprise"]
```

### Key Features

- ✓ Preserves user IDs for cohort analysis
- ✓ Preserves usage metrics
- ✓ Anonymizes personal information
- ✓ Preserves subscription and feature data
- ✓ Supports feature usage analysis

---

## Multi-Tenant Scenario

**Use Case**: Anonymize data across multiple tenants while maintaining isolation.

### Data Structure

```python
from confiture.scenarios.multi_tenant import MultiTenantScenario

tenant_record = {
    "tenant_id": "TENANT-A",               # Preserved - isolation key
    "user_id": "USER-001",                 # Preserved - tenant-scoped ID
    "tenant_name": "Company A",            # Anonymized - PII
    "user_name": "john.smith",            # Anonymized - PII
    "email": "john@companya.com",          # Redacted - PII
    "organization": "Company A",           # Masked - PII
    "department": "Engineering",           # Preserved - org structure
    "created_by_user_id": "USER-ADMIN",   # Preserved - relationships
    "created_by": "admin@companya.com",   # Redacted - PII
    "active_users": 150,                   # Preserved - metrics
    "data_storage": 1024,                  # Preserved - metrics
}
```

### Tenant-Specific Anonymization

```python
# Anonymize with tenant-specific seed
tenant_a_data = {..., "tenant_id": "TENANT-A"}
tenant_b_data = {..., "tenant_id": "TENANT-B"}

# Same user ID produces different results per tenant
anonymized_a = MultiTenantScenario.anonymize(tenant_a_data)
anonymized_b = MultiTenantScenario.anonymize(tenant_b_data)

# Verify isolation
print(anonymized_a["user_name"])  # e.g., "Michael Johnson"
print(anonymized_b["user_name"])  # Different: "Sarah Williams"

# Same tenant produces consistent results
anonymized_a1 = MultiTenantScenario.anonymize(tenant_a_data)
anonymized_a2 = MultiTenantScenario.anonymize(tenant_a_data)
assert anonymized_a1["user_name"] == anonymized_a2["user_name"]  # ✓ Consistent
```

### Batch Processing

```python
# Mix of records from multiple tenants
mixed_records = [
    {..., "tenant_id": "TENANT-A"},
    {..., "tenant_id": "TENANT-A"},
    {..., "tenant_id": "TENANT-B"},
]

# Anonymize maintains per-tenant isolation
anonymized = MultiTenantScenario.anonymize_batch(mixed_records)

# Verify isolation
result = MultiTenantScenario.verify_data_isolation(anonymized, mixed_records)
print(f"Data isolated: {result['isolated']}")
```

### Key Features

- ✓ Per-tenant deterministic seeding
- ✓ Data isolation across tenants
- ✓ Consistent anonymization within tenant
- ✓ Batch processing with tenant awareness
- ✓ Isolation verification

---

## Common Patterns

### Pattern 1: Preserve Identifiers

```python
profile = StrategyProfile(
    columns={
        "id": "preserve",           # Customer ID
        "order_id": "preserve",     # Order ID
        "reference": "preserve",    # Reference number
        "name": "name",             # Anonymize
        "email": "text_redaction",  # Redact
    }
)
# Benefit: Can link back to original records for joins/lookups
```

### Pattern 2: Anonymize PII, Preserve Business Data

```python
profile = StrategyProfile(
    columns={
        # PII - anonymize
        "customer_name": "name",
        "email_address": "text_redaction",
        "phone_number": "text_redaction",
        "physical_address": "address",

        # Business metrics - preserve
        "purchase_amount": "preserve",
        "purchase_frequency": "preserve",
        "customer_lifetime_value": "preserve",
        "churn_risk_score": "preserve",
    }
)
# Benefit: Enable analytics on anonymized data
```

### Pattern 3: Multi-Level Sensitivity

```python
profile = StrategyProfile(
    columns={
        # Highly sensitive - redact
        "ssn": "text_redaction",
        "password_hash": "text_redaction",
        "credit_card": "credit_card",

        # Moderately sensitive - mask
        "birth_date": "date",
        "phone": "text_redaction",
        "address": "address",

        # Low sensitivity - preserve
        "state": "preserve",
        "country": "preserve",
        "age_range": "preserve",
    }
)
```

### Pattern 4: Compliance-Based Anonymization

```python
def get_anonymization_profile(region):
    """Get profile based on region."""
    region_map = {
        "EU": RegulationType.GDPR,
        "US": RegulationType.CCPA,
        "CA": RegulationType.PIPEDA,
    }
    return region_map.get(region, RegulationType.GDPR)

# Usage
user_region = user_data["region"]
regulation = get_anonymization_profile(user_region)
anonymized = HealthcareScenario.anonymize(user_data, regulation)
```

---

## Integration Examples

### Database Integration

```python
import sqlite3
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

def anonymize_database(db_path, output_db_path):
    """Anonymize patient database for research."""
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(output_db_path)

    # Copy schema
    for row in src.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
        dst.execute(row[0])

    # Read and anonymize
    cursor = src.execute("SELECT * FROM patients")
    anonymized_count = 0

    for row in cursor:
        patient = {
            "patient_id": row[0],
            "patient_name": row[1],
            "ssn": row[2],
            # ... map all columns
        }

        anonymized = HealthcareScenario.anonymize(
            patient,
            RegulationType.GDPR
        )

        dst.execute(
            "INSERT INTO patients VALUES (?, ?, ...)",
            (anonymized["patient_id"], anonymized["patient_name"], ...)
        )
        anonymized_count += 1

    dst.commit()
    src.close()
    dst.close()

    print(f"Anonymized {anonymized_count} records")
```

### CSV File Processing

```python
import csv
from confiture.scenarios.ecommerce import ECommerceScenario

def anonymize_csv(input_file, output_file):
    """Anonymize CSV file."""
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)

        writer.writeheader()

        for row in reader:
            anonymized = ECommerceScenario.anonymize(row)
            writer.writerow(anonymized)

    print(f"Anonymized CSV: {input_file} → {output_file}")

# Usage
anonymize_csv("customers.csv", "customers_anonymized.csv")
```

### JSON Export

```python
import json
from confiture.scenarios.financial import FinancialScenario

def anonymize_json(input_file, output_file):
    """Anonymize JSON records."""
    with open(input_file, 'r') as f:
        applications = json.load(f)

    anonymized = FinancialScenario.anonymize_batch(applications)

    with open(output_file, 'w') as f:
        json.dump(anonymized, f, indent=2)

    print(f"Anonymized JSON: {input_file} → {output_file}")

# Usage
anonymize_json("applications.json", "applications_anonymized.json")
```

### REST API Integration

```python
from fastapi import FastAPI, Request
from confiture.scenarios.saas import SaaSScenario

app = FastAPI()

@app.post("/anonymize-user")
async def anonymize_user(request: Request):
    """REST endpoint for user anonymization."""
    user_data = await request.json()

    try:
        anonymized = SaaSScenario.anonymize(user_data)
        return {
            "status": "success",
            "data": anonymized
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/verify-compliance")
async def verify_compliance(request: Request):
    """Verify compliance of anonymization."""
    payload = await request.json()

    result = SaaSScenario.verify_compliance(
        original=payload["original"],
        anonymized=payload["anonymized"],
        regulation=payload.get("regulation")
    )

    return result
```

---

## Best Practices

1. **Always preserve identifiers needed for joins/lookups**
2. **Match strategy to data type** (dates → date strategy, names → name strategy)
3. **Use consistent seeds** for reproducible anonymization
4. **Verify compliance** after anonymization
5. **Test batch processing** with realistic data volumes
6. **Monitor performance** with benchmarking tools
7. **Document column mappings** in profiles
8. **Review anonymized samples** to verify quality

---

## See Also

- [Anonymization Strategy Framework](./anonymization-strategy-framework.md)
- [Multi-Region Compliance](./multi-region-compliance.md)
- [Performance Benchmarking](./performance-benchmarking.md)
- [API Reference](../api/)
