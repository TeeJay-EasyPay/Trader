# Scheduler Audit

## Scheduler Components

Implemented in `src/ai_trader/scheduler.py` and started in `run_server` in `src/ai_trader/api.py`.

## ResearchScheduler

Frequency:

- `RESEARCH_SCHEDULER_INTERVAL_MINUTES`, default 60.

Trigger:

- Starts only when `RESEARCH_SCHEDULER_ENABLED` is true.

Inputs:

- Calls `service.run_analysis({"limit": limit, "trigger_type": "scheduled"})`.

Outputs:

- Research run rows.
- Recommendations if generated.
- Notifications.

Failure handling:

- Exceptions are logged.
- `on_error` creates a `research_failure` notification.
- Loop continues.

Trading intelligence effect:

- Reruns current analysis logic. It does not introduce new strategy learning by itself.

## Managed Exit Worker

Name:

- `ai-trader-exit-monitor`.

Frequency:

- 60 seconds.

Function:

- `service.monitor_managed_exits`.

Purpose:

- Safety-critical stop loss/take profit/trailing stop monitoring for managed exits.

Trading intelligence effect:

- Operational trade management, not idea generation.

## Broker Order Monitor

Name:

- `ai-trader-order-monitor`.

Frequency:

- 60 seconds.

Function:

- `service.poll_broker_activity`.

Purpose:

- Poll broker orders and trade history.
- Persist new rows.
- Create fill/closed notifications.

Trading intelligence effect:

- Updates operational state and trade evidence.

## Auto Executor

Name:

- `ai-trader-auto-executor`.

Frequency:

- `max(30, AUTO_EXECUTION_INTERVAL_SECONDS)`, default 60.

Function:

- `service.auto_execute_recommendations`.

Purpose:

- Repeatedly tests whether existing recommendations are eligible.

Trading intelligence effect:

- No new intelligence; execution gate over existing ideas.

## Crypto Refresh Worker

Name:

- `ai-trader-crypto-refresh`.

Frequency:

- `max(300, RESEARCH_SCHEDULER_INTERVAL_MINUTES * 60)`.

Function:

- `service.refresh_crypto_universe`.

Purpose:

- Refresh crypto universe and then run crypto analysis.

Trading intelligence effect:

- Updates crypto market scores using current public data. It reruns the same scoring logic on refreshed data.

## Push Dispatch Worker

Name:

- `ai-trader-push-dispatch`.

Frequency:

- 30 seconds.

Function:

- `service.dispatch_pending_push_notifications`.

Purpose:

- Sends high-priority notifications.

Trading intelligence effect:

- None. Operational delivery only.

## Continuous Intelligence Finding

AI Trader continuously monitors and refreshes. It does not yet continuously study in a strategy-improvement sense. The scheduler reruns existing scoring and monitoring logic. It does not search for new strategies, recalibrate probabilities, or adapt rules from outcomes.
