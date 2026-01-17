"""Performance benchmarking tests for anonymization strategies.

Tests:
1. Individual strategy performance
2. Batch anonymization scaling
3. Multi-regulation compliance overhead
4. Scalability analysis
"""

from confiture.core.anonymization.benchmarking import (
    Benchmarker,
    PerformanceTracker,
    ScalabilityTester,
)
from confiture.core.anonymization.factory import StrategyFactory, StrategyProfile
from confiture.core.anonymization.registry import StrategyRegistry
from confiture.scenarios.compliance import RegulationType
from confiture.scenarios.ecommerce import ECommerceScenario
from confiture.scenarios.healthcare import HealthcareScenario


class TestStrategyPerformance:
    """Benchmark individual strategy performance."""

    def test_name_masking_performance(self):
        """Benchmark name masking strategy."""
        benchmarker = Benchmarker()
        strategy = StrategyRegistry.get("name", {"seed": 42})

        test_values = [
            "John Smith",
            "Jane Doe",
            "Michael Johnson",
            "Sarah Williams",
            "Robert Brown",
        ]

        result = benchmarker.benchmark_strategy(strategy, test_values, iterations=100)

        assert result.avg_time_ms > 0
        assert result.ops_per_second > 100  # Should be fast
        assert result.max_time_ms < 50  # Should be under 50ms max

    def test_date_masking_performance(self):
        """Benchmark date masking strategy."""
        benchmarker = Benchmarker()
        strategy = StrategyRegistry.get("date", {"seed": 42})

        test_values = [
            "2024-01-15",
            "1990-12-25",
            "2000-06-30",
            "1985-03-10",
            "2020-11-20",
        ]

        result = benchmarker.benchmark_strategy(strategy, test_values, iterations=100)

        assert result.avg_time_ms > 0
        assert result.ops_per_second > 100

    def test_credit_card_performance(self):
        """Benchmark credit card masking strategy."""
        benchmarker = Benchmarker()
        strategy = StrategyRegistry.get("credit_card", {"seed": 42})

        test_values = [
            "4532-1234-5678-9010",
            "5425-2334-3010-9903",
            "3782-822463-10005",
        ]

        result = benchmarker.benchmark_strategy(strategy, test_values, iterations=50)

        assert result.avg_time_ms > 0
        assert result.ops_per_second > 10  # May be slower due to Luhn validation

    def test_ip_address_performance(self):
        """Benchmark IP address masking strategy."""
        benchmarker = Benchmarker()
        strategy = StrategyRegistry.get("ip_address", {"seed": 42})

        test_values = [
            "192.168.1.100",
            "10.0.0.1",
            "172.16.0.1",
            "8.8.8.8",
            "1.1.1.1",
        ]

        result = benchmarker.benchmark_strategy(strategy, test_values, iterations=100)

        assert result.avg_time_ms > 0
        assert result.ops_per_second > 100

    def test_text_redaction_performance(self):
        """Benchmark text redaction strategy."""
        benchmarker = Benchmarker()
        strategy = StrategyRegistry.get("text_redaction", {"seed": 42})

        test_values = [
            "john@example.com",
            "jane.doe@company.com",
            "contact@website.org",
        ]

        result = benchmarker.benchmark_strategy(strategy, test_values, iterations=100)

        assert result.avg_time_ms > 0
        assert result.ops_per_second > 100

    def test_preserve_strategy_performance(self):
        """Benchmark preserve strategy (should be fastest)."""
        benchmarker = Benchmarker()
        strategy = StrategyRegistry.get("preserve", {"seed": 42})

        test_values = ["value1", "value2", "value3", "value4", "value5"]

        result = benchmarker.benchmark_strategy(strategy, test_values, iterations=1000)

        assert result.avg_time_ms > 0
        assert result.ops_per_second > 1000  # Should be very fast

    def test_strategy_comparison(self):
        """Compare performance across strategies."""
        benchmarker = Benchmarker()

        strategies = [
            ("name", {"seed": 42}),
            ("date", {"seed": 42}),
            ("preserve", {"seed": 42}),
            ("ip_address", {"seed": 42}),
        ]

        test_values = ["test_value_1", "test_value_2", "test_value_3"]

        results = {}
        for strategy_name, config in strategies:
            strategy = StrategyRegistry.get(strategy_name, config)
            result = benchmarker.benchmark_strategy(strategy, test_values, iterations=100)
            results[strategy_name] = result

        # Preserve should be fastest
        preserve_time = results["preserve"].avg_time_ms
        for name, result in results.items():
            if name != "preserve":
                assert result.avg_time_ms >= preserve_time


