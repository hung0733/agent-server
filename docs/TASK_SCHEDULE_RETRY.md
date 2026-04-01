# Task Schedule Retry Mechanism

## Overview

The task schedule system includes a built-in retry mechanism with exponential backoff for handling task execution failures. This ensures resilient task scheduling even when temporary issues occur (agent busy, network failures, etc.).

## Retry Strategy

When a scheduled task fails, the system automatically retries according to the following backoff schedule:

| Consecutive Failures | Retry Delay | Description |
|---------------------|-------------|-------------|
| 1st failure | 30 seconds | Quick first retry |
| 2nd failure | 60 seconds (1 minute) | Slightly longer wait |
| 3rd failure | 300 seconds (5 minutes) | Moderate backoff |
| 4th failure | 900 seconds (15 minutes) | Significant wait |
| 5+ failures | 3600 seconds (60 minutes) | Maximum backoff |

### Key Behaviors

1. **Automatic Retry**: Failed tasks are automatically rescheduled with the appropriate delay
2. **Reset on Success**: The consecutive failure counter resets to 0 when a task succeeds
3. **Persistent State**: Failure tracking survives system restarts (stored in database)
4. **No Max Retry Limit**: Tasks will continue retrying indefinitely (can be manually disabled)

## Database Schema

### New Fields in `task_schedules` Table

```sql
-- Number of consecutive execution failures (resets to 0 on success)
consecutive_failures INTEGER NOT NULL DEFAULT 0

-- Timestamp of the last execution failure (NULL if never failed or last run succeeded)
last_failure_at TIMESTAMP WITH TIME ZONE NULL
```

## Implementation Details

### Retry Backoff Function

```python
def calculate_retry_delay_seconds(consecutive_failures: int) -> int:
    """
    Calculate retry delay in seconds based on consecutive failure count.

    Returns:
        - 0 if no failures
        - 30 for 1st failure
        - 60 for 2nd failure
        - 300 for 3rd failure
        - 900 for 4th failure
        - 3600 for 5+ failures
    """
```

### Task Execution Flow

```
1. Task execution attempted
   ├─> SUCCESS
   │   ├─ Reset consecutive_failures = 0
   │   ├─ Set last_failure_at = NULL
   │   └─ Calculate next_run_at from schedule expression
   │
   └─> FAILURE
       ├─ Increment consecutive_failures++
       ├─ Set last_failure_at = current_time
       ├─ Calculate retry_delay = calculate_retry_delay_seconds(consecutive_failures)
       └─ Set next_run_at = current_time + retry_delay
```

### Failure Handling

The scheduler treats two types of failures differently:

#### 1. Agent Busy (Temporary Failure)
- Task status: Remains `pending` (not marked `failed`)
- Retry behavior: Standard exponential backoff
- Use case: Agent is currently executing another task

#### 2. Execution Error (Actual Failure)
- Task status: Marked as `failed`
- Retry behavior: Standard exponential backoff
- Schedule continues: Next execution created despite failure
- Use case: Code errors, network failures, invalid payload

## Usage Examples

### Creating a Scheduled Task with Retry Awareness

```python
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dto.task_schedule_dto import TaskScheduleCreate
from db.types import ScheduleType

# Create a schedule (retry fields initialized automatically)
schedule = await TaskScheduleDAO.create(
    TaskScheduleCreate(
        task_template_id=template_task.id,
        schedule_type=ScheduleType.cron,
        schedule_expression="0 */6 * * *",  # Every 6 hours
        is_active=True,
    )
)

# consecutive_failures defaults to 0
# last_failure_at defaults to NULL
```

### Monitoring Retry State

```python
# Get schedule with retry information
schedule = await TaskScheduleDAO.get_by_id(schedule_id)

print(f"Consecutive failures: {schedule.consecutive_failures}")
print(f"Last failure: {schedule.last_failure_at}")
print(f"Next run: {schedule.next_run_at}")

# Check if schedule is in retry backoff
if schedule.consecutive_failures > 0:
    print(f"⚠️  Schedule failing ({schedule.consecutive_failures} attempts)")
    if schedule.consecutive_failures >= 5:
        print("❌ Maximum backoff reached (60 minute delays)")
```

### Manual Intervention

```python
# Manually reset failure tracking (force immediate retry)
await TaskScheduleDAO.update(
    TaskScheduleUpdate(
        id=schedule.id,
        consecutive_failures=0,
        last_failure_at=None,
        next_run_at=datetime.now(timezone.utc),  # Run immediately
    )
)

# Disable a failing schedule
await TaskScheduleDAO.update(
    TaskScheduleUpdate(
        id=schedule.id,
        is_active=False,  # Stop automatic retries
    )
)
```

## Observability

### Logging

The scheduler logs retry events at appropriate levels:

```python
# Info level: Retry attempts and backoff calculations
logger.info(
    "連續失敗次數: %d，將於 %d 秒後重試",
    new_failure_count,
    retry_delay_seconds,
)

# Warning level: Agent busy (temporary failure)
logger.warning(
    "Agent 忙碌，延遲重試: %s",
    error_msg,
)

# Error level: Actual execution failures
logger.error(
    "任務執行失敗: %s",
    str(e),
    exc_info=True,
)
```

