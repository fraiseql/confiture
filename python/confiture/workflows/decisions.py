"""Error decision trees for agent-driven error handling."""



class DecisionTree:
    """Decision tree for error classification and action selection."""

    def classify_error(self, error_code: str) -> str:
        """Classify error severity.

        Args:
            error_code: Error code like 'CONFIG_001'

        Returns:
            Severity: 'critical', 'error', 'warning', 'info'
        """
        category = error_code.split("_")[0]

        critical_categories = {"ROLLBACK", "PRECON"}
        warning_categories = {"LINT", "DIFFER"}
        info_categories = {"VALID"}

        if category in critical_categories:
            return "critical"
        if category in warning_categories:
            return "warning"
        if category in info_categories:
            return "info"
        return "error"

    def should_escalate(self, error_code: str) -> bool:
        """Determine if error should be escalated.

        Args:
            error_code: Error code

        Returns:
            True if should escalate to manual intervention
        """
        return self.classify_error(error_code) == "critical"

    def can_auto_repair(self, error_code: str) -> bool:
        """Determine if error can be auto-repaired.

        Args:
            error_code: Error code

        Returns:
            True if can attempt automatic repair
        """
        retryable = {"MIGR", "SQL", "POOL", "LOCK"}
        category = error_code.split("_")[0]
        return category in retryable