class TestBatchAnonymizationPerformance:
    """Benchmark batch anonymization operations."""

    def test_ecommerce_batch_performance(self):
        """Benchmark ecommerce scenario batch anonymization."""
        benchmarker = Benchmarker()

        [
            {
                "customer_id": f"CUST-{i:06d}",
                "order_id": f"ORD-{i:06d}",
                "first_name": f"Customer {i}",
                "last_name": "Smith",
                "email": f"customer{i}@example.com",
                "phone": "555-1234",
                "address": f"{i} Main Street",
                "order_total": 100 + i,
            }
            for i in range(100)
        ]

        def anonymize_batch(data):
            return ECommerceScenario.anonymize_batch(data)

        results = benchmarker.benchmark_batch_anonymization(
            anonymize_batch, batch_sizes=[10, 50, 100]
        )

        assert len(results) == 3
        for _batch_size, result in results.items():
            assert result.total_time_ms > 0
            assert result.ops_per_second > 0

    def test_healthcare_batch_performance(self):
        """Benchmark healthcare scenario batch anonymization."""
        benchmarker = Benchmarker()

        [
            {
                "patient_id": f"PAT-{i:06d}",
                "patient_name": f"Patient {i}",
                "ssn": f"{100 + i:03d}-{20 + i:02d}-{i:04d}",
                "diagnosis": "E11",
                "medication": "Metformin",
            }
            for i in range(50)
        ]

        def anonymize_batch(data):
            return HealthcareScenario.anonymize_batch(data, RegulationType.GDPR)

        results = benchmarker.benchmark_batch_anonymization(
            anonymize_batch, batch_sizes=[10, 25, 50]
        )

        assert len(results) == 3
        for _batch_size, result in results.items():
            assert result.total_time_ms > 0


class TestCompliancePerformanceOverhead:
    """Benchmark compliance verification overhead."""

    def test_gdpr_compliance_overhead(self):
        """Measure GDPR compliance verification overhead."""
        tracker = PerformanceTracker()

        sample_data = {
            "patient_id": "PAT-001",
            "patient_name": "John Smith",
            "ssn": "123-45-6789",
            "diagnosis": "E11",
        }

        # Measure anonymization time
        import time

        start = time.perf_counter()
        for _ in range(100):
            _ = HealthcareScenario.anonymize(sample_data, RegulationType.GDPR)
        anon_time = (time.perf_counter() - start) * 10  # Average per operation

        tracker.record("GDPR Anonymization", anon_time)

        # Measure compliance verification time
        anonymized = HealthcareScenario.anonymize(sample_data, RegulationType.GDPR)

        start = time.perf_counter()
        for _ in range(100):
            _ = HealthcareScenario.verify_compliance(sample_data, anonymized, RegulationType.GDPR)
        verify_time = (time.perf_counter() - start) * 10

        tracker.record("GDPR Compliance Verification", verify_time)

        # Compliance verification should add minimal overhead
        assert verify_time < anon_time * 2

    def test_multi_regulation_overhead(self):
        """Measure overhead of checking multiple regulations."""
        tracker = PerformanceTracker()

        sample_data = {
            "patient_id": "PAT-001",
            "patient_name": "John Smith",
            "ssn": "123-45-6789",
        }

        regulations = [
            RegulationType.GDPR,
            RegulationType.CCPA,
            RegulationType.PIPEDA,
        ]

        import time

        for regulation in regulations:
            start = time.perf_counter()
            for _ in range(50):
                _ = HealthcareScenario.anonymize(sample_data, regulation)
            elapsed = (time.perf_counter() - start) * 20  # Average per operation

            tracker.record(f"Anonymization ({regulation.value.upper()})", elapsed)

        # All regulations should have similar performance
        stats = tracker.get_stats(f"Anonymization ({regulations[0].value.upper()})")
        assert stats["avg_ms"] > 0


