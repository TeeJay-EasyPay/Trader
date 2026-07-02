from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .audit import AuditDatabase
from .guardrails import validate_trade_proposal
from .models import AccountContext, GuardrailConfig, TradeProposal


class ExecutionBroker(Protocol):
    def account_context(self, daily_realized_pnl: float = 0.0) -> AccountContext: ...
    def place_bracket_order(self, *, symbol: str, side: str, qty: float, stop_loss: float, take_profit: float) -> dict: ...


class ExecutionEngine:
    def __init__(self, *, broker: ExecutionBroker, audit: AuditDatabase, guardrails: GuardrailConfig):
        self.broker = broker
        self.audit = audit
        self.guardrails = guardrails

    def execute_proposals(
        self,
        proposals: list[TradeProposal],
        *,
        daily_realized_pnl: float = 0.0,
        now: datetime | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        for proposal in proposals:
            account = self.broker.account_context(daily_realized_pnl=daily_realized_pnl)
            validation = validate_trade_proposal(proposal, account, self.guardrails, now=now)
            if not validation.passed:
                result = {"proposal_id": proposal.proposal_id, "status": "rejected", "failures": validation.failures}
                self.audit.record_trade_event("execution_rejected", proposal, validation=validation, execution_result=result)
                self.audit.record_execution_event(proposal.proposal_id, "execution_rejected", result)
                results.append(result)
                continue

            order = self.broker.place_bracket_order(
                symbol=proposal.symbol,
                side=proposal.side,
                qty=proposal.position_size,
                stop_loss=proposal.stop_loss,
                take_profit=proposal.take_profit,
            )
            result = {"proposal_id": proposal.proposal_id, "status": "executed", "order": order}
            self.audit.record_trade_event("execution_approved", proposal, validation=validation, execution_result=result)
            self.audit.record_execution_event(proposal.proposal_id, "execution_approved", result)
            results.append(result)
        return results

