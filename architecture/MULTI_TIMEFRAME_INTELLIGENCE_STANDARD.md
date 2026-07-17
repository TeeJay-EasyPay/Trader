# Multi-Timeframe Intelligence Standard

Date: 2026-07-17

## Standard

AI Trader must not flatten conflicting timeframes into one confident score. It should state what each timeframe says and whether the timeframes agree.

## Supported Timeframes

The architecture supports 5 minute, 15 minute, 1 hour, 4 hour, daily, weekly, and monthly evidence where data is available.

## Plain English Output

Example:

> Long-term trend is positive, medium-term momentum is weakening, and the short-term price is pulling back toward support.

## Rejection/Warn Conditions

Recommendations must warn or reject when the required timeframe data is stale, missing, duplicated, internally impossible, or too incomplete for the strategy.