class TestScalability:
    """Test scalability with varying data sizes."""

    def test_field_count_scalability(self):
        """Test anonymization scalability with increasing field count."""
        factory = StrategyFactory(ECommerceScenario.get_profile())

        def anonymize_func(record):
            return factory.anonymize(record)

        tester = ScalabilityTester(anonymize_func)

        # Test with 5 to 50 fields
        results = tester.test_scaling((5, 50), step=5)

        assert len(results) == 10
        assert all(time_ms > 0 for time_ms in results.values())

        # Time should increase roughly linearly with field count
        # (not exponentially)
        max_time = max(results.values())
        min_time = min(results.values())
        ratio = max_time / min_time

        # Should be less than 20x increase for 10x field increase
        assert ratio < 20

    def test_batch_size_scalability(self):
        """Test batch anonymization scalability."""
        import time

        factory = StrategyFactory(HealthcareScenario.get_profile(RegulationType.GDPR))

        results = {}

        for batch_size in [10, 50, 100, 500]:
            test_data = [
                {
                    "patient_id": f"PAT-{i:06d}",
                    "patient_name": f"Patient {i}",
                    "ssn": f"{100 + i:03d}-{20 + i:02d}-{i:04d}",
                    "diagnosis": "E11",
                }
                for i in range(batch_size)
            ]

            start = time.perf_counter()
            [factory.anonymize(record) for record in test_data]
            elapsed_ms = (time.perf_counter() - start) * 1000

            results[batch_size] = elapsed_ms

        # Time should increase linearly with batch size
        # Compare 10 vs 100 (10x increase)
        ratio = results[100] / results[10]
        assert 5 < ratio < 20  # Should be roughly 10x


class TestMemoryFootprint:
    """Test memory usage of benchmarking operations."""

    def test_strategy_memory_usage(self):
        """Measure memory footprint of strategies."""
        Benchmarker()

        strategies = [
            ("name", {"seed": 42}),
            ("date", {"seed": 42}),
            ("preserve", {"seed": 42}),
        ]

        results = {}

        for strategy_name, config in strategies:
            strategy = StrategyRegistry.get(strategy_name, config)
            memory_kb = strategy.__sizeof__() / 1024.0
            results[strategy_name] = memory_kb

        # All strategies should be reasonably small
        for _name, memory in results.items():
            assert memory < 100  # Less than 100KB

    def test_factory_memory_usage(self):
        """Measure memory footprint of factory."""
        import sys

        factory = StrategyFactory(ECommerceScenario.get_profile())

        memory_kb = sys.getsizeof(factory) / 1024.0

        # Factory should be relatively small
        assert memory_kb < 500


class TestPerformanceRegression:
    """Test for performance regressions."""

    def test_anonymization_consistency(self):
        """Verify anonymization produces consistent results."""
        data = {
            "name": "John Smith",
            "email": "john@example.com",
        }

        profile = StrategyProfile(
            name="test",
            seed=42,
            columns={"name": "name", "email": "text_redaction"},
        )

        factory1 = StrategyFactory(profile)
        factory2 = StrategyFactory(profile)

        result1 = factory1.anonymize(data)
        result2 = factory2.anonymize(data)

        # Same seed should produce same results
        assert result1["name"] == result2["name"]
        assert result1["email"] == result2["email"]

    def test_deterministic_performance(self):
        """Verify performance is deterministic."""
        import time

        factory = StrategyFactory(ECommerceScenario.get_profile())

        sample_data = {
            "customer_id": "CUST-001",
            "first_name": "John",
            "email": "john@example.com",
        }

        # Measure 3 separate runs
        times = []

        for _ in range(3):
            times_run = []
            for _ in range(100):
                start = time.perf_counter()
                _ = factory.anonymize(sample_data)
                elapsed_ms = (time.perf_counter() - start) * 1000
                times_run.append(elapsed_ms)

            avg_time = sum(times_run) / len(times_run)
            times.append(avg_time)

        # Average times should be similar across runs
        # (within 50% variation)
        max_time = max(times)
        min_time = min(times)
        ratio = max_time / min_time

        assert ratio < 1.5  # Should vary less than 50%