### Monitoring Queries

```sql
-- Schedules currently in retry backoff
SELECT
    id,
    consecutive_failures,
    last_failure_at,
    next_run_at,
    next_run_at - NOW() AS time_until_retry
FROM task_schedules
WHERE consecutive_failures > 0
    AND is_active = TRUE
ORDER BY consecutive_failures DESC, last_failure_at ASC;

-- Schedules at maximum backoff (5+ failures)
SELECT
    id,
    task_template_id,
    consecutive_failures,
    last_failure_at
FROM task_schedules
WHERE consecutive_failures >= 5
    AND is_active = TRUE;

-- Average failure rate per schedule
SELECT
    AVG(consecutive_failures) AS avg_failures,
    MAX(consecutive_failures) AS max_failures,
    COUNT(*) FILTER (WHERE consecutive_failures > 0) AS failing_count,
    COUNT(*) AS total_count
FROM task_schedules
WHERE is_active = TRUE;
```

## Best Practices

### 1. **Idempotent Tasks**
Ensure scheduled tasks are idempotent since retries will re-execute them:

```python
# ✅ Good: Idempotent task
async def sync_user_data(user_id: UUID):
    """Sync user data - safe to run multiple times."""
    existing = await get_latest_sync(user_id)
    if existing and existing.timestamp > cutoff:
        return  # Already synced recently

    await perform_sync(user_id)

# ❌ Bad: Non-idempotent task
async def send_daily_email(user_id: UUID):
    """Sends email without checking if already sent."""
    await send_email(user_id, "daily_digest")
    # Retry would send duplicate emails!
```

### 2. **Monitor Failure Patterns**
Set up alerts for schedules stuck in retry:

- Alert when `consecutive_failures >= 3` (5+ minutes backoff)
- Critical alert when `consecutive_failures >= 5` (max backoff)
- Track schedules that haven't succeeded in 24+ hours

### 3. **Graceful Degradation**
Handle persistent failures appropriately:

```python
# Check failure count before critical operations
schedule = await TaskScheduleDAO.get_by_id(schedule_id)
if schedule.consecutive_failures >= 5:
    # Consider fallback behavior
    logger.critical(
        "Schedule %s failing consistently - manual intervention required",
        schedule_id,
    )
    # Maybe disable schedule or notify ops team
```

### 4. **Timeout Configuration**
Ensure task timeouts are shorter than retry delays:

```python
# ❌ Bad: Timeout longer than first retry delay
TASK_TIMEOUT = 60  # 1 minute timeout
# First retry after 30 seconds - timeout hasn't triggered yet!

# ✅ Good: Timeout shorter than retry delays
TASK_TIMEOUT = 15  # 15 seconds timeout
# Task fails fast, retry happens after 30 seconds
```

## Testing

### Unit Tests

```python
# Test retry backoff calculation
from scheduler.task_scheduler import calculate_retry_delay_seconds

assert calculate_retry_delay_seconds(0) == 0
assert calculate_retry_delay_seconds(1) == 30
assert calculate_retry_delay_seconds(2) == 60
assert calculate_retry_delay_seconds(3) == 300
assert calculate_retry_delay_seconds(4) == 900
assert calculate_retry_delay_seconds(5) == 3600
assert calculate_retry_delay_seconds(100) == 3600  # Max backoff
```

### Integration Tests

See `tests/integration/test_task_schedule_retry.py` for comprehensive integration tests covering:
- Consecutive failure tracking
- Success resets failure counter
- Retry delay progression
- Database persistence

## Migration

### Applying the Migration

```bash
# Apply retry tracking fields to task_schedules table
alembic upgrade head
```

### Rollback

```bash
# Remove retry tracking fields
alembic downgrade -1
```

### Existing Schedules

Existing schedules are automatically upgraded:
- `consecutive_failures` defaults to 0
- `last_failure_at` defaults to NULL
- No manual data migration needed

## Performance Impact

- **Database**: 2 additional columns per schedule (minimal storage)
- **Query Performance**: No impact (fields indexed for monitoring queries)
- **Runtime**: Negligible overhead (~1ms per failure to calculate delay)

## Future Enhancements

Potential improvements:
1. **Configurable Backoff**: Per-schedule custom retry delays
2. **Max Retry Limit**: Optional maximum attempt count
3. **Alert Integration**: Webhook notifications on persistent failures
4. **Retry History**: Separate table tracking all retry attempts
5. **Circuit Breaker**: Auto-disable schedules after N failures

## Related Documentation

- [Task Scheduler Architecture](./TASK_SCHEDULER.md)
- [Task Queue System](./TASK_QUEUE.md)
- [Database Schema](./SCHEMA.md)

## Changelog

### Version 1.0.0 (2026-04-01)
- ✅ Initial implementation of retry mechanism
- ✅ Exponential backoff strategy
- ✅ Database migration for retry fields
- ✅ Unit and integration tests
- ✅ Comprehensive logging
