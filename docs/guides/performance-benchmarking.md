# Performance Benchmarking Guide

**Table of Contents**
1. [Overview](#overview)
2. [Benchmarking Tools](#benchmarking-tools)
3. [Strategy Performance](#strategy-performance)
4. [Batch Performance](#batch-performance)
5. [Compliance Overhead](#compliance-overhead)
6. [Scalability Analysis](#scalability-analysis)
7. [Optimization Tips](#optimization-tips)
8. [Performance Metrics](#performance-metrics)

---

## Overview

This guide covers performance measurement and optimization for Confiture anonymization operations.

### Key Metrics

- **Throughput**: Operations per second (ops/sec)
- **Latency**: Time per operation (milliseconds)
- **Memory**: RAM usage (kilobytes)
- **Scalability**: Performance with growing data sizes

---

## Benchmarking Tools

### Benchmarker Class

```python
from confiture.core.anonymization.benchmarking import Benchmarker
from confiture.core.anonymization.registry import StrategyRegistry

benchmarker = Benchmarker(verbose=True)

# Benchmark strategy
strategy = StrategyRegistry.get("name", {"seed": 42})
test_values = ["John Smith", "Jane Doe", "Bob Johnson"]

result = benchmarker.benchmark_strategy(strategy, test_values, iterations=1000)

# Result provides:
# - avg_time_ms: Average time per operation
# - ops_per_second: Throughput
# - min_time_ms: Best case
# - max_time_ms: Worst case
# - memory_estimate_kb: Memory footprint

print(result)
# Output: NameMaskingStrategy | Iterations: 1000 | Avg: 0.5234ms | Ops/sec: 1910.6
```

### PerformanceTracker Class

```python
from confiture.core.anonymization.benchmarking import PerformanceTracker
import time

tracker = PerformanceTracker()

# Record multiple operations
for _ in range(100):
    start = time.perf_counter()
    # ... perform operation ...
    elapsed_ms = (time.perf_counter() - start) * 1000
    tracker.record("my_operation", elapsed_ms)

# Get statistics
stats = tracker.get_stats("my_operation")
print(stats)
# Output: {'count': 100, 'total_ms': 52.3, 'avg_ms': 0.523, 'min_ms': 0.4, 'max_ms': 1.2}

# Get report
print(tracker.get_report())
```

### ScalabilityTester Class

```python
from confiture.core.anonymization.benchmarking import ScalabilityTester
from confiture.core.anonymization.factory import StrategyFactory
from confiture.scenarios.healthcare import HealthcareScenario

factory = StrategyFactory(HealthcareScenario.get_profile())
tester = ScalabilityTester(factory.anonymize)

# Test with increasing field counts
results = tester.test_scaling((5, 50), step=5)
# Returns: {5: 0.21ms, 10: 0.42ms, 15: 0.63ms, ...}

# Analyze complexity
analysis = tester.analyze_complexity(results)
print(analysis)
# Output: Estimated Complexity: O(n) - Linear
```

---

## Strategy Performance

### Performance Ranking

**Fastest to Slowest**:

1. **Preserve** (~2000+ ops/sec)
   - No-op strategy
   - Returns value unchanged

2. **Name/Date/Address** (~500-1000 ops/sec)
   - Simple randomization
   - Database lookup + formatting

3. **Text Redaction** (~100-500 ops/sec)
   - Pattern matching
   - Regex compilation/matching

4. **IP Address** (~300-800 ops/sec)
   - IP parsing
   - Subnet preservation

5. **Credit Card** (~50-200 ops/sec)
   - Luhn checksum validation
   - Multiple validations per operation

### Benchmarking Individual Strategies

```python
from confiture.core.anonymization.benchmarking import Benchmarker
from confiture.core.anonymization.registry import StrategyRegistry

benchmarker = Benchmarker()

strategies = {
    "name": ["John Smith", "Jane Doe", "Bob Johnson"],
    "date": ["1990-05-15", "2000-06-30", "1985-03-10"],
    "preserve": ["value1", "value2", "value3"],
    "text_redaction": ["john@example.com", "jane@example.com"],
    "ip_address": ["192.168.1.100", "10.0.0.1", "172.16.0.1"],
    "credit_card": ["4532-1234-5678-9010", "5425-2334-3010-9903"],
}

results = {}
for strategy_name, test_values in strategies.items():
    strategy = StrategyRegistry.get(strategy_name, {"seed": 42})
    result = benchmarker.benchmark_strategy(strategy, test_values, iterations=100)
    results[strategy_name] = result

# Print summary
print(benchmarker.get_summary())
```

### Strategy Comparison

```python
# Compare two strategies
baseline = benchmarker.benchmark_strategy(strategy1, values, iterations=1000)
candidate = benchmarker.benchmark_strategy(strategy2, values, iterations=1000)

comparison = benchmarker.compare_performance(baseline, candidate)
print(comparison)

# Check for regression
if comparison.regression:
    print(f"⚠️ Performance regression detected: {comparison.speedup:.2f}x slower")
```

---

## Batch Performance

### Batch Anonymization

```python
from confiture.core.anonymization.benchmarking import Benchmarker
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

benchmarker = Benchmarker()

def anonymize_batch(data):
    return HealthcareScenario.anonymize_batch(data, RegulationType.GDPR)

# Test different batch sizes
results = benchmarker.benchmark_batch_anonymization(
    anonymize_batch,
    batch_sizes=[10, 50, 100, 500, 1000]
)

# Results: {10: BenchmarkResult(...), 50: BenchmarkResult(...), ...}

# Analyze scaling
for batch_size, result in results.items():
    print(f"Batch {batch_size}: {result.ops_per_second:.1f} ops/sec")
```

### Expected Performance

- **Small batches (10-50 items)**: 1-5ms per record
- **Medium batches (100-500 items)**: 0.5-2ms per record
- **Large batches (1000+ items)**: 0.3-1ms per record

---

## Compliance Overhead

### Measuring Compliance Verification Cost

```python
from confiture.core.anonymization.benchmarking import PerformanceTracker
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType
import time

tracker = PerformanceTracker()

data = {
    "patient_id": "PAT-001",
    "patient_name": "John Smith",
    "ssn": "123-45-6789",
}

# Measure anonymization
for _ in range(100):
    start = time.perf_counter()
    anonymized = HealthcareScenario.anonymize(data, RegulationType.GDPR)
    elapsed_ms = (time.perf_counter() - start) * 1000
    tracker.record("Anonymization", elapsed_ms)

# Measure compliance verification
for _ in range(100):
    start = time.perf_counter()
    result = HealthcareScenario.verify_compliance(data, anonymized, RegulationType.GDPR)
    elapsed_ms = (time.perf_counter() - start) * 1000
    tracker.record("Compliance Verification", elapsed_ms)

# Get report
print(tracker.get_report())

# Typical results:
# Anonymization: ~0.5-1.0ms
# Compliance Verification: ~0.2-0.4ms (20-40% overhead)
```

### Multi-Regulation Overhead

```python
from confiture.scenarios.compliance import RegulationType

regulations = [
    RegulationType.GDPR,
    RegulationType.CCPA,
    RegulationType.PIPEDA,
]

for regulation in regulations:
    tracker.record(f"Anonymization ({regulation.value})", anonymization_time)

# Expected: Similar performance across all regulations
# (difference < 10%)
```

---

## Scalability Analysis

### Field Count Scalability

```python
from confiture.core.anonymization.benchmarking import ScalabilityTester
from confiture.core.anonymization.factory import StrategyFactory
from confiture.scenarios.ecommerce import ECommerceScenario

factory = StrategyFactory(ECommerceScenario.get_profile())
tester = ScalabilityTester(factory.anonymize)

# Test with 5-100 fields
results = tester.test_scaling((5, 100), step=10)

# Analyze complexity
analysis = tester.analyze_complexity(results)
print(analysis)

# Expected: Linear O(n) complexity
# Time should roughly double when fields double
```

### Batch Size Scalability

```python
import time
from confiture.core.anonymization.factory import StrategyFactory
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

factory = StrategyFactory(
    HealthcareScenario.get_profile(RegulationType.GDPR)
)

results = {}
for batch_size in [10, 100, 1000]:
    data = [
        {
            "patient_id": f"PAT-{i:06d}",
            "patient_name": f"Patient {i}",
            "ssn": f"{100+i:03d}-{20+i:02d}-{i:04d}",
        }
        for i in range(batch_size)
    ]

    start = time.perf_counter()
    anonymized = [factory.anonymize(record) for record in data]
    elapsed_ms = (time.perf_counter() - start) * 1000

    results[batch_size] = elapsed_ms

# Print results
for batch_size, elapsed_ms in results.items():
    per_record_ms = elapsed_ms / batch_size
    print(f"Batch {batch_size}: {elapsed_ms:.2f}ms total, {per_record_ms:.4f}ms per record")

# Expected: Sub-linear per-record cost with larger batches
# (10 items: 1ms/item, 1000 items: 0.5ms/item due to overhead amortization)
```

---

## Optimization Tips

### 1. Reuse Factory Objects

```python
# ✅ GOOD: Create once, reuse
factory = StrategyFactory(profile)
results = [factory.anonymize(record) for record in large_batch]

# ❌ BAD: Create for each record
results = [StrategyFactory(profile).anonymize(record) for record in large_batch]
```

### 2. Cache Strategy Instances

```python
# ✅ GOOD: Cache strategies
from confiture.core.anonymization.registry import StrategyRegistry

strategies = {}
for strategy_name in ["name", "date", "email"]:
    strategies[strategy_name] = StrategyRegistry.get(strategy_name, {"seed": 42})

# Use cached strategies
for record in data:
    name = strategies["name"].anonymize(record["name"])
```

### 3. Process in Batches

```python
# ✅ GOOD: Batch processing
batch_size = 1000
for i in range(0, len(data), batch_size):
    batch = data[i:i+batch_size]
    anonymized_batch = factory.anonymize_batch(batch)
    process_batch(anonymized_batch)
```

### 4. Use Preserve for Non-Sensitive Fields

```python
# ✅ GOOD: Skip anonymization for non-sensitive fields
profile = StrategyProfile(
    columns={
        "id": "preserve",              # Skip anonymization
        "amount": "preserve",          # Skip anonymization
        "name": "name",                # Anonymize
        "email": "text_redaction",     # Anonymize
    }
)

# ❌ BAD: Anonymize non-sensitive fields
profile = StrategyProfile(
    columns={
        "id": "text_redaction",        # Unnecessary
        "amount": "name",              # Wrong strategy
    }
)
```

### 5. Choose Appropriate Strategies

```python
# ✅ GOOD: Match strategy to data type
strategies = {
    "date": "date",                    # Fast - simple masking
    "preserve": "preserve",            # Fastest - no-op
    "email": "text_redaction:email",   # Medium - pattern matching
}

# ❌ BAD: Use complex strategies unnecessarily
strategies = {
    "date": "text_redaction",          # Slower - regex matching
    "preserve": "custom",              # Slower - function call
}
```

---

## Performance Metrics

### Typical Performance Figures

**Strategy Performance** (per 1000 operations):

| Strategy | Time | Ops/sec |
|----------|------|---------|
| Preserve | 0.5ms | 2000+ |
| Name | 0.8ms | 1250+ |
| Date | 1.0ms | 1000+ |
| Address | 1.5ms | 667+ |
| IP Address | 1.2ms | 833+ |
| Text Redaction | 5.0ms | 200+ |
| Credit Card | 10.0ms | 100+ |

**Batch Performance**:

- 10 records: 5-15ms total
- 100 records: 30-80ms total
- 1000 records: 250-600ms total

**Memory Footprint**:

- Per strategy: 1-5 KB
- Per factory: 50-100 KB
- Per profile: 10-50 KB

### Benchmarking Best Practices

1. **Warmup Runs**: Run 5-10 iterations before measuring
2. **Multiple Iterations**: Run at least 100 iterations
3. **Check Variance**: Watch for outliers
4. **Consistent Environment**: Close other applications
5. **Measure Twice**: Repeat measurements to ensure consistency

---

## Monitoring and Alerting

### Performance Regression Detection

```python
from confiture.core.anonymization.benchmarking import Benchmarker

# Baseline measurement
baseline = benchmarker.benchmark_strategy(strategy, values, iterations=1000)

# Current measurement
current = benchmarker.benchmark_strategy(strategy, values, iterations=1000)

# Compare
comparison = benchmarker.compare_performance(baseline, current)

if comparison.regression:
    # Alert: Performance degradation detected
    send_alert(f"Performance regression: {comparison.speedup:.2f}x")
else:
    # Log improvement
    log_improvement(f"Speedup: {comparison.speedup:.2f}x")
```

### Continuous Performance Monitoring

```python
import time
from datetime import datetime

# Track performance over time
performance_log = []

for _ in range(24):  # Track every hour
    result = benchmarker.benchmark_strategy(strategy, values, iterations=100)
    performance_log.append({
        "timestamp": datetime.now(),
        "avg_time_ms": result.avg_time_ms,
        "ops_per_sec": result.ops_per_second,
    })
    time.sleep(3600)  # Wait 1 hour

# Analyze trends
avg_time = sum(p["avg_time_ms"] for p in performance_log) / len(performance_log)
max_time = max(p["avg_time_ms"] for p in performance_log)
min_time = min(p["avg_time_ms"] for p in performance_log)

print(f"24-hour average: {avg_time:.2f}ms")
print(f"Variance: {max_time - min_time:.2f}ms")
```

---

## See Also

- [Anonymization Strategy Framework](./anonymization-strategy-framework.md)
- [Multi-Region Compliance](./multi-region-compliance.md)
- [Real-World Scenarios](./real-world-scenarios.md)
