"""Multi-tenant data isolation and anonymization scenario.

Real-world use case: Anonymizing tenant data while ensuring data isolation across
customers in multi-tenant systems.

Data Types:
- Tenant identifiers (preserve for data isolation)
- Tenant names (sensitive - may be identifying)
- User names (PII)
- Email addresses (PII)
- Organization information (sensitive)
- Tenant-specific data (anonymize per tenant config)
- Cross-tenant shared data (preserve for auditing)

Architecture:
- Each tenant has isolated data
- Global seed by tenant ensures consistent hashing across tables
- Tenant metadata preserved for data isolation
- Customer names and PII masked
- Business metrics preserved

Strategy:
- Tenant identifiers: Preserve (data isolation key)
- Tenant names: Mask with initials
- User data: Per-tenant anonymization
- Cross-cutting data: Preserve for auditing
- Relationships: Maintain via deterministic hashing
"""

from confiture.core.anonymization.factory import StrategyFactory, StrategyProfile


class MultiTenantScenario:
    """Multi-tenant data anonymization scenario.

    Demonstrates anonymizing multi-tenant data while maintaining data isolation
    and cross-table consistency through deterministic seeding.

    Example:
        >>> scenario = MultiTenantScenario()
        >>> tenant_a_data = {
        ...     "tenant_id": "TENANT-A",
        ...     "user_id": "USER-001",
        ...     "user_name": "john.smith",
        ...     "text_redaction": "john@companya.com",
        ...     "organization": "Company A",
        ...     "department": "Engineering",
        ... }
        >>> tenant_b_data = {
        ...     "tenant_id": "TENANT-B",
        ...     "user_id": "USER-001",  # Same user ID, different tenant
        ...     "user_name": "jane.doe",
        ...     "text_redaction": "jane@companyb.com",
        ...     "organization": "Company B",
        ...     "department": "Sales",
        ... }
        >>> anon_a = scenario.anonymize(tenant_a_data)
        >>> anon_b = scenario.anonymize(tenant_b_data)
        >>> # Tenant IDs preserved, user data anonymized differently per tenant
    """

    @staticmethod
    def get_profile(tenant_id: str) -> StrategyProfile:
        """Get multi-tenant anonymization profile.

        Uses tenant ID to create deterministic seed for cross-table consistency
        within tenant boundaries.

        Args:
            tenant_id: Tenant identifier for seed generation.

        Returns:
            StrategyProfile configured for multi-tenant data with tenant-specific seed.

        Strategy Mapping:
            - tenant_id: preserve (data isolation key)
            - user_id: preserve (tenant-scoped identifier)
            - user_name: anonymize
            - email: redact
            - organization_name: mask
            - department: preserve (business metadata)
            - created_by: anonymize
            - updated_by: anonymize
            - tenant_metadata: preserve (for auditing)
            - business_metrics: preserve (for analytics)
        """
        # Create deterministic seed from tenant ID
        # This ensures same seed for all records in same tenant
        tenant_seed = hash(tenant_id) & 0x7FFFFFFF  # Positive integer

        return StrategyProfile(
            name=f"multi_tenant_{tenant_id}",
            seed=tenant_seed,  # Tenant-specific seed
            columns={
                # Tenant identifiers - preserve for data isolation
                "tenant_id": "preserve",
                "tenant_uuid": "preserve",
                "account_id": "preserve",
                "workspace_id": "preserve",
                "client_id": "preserve",
                "customer_id": "preserve",

                # User identifiers - preserve (tenant-scoped)
                "user_id": "preserve",
                "user_uuid": "preserve",
                "employee_id": "preserve",
                "member_id": "preserve",

                # User PII - anonymize
                "user_name": "text_redaction",
                "username": "text_redaction",
                "first_name": "name",
                "last_name": "name",
                "full_name": "name",
                "display_name": "name",
                "email": "text_redaction",
                "phone": "text_redaction",
                "phone_number": "text_redaction",

                # Organization/Tenant info - mask names
                "organization_name": "name",
                "tenant_name": "name",
                "company_name": "name",
                "department": "preserve",  # Business metadata
                "team": "preserve",
                "division": "preserve",

                # Address - mask
                "address": "address",
                "city": "preserve",
                "state": "preserve",
                "country": "preserve",

                # Relationships - anonymize names but preserve IDs
                "created_by": "text_redaction",
                "created_by_user_id": "preserve",
                "updated_by": "text_redaction",
                "updated_by_user_id": "preserve",
                "assigned_to": "text_redaction",
                "assigned_to_user_id": "preserve",
                "manager": "text_redaction",
                "manager_id": "preserve",

                # Tenant metadata - preserve
                "tenant_type": "preserve",
                "tenant_status": "preserve",
                "tenant_tier": "preserve",
                "industry": "preserve",
                "region": "preserve",
                "timezone": "preserve",

                # Business metrics - preserve
                "active_users": "preserve",
                "total_users": "preserve",
                "data_storage": "preserve",
                "api_quota": "preserve",
                "monthly_cost": "preserve",
                "annual_contract_value": "preserve",

                # Dates - preserve for audit trail
                "created_at": "preserve",
                "updated_at": "preserve",
                "deleted_at": "preserve",
                "last_login": "date",
                "contract_start": "preserve",
                "contract_end": "preserve",
                "billing_cycle": "preserve",

                # Content/Data - preserve
                "description": "preserve",
                "notes": "preserve",
                "tags": "preserve",
                "status": "preserve",
                "data_classification": "preserve",

                # IP/Technical - mask
                "ip_address": "ip_address",
                "device_id": "preserve",
                "browser": "preserve",

                # Audit fields
                "change_log": "preserve",
                "audit_trail": "preserve",
            },
            defaults="preserve",
        )

    @classmethod
    def create_factory(cls, tenant_id: str) -> StrategyFactory:
        """Create tenant-specific factory for anonymization.

        Args:
            tenant_id: Tenant identifier for isolation.

        Returns:
            Configured StrategyFactory for the tenant.
        """
        profile = cls.get_profile(tenant_id)
        return StrategyFactory(profile)

    @classmethod
    def anonymize(cls, data: dict) -> dict:
        """Anonymize multi-tenant data.

        Extracts tenant ID from data and uses tenant-specific seed for
        deterministic anonymization within tenant boundaries.

        Args:
            data: Record containing tenant_id and other fields.

        Returns:
            Anonymized data with PII masked and tenant isolation maintained.

        Raises:
            ValueError: If tenant_id not in data.

        Example:
            >>> data = {
            ...     "tenant_id": "TENANT-A",
            ...     "user_id": "USER-001",
            ...     "text_redaction": "john@example.com",
            ...     "organization_name": "Company A",
            ... }
            >>> result = MultiTenantScenario.anonymize(data)
            >>> result["tenant_id"]  # Preserved
            'TENANT-A'
            >>> result["text_redaction"]  # Redacted
            '[EMAIL]'
            >>> result["organization_name"]  # Masked
            'CA'
        """
        if "tenant_id" not in data:
            raise ValueError("Data must contain 'tenant_id' field for multi-tenant anonymization")

        tenant_id = data["tenant_id"]
        factory = cls.create_factory(tenant_id)
        return factory.anonymize(data)

    @classmethod
    def anonymize_batch(cls, data_list: list[dict]) -> list[dict]:
        """Anonymize batch of multi-tenant records.

        Creates per-tenant factories to maintain data isolation while
        anonymizing deterministically within each tenant.

        Args:
            data_list: List of records from potentially multiple tenants.

        Returns:
            List of anonymized records maintaining tenant isolation.

        Example:
            >>> data = [
            ...     {"tenant_id": "TENANT-A", "user_id": "U1", ...},
            ...     {"tenant_id": "TENANT-A", "user_id": "U2", ...},
            ...     {"tenant_id": "TENANT-B", "user_id": "U1", ...},
            ... ]
            >>> results = MultiTenantScenario.anonymize_batch(data)
            >>> # TENANT-A records use TENANT-A seed, TENANT-B uses TENANT-B seed
        """
        results = []
        factories_cache = {}

        for record in data_list:
            tenant_id = record.get("tenant_id")
            if not tenant_id:
                raise ValueError("All records must contain 'tenant_id' field")

            # Cache factories by tenant to avoid recreating
            if tenant_id not in factories_cache:
                factories_cache[tenant_id] = cls.create_factory(tenant_id)

            factory = factories_cache[tenant_id]
            results.append(factory.anonymize(record))

        return results

    @classmethod
    def get_strategy_info(cls, tenant_id: str) -> dict:
        """Get strategies for specific tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Dictionary mapping columns to strategy names for tenant.
        """
        profile = cls.get_profile(tenant_id)
        factory = StrategyFactory(profile)
        return factory.list_column_strategies()

    @classmethod
    def verify_data_isolation(
        cls, data_list: list[dict], original_list: list[dict]
    ) -> dict:
        """Verify data isolation across tenants.

        Checks that same user IDs in different tenants produce different
        anonymized results due to tenant-specific seeding.

        Args:
            data_list: Anonymized records.
            original_list: Original records.

        Returns:
            Dictionary with isolation verification results.
        """
        results = {
            "isolated": True,
            "issues": [],
            "cross_tenant_checks": [],
        }

        # Group by tenant
        by_tenant = {}
        for record in data_list:
            tenant = record.get("tenant_id", "UNKNOWN")
            if tenant not in by_tenant:
                by_tenant[tenant] = []
            by_tenant[tenant].append(record)

        # Check isolation: same user_id in different tenants should have different PII
        user_by_tenant = {}
        for i, record in enumerate(original_list):
            tenant = record.get("tenant_id")
            user_id = record.get("user_id")
            key = (user_id,)

            if key not in user_by_tenant:
                user_by_tenant[key] = {}

            user_by_tenant[key][tenant] = {
                "original": record,
                "anonymized": data_list[i],
            }

        # Verify same user in different tenants has different anonymizations
        for (user_id,), tenants_data in user_by_tenant.items():
            if len(tenants_data) > 1:
                anon_values = [
                    tenants_data[t]["anonymized"].get("text_redaction")
                    for t in tenants_data
                ]
                if len(set(anon_values)) != len(anon_values):
                    results["isolated"] = False
                    results["issues"].append(
                        f"User {user_id} has same anonymization in different tenants"
                    )
                else:
                    results["cross_tenant_checks"].append(
                        f"User {user_id}: ✓ Properly isolated across {len(tenants_data)} tenants"
                    )

        return results
