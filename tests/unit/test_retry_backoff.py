# pyright: reportMissingImports=false
"""
Unit tests for task schedule retry backoff mechanism.

Tests the calculate_retry_delay_seconds function to ensure
proper exponential backoff behavior according to requirements:
- 1st failure: 30 seconds
- 2nd consecutive failure: 60 seconds
- 3rd consecutive failure: 300 seconds (5 minutes)
- 4th consecutive failure: 900 seconds (15 minutes)
- 5+ consecutive failures: 3600 seconds (60 minutes)

Import path: tests.unit.test_retry_backoff
"""
import pytest

from scheduler.task_scheduler import calculate_retry_delay_seconds


class TestRetryBackoff:
    """Test suite for retry backoff calculation."""

    def test_no_failures_returns_zero_delay(self):
        """Test that 0 consecutive failures returns 0 delay."""
        delay = calculate_retry_delay_seconds(0)
        assert delay == 0, "No failures should result in no delay"

    def test_first_failure_returns_30_seconds(self):
        """Test that 1st failure returns 30 second delay."""
        delay = calculate_retry_delay_seconds(1)
        assert delay == 30, "First failure should retry after 30 seconds"

    def test_second_consecutive_failure_returns_60_seconds(self):
        """Test that 2nd consecutive failure returns 60 second delay."""
        delay = calculate_retry_delay_seconds(2)
        assert delay == 60, "Second consecutive failure should retry after 60 seconds"

    def test_third_consecutive_failure_returns_5_minutes(self):
        """Test that 3rd consecutive failure returns 5 minute delay."""
        delay = calculate_retry_delay_seconds(3)
        assert delay == 300, "Third consecutive failure should retry after 5 minutes (300 seconds)"

    def test_fourth_consecutive_failure_returns_15_minutes(self):
        """Test that 4th consecutive failure returns 15 minute delay."""
        delay = calculate_retry_delay_seconds(4)
        assert delay == 900, "Fourth consecutive failure should retry after 15 minutes (900 seconds)"

    def test_fifth_consecutive_failure_returns_60_minutes(self):
        """Test that 5th consecutive failure returns 60 minute delay."""
        delay = calculate_retry_delay_seconds(5)
        assert delay == 3600, "Fifth consecutive failure should retry after 60 minutes (3600 seconds)"

    def test_sixth_consecutive_failure_returns_60_minutes(self):
        """Test that 6th consecutive failure still returns 60 minute delay."""
        delay = calculate_retry_delay_seconds(6)
        assert delay == 3600, "Sixth consecutive failure should retry after 60 minutes (3600 seconds)"

    def test_many_consecutive_failures_returns_60_minutes(self):
        """Test that 10th+ consecutive failures still return 60 minute delay."""
        for failure_count in [7, 10, 20, 50, 100]:
            delay = calculate_retry_delay_seconds(failure_count)
            assert delay == 3600, (
                f"{failure_count} consecutive failures should retry after 60 minutes (3600 seconds)"
            )

    def test_backoff_sequence(self):
        """Test the complete backoff sequence progression."""
        expected_sequence = [
            (0, 0),      # No failures
            (1, 30),     # 1st failure: 30 seconds
            (2, 60),     # 2nd failure: 60 seconds
            (3, 300),    # 3rd failure: 5 minutes
            (4, 900),    # 4th failure: 15 minutes
            (5, 3600),   # 5th failure: 60 minutes
            (6, 3600),   # 6th failure: 60 minutes
            (7, 3600),   # 7th failure: 60 minutes
        ]

        for failure_count, expected_delay in expected_sequence:
            actual_delay = calculate_retry_delay_seconds(failure_count)
            assert actual_delay == expected_delay, (
                f"Failed at failure_count={failure_count}: "
                f"expected {expected_delay}s, got {actual_delay}s"
            )

    @pytest.mark.parametrize("failure_count,expected_delay", [
        (0, 0),
        (1, 30),
        (2, 60),
        (3, 300),
        (4, 900),
        (5, 3600),
        (10, 3600),
        (100, 3600),
    ])
    def test_retry_delays_parametrized(self, failure_count: int, expected_delay: int):
        """Parametrized test for retry delay calculation."""
        actual_delay = calculate_retry_delay_seconds(failure_count)
        assert actual_delay == expected_delay, (
            f"Failure count {failure_count} should return {expected_delay}s delay, "
            f"got {actual_delay}s"
        )
