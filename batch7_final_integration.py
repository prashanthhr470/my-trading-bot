from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Dict, Optional

from app.agent.agent_runtime import AgentRuntime
from app.ai.decision_gate import apply_decision_gate
from app.ai.validator import validate_ai_decision
from app.ctrader.execution_adapter import BrokerExecutionAdapter
from app.ctrader.symbol_info import get_symbol_spec
from app.execution_safety import ExecutionSafetyGate
from app.risk_management import calculate_risk
from app.trade_plan import build_trade_plan, trade_plan_to_dict


SYMBOL = "XAUUSD"
TIMEFRAMES = ("H4", "H1", "M15", "M5")

# Final batch is permanently DRY-RUN.
DRY_RUN = True

RISK_PERCENT = 1.0
MAX_SPREAD = 5.0
MAX_OPEN_POSITIONS = 1
MAX_DAILY_LOSS_PERCENT = 3.0


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unwrap(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    return value


def _account_balance(available_data: Dict[str, Any]) -> float:
    account = _as_dict(available_data.get("account"))

    for key in ("balance", "account_balance"):
        try:
            value = float(account.get(key))
        except (TypeError, ValueError):
            continue

        if value > 0:
            return value

    return 10_000.0


def _trade_levels(
    setup: Dict[str, Any],
) -> Optional[tuple[float, float, float]]:
    entry = setup.get("entry_price")
    stop = setup.get("stop_loss")
    target = setup.get("take_profit")

    entry_zone = setup.get("entry_zone")

    if entry is None:
        if isinstance(entry_zone, (int, float)):
            entry = entry_zone
        elif isinstance(entry_zone, dict):
            entry = entry_zone.get(
                "price",
                entry_zone.get("entry"),
            )

    targets = setup.get("targets")

    if target is None and isinstance(targets, list) and targets:
        first = targets[0]

        if isinstance(first, (int, float)):
            target = first

        elif isinstance(first, dict):
            target = first.get(
                "price",
                first.get(
                    "target",
                    first.get("take_profit"),
                ),
            )

    try:
        if entry is None or stop is None or target is None:
            return None

        return (
            float(entry),
            float(stop),
            float(target),
        )

    except (TypeError, ValueError):
        return None


def _blocked_gate(reason: str) -> Dict[str, Any]:
    return {
        "decision": "WAIT",
        "gate_status": "BLOCKED",
        "gate_reason": reason,
    }


class FinalAgentPipeline:
    """
    Final integration layer.

    AgentRuntime
        -> Intelligence
        -> Qwen3
        -> AI Validator
        -> Decision Gate
        -> Setup
        -> Risk
        -> Trade Plan
        -> Broker Validation
        -> Final Safety Gate
        -> DRY-RUN execution

    This class never enables live execution.
    """

    def __init__(self) -> None:
        self.runtime = AgentRuntime(
            dry_run=True,
            max_calls_per_cycle=20,
            max_cycle_seconds=120.0,
        )

        self.adapter = BrokerExecutionAdapter(
            dry_run=True,
            max_spread=MAX_SPREAD,
        )

        self.safety_gate = ExecutionSafetyGate(
            max_spread=MAX_SPREAD,
            max_open_positions=MAX_OPEN_POSITIONS,
            max_daily_loss_percent=MAX_DAILY_LOSS_PERCENT,
            require_dry_run=True,
        )

    async def run(
        self,
        symbol: str = SYMBOL,
        timeframes: tuple[str, ...] = TIMEFRAMES,
        account_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        account_state (optional): real paper/demo account context supplied
        by the caller (e.g. multi_symbol_paper.py), used to feed the final
        safety gate with real numbers instead of conservative stubs:

            {
                "duplicate_position": bool,   # symbol already has an open position
                "daily_loss_percent": float,  # % equity lost since UTC day start
                "kill_switch": bool,          # manual or automatic circuit breaker
            }

        When not supplied (e.g. ad-hoc/manual runs with no account context),
        this defaults to the conservative values that were previously
        hardcoded: duplicate_position=False, daily_loss_percent=0.0,
        kill_switch=False. Those defaults are appropriate only because no
        account exists yet to be duplicated/lost against in that case.
        """

        account_state = account_state or {}

        if not DRY_RUN:
            raise RuntimeError(
                "FINAL BATCH SAFETY FAILURE: "
                "DRY_RUN must remain True."
            )

        symbol = symbol.upper()

        # --------------------------------------------------------
        # 1. AGENT RUNTIME
        # --------------------------------------------------------

        cycle = await self.runtime.run_cycle(
            symbol=symbol,
            timeframes=timeframes,
        )

        available_data = dict(
            cycle.available_data
        )

        intelligence = _as_dict(
            cycle.metadata.get("intelligence")
        )

        ai_reasoning = _as_dict(
            cycle.metadata.get("ai_reasoning")
        )

        # Some versions return the AI decision directly;
        # others may wrap it under "ai_decision".
        ai_decision = _as_dict(
            ai_reasoning.get("ai_decision")
        )

        # reasoning_engine returns the structured proposal under
        # "ai_decision". Some future/older versions may instead
        # expose it directly or under another wrapper.
        if not ai_decision:
            for key in (
                "decision",
                "final_decision",
                "proposal",
                "result",
            ):
                candidate = ai_reasoning.get(key)

                if isinstance(candidate, dict):
                    ai_decision = candidate
                    break

        if not ai_decision:
            # Last-resort direct response compatibility.
            if any(
                key in ai_reasoning
                for key in (
                    "market",
                    "bias",
                    "confidence",
                    "decision",
                    "setup",
                )
            ):
                ai_decision = dict(ai_reasoning)

        # --------------------------------------------------------
        # 2. DETERMINISTIC EVIDENCE
        # --------------------------------------------------------

        evidence = _unwrap(
            available_data.get("analyze_evidence"),
            "evidence",
        )

        if not isinstance(evidence, dict):
            evidence = {}

        if not evidence:
            context = _as_dict(
                intelligence.get("context")
            )

            evidence = _as_dict(
                context.get("evidence")
            )

        # --------------------------------------------------------
        # 3. AI VALIDATION
        # --------------------------------------------------------

        validation = validate_ai_decision(
            ai_decision,
            evidence,
            expected_symbol=symbol,
        )

        # --------------------------------------------------------
        # 4. DECISION GATE
        # --------------------------------------------------------

        if validation.get("valid") is True:
            try:
                gate = apply_decision_gate(
                    ai_decision,
                    evidence,
                )

            except Exception as exc:
                gate = _blocked_gate(
                    "Decision gate failed closed: "
                    f"{type(exc).__name__}: {exc}"
                )

        else:
            gate = _blocked_gate(
                "AI validator rejected the AI decision."
            )

        gated_decision = gate.get(
            "decision",
            "NO_TRADE",
        )

        # --------------------------------------------------------
        # 5. SETUP
        # --------------------------------------------------------

        setup = _as_dict(
            intelligence.get("setup")
        )

        # --------------------------------------------------------
        # 6. RISK MANAGEMENT
        # --------------------------------------------------------

        risk_result = None

        risk_reason = (
            "Risk calculation skipped because the "
            "upstream decision is not executable."
        )

        if gated_decision in {
            "BUY_CANDIDATE",
            "SELL_CANDIDATE",
        }:

            levels = _trade_levels(
                setup
            )

            if levels is None:

                risk_reason = (
                    "Executable candidate has no complete "
                    "entry, stop-loss and take-profit levels."
                )

            else:

                entry, stop, target = levels

                try:

                    symbol_spec = await get_symbol_spec(
                        symbol
                    )

                    risk_result = calculate_risk(
                        account_balance=_account_balance(
                            available_data
                        ),
                        direction=(
                            "BUY"
                            if gated_decision
                            == "BUY_CANDIDATE"
                            else "SELL"
                        ),
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        risk_percent=RISK_PERCENT,
                        symbol_spec=symbol_spec,
                    )

                    risk_reason = (
                        risk_result.reason
                    )

                except Exception as exc:

                    risk_reason = (
                        "Risk calculation failed closed: "
                        f"{type(exc).__name__}: {exc}"
                    )

        # --------------------------------------------------------
        # 7. TRADE PLAN
        # --------------------------------------------------------

        trade_plan = build_trade_plan(
            ai_decision=ai_decision,
            validator_result=validation,
            gate_result=gate,
            setup_result=setup,
            risk_result=risk_result,
            symbol=symbol,
        )

        # --------------------------------------------------------
        # 8. BROKER VALIDATION
        # --------------------------------------------------------

        broker_validation = self.adapter.validate_trade_plan(
            trade_plan
        )

        # Support both async and sync adapter implementations.
        if inspect.isawaitable(broker_validation):
            broker_validation = await broker_validation

        positions = _as_dict(
            available_data.get(
                "open_positions"
            )
        )

        try:
            open_positions = int(
                positions.get(
                    "position_count",
                    0,
                ) or 0
            )

        except (TypeError, ValueError):
            open_positions = 0

        # --------------------------------------------------------
        # 9. FINAL SAFETY GATE
        # --------------------------------------------------------

        safety_result = self.safety_gate.check(
            trade_plan,
            broker_validation,
            open_positions=open_positions,
            daily_loss_percent=float(
                account_state.get("daily_loss_percent", 0.0)
            ),
            kill_switch=bool(
                account_state.get("kill_switch", False)
            ),
            duplicate_position=bool(
                account_state.get("duplicate_position", False)
            ),
            dry_run=True,
        )

        broker_result = broker_validation

        # The only possible execution call is DRY-RUN.
        if safety_result.allowed:

            broker_result = await self.adapter.execute(
                trade_plan
            )

        # --------------------------------------------------------
        # 10. ABSOLUTE EXECUTION CHECK
        # --------------------------------------------------------

        if getattr(
            broker_result,
            "executed",
            False,
        ):

            raise RuntimeError(
                "CRITICAL SAFETY FAILURE: "
                "an order was reported as executed."
            )

        # Canonical downstream fields.  Keep these aliases at the
        # integration boundary so paper/live adapters consume one stable
        # contract regardless of internal pipeline representation.
        canonical_plan = trade_plan_to_dict(trade_plan)
        canonical_decision = gated_decision

        result = {
            "status": "COMPLETED",
            "symbol": symbol,
            "final_decision": canonical_decision,
            "paper_trade_plan": canonical_plan,
            "trade_authorized": False,
            "execution_allowed": False,
            "broker_order": False,
            "paper_trading": True,
            "ai_direct_execution": False,

            "cycle": {
                "cycle_id": cycle.cycle_id,
                "status": getattr(
                    cycle.status,
                    "value",
                    str(cycle.status),
                ),
                "tool_calls": cycle.metadata.get(
                    "tool_calls",
                    0,
                ),
            },

            "intelligence": intelligence,

            "ai_reasoning": ai_reasoning,

            "ai_validation": validation,

            "decision_gate": gate,

            "setup": setup,

            "risk": (
                risk_result.__dict__
                if risk_result is not None
                else {
                    "allowed": False,
                    "reason": risk_reason,
                }
            ),

            "trade_plan": canonical_plan,

            "broker_validation": (
                broker_validation.__dict__
            ),

            "broker_result": (
                broker_result.__dict__
            ),

            "final_safety": (
                safety_result.__dict__
            ),

            # Hard final-state declarations.
            "dry_run": True,
            "live_execution": False,
            "order_executed": False,
            "read_only": True,
        }

        return result


def _print_summary(
    result: Dict[str, Any],
) -> None:

    ai_reasoning = _as_dict(
        result.get("ai_reasoning")
    )

    ai = _as_dict(
        ai_reasoning.get("ai_decision")
    )

    if not ai:
        ai = ai_reasoning

    validation = _as_dict(
        result.get("ai_validation")
    )

    gate = _as_dict(
        result.get("decision_gate")
    )

    plan = _as_dict(
        result.get("trade_plan")
    )

    broker = _as_dict(
        result.get("broker_result")
    )

    safety = _as_dict(
        result.get("final_safety")
    )

    print()
    print("=" * 70)
    print(
        "HAFNOT AI TRADING AGENT — FINAL INTEGRATION BATCH"
    )
    print("=" * 70)

    print()

    print(
        f"STATUS:              "
        f"{result.get('status')}"
    )

    print(
        f"SYMBOL:              "
        f"{result.get('symbol')}"
    )

    print(
        f"AI DECISION:         "
        f"{ai.get('decision', 'UNKNOWN')}"
    )

    print(
        f"AI BIAS:             "
        f"{ai.get('bias', 'UNKNOWN')}"
    )

    print(
        f"AI CONFIDENCE:       "
        f"{ai.get('confidence', 'UNKNOWN')}"
    )

    print(
        f"AI VALIDATOR:        "
        f"{validation.get('valid', False)}"
    )

    print(
        f"DECISION GATE:       "
        f"{gate.get('decision', 'UNKNOWN')}"
    )

    print(
        f"TRADE PLAN:          "
        f"{plan.get('status', 'UNKNOWN')}"
    )

    print(
        f"BROKER ALLOWED:      "
        f"{broker.get('allowed', False)}"
    )

    print(
        f"BROKER EXECUTED:     "
        f"{broker.get('executed', False)}"
    )

    print(
        f"FINAL SAFETY:        "
        f"{safety.get('allowed', False)}"
    )

    print(
        f"DRY RUN:             "
        f"{result.get('dry_run')}"
    )

    print(
        f"LIVE EXECUTION:      "
        f"{result.get('live_execution')}"
    )

    print(
        f"ORDER EXECUTED:      "
        f"{result.get('order_executed')}"
    )

    print(
        f"READ ONLY:           "
        f"{result.get('read_only')}"
    )

    print()
    print("=" * 70)


async def main() -> None:

    result = await FinalAgentPipeline().run()

    _print_summary(
        result
    )

    # ------------------------------------------------------------
    # HARD ACCEPTANCE CHECKS
    # ------------------------------------------------------------

    checks = {
        "pipeline_completed": (
            result.get("status")
            == "COMPLETED"
        ),

        "ai_validation_completed": (
            isinstance(
                result.get("ai_validation"),
                dict,
            )
        ),

        "trade_plan_created": (
            isinstance(
                result.get("trade_plan"),
                dict,
            )
        ),

        "broker_validation_created": (
            isinstance(
                result.get("broker_validation"),
                dict,
            )
        ),

        "final_safety_created": (
            isinstance(
                result.get("final_safety"),
                dict,
            )
        ),

        "dry_run_enabled": (
            result.get("dry_run")
            is True
        ),

        "live_execution_disabled": (
            result.get("live_execution")
            is False
        ),

        "order_not_executed": (
            result.get("order_executed")
            is False
        ),

        "read_only": (
            result.get("read_only")
            is True
        ),

        "broker_did_not_execute": (
            result.get(
                "broker_result",
                {},
            ).get(
                "executed",
                False,
            )
            is False
        ),
    }

    print()
    print(
        "FINAL BATCH ACCEPTANCE CHECKS"
    )
    print("-" * 70)

    failed = []

    for name, passed in checks.items():

        label = (
            name.replace(
                "_",
                " ",
            ).upper()
        )

        if passed:
            print(
                f"[PASS] {label}"
            )

        else:
            print(
                f"[FAIL] {label}"
            )
            failed.append(
                name
            )

    print()

    if failed:

        print(
            "FINAL BATCH RESULT: FAILED"
        )

        raise RuntimeError(
            "Final batch acceptance checks failed: "
            + ", ".join(failed)
        )

    print(
        "FINAL BATCH RESULT: PASSED"
    )

    print()
    print(
        "FINAL RESULT JSON:"
    )

    print(
        json.dumps(
            {
                "status": result["status"],
                "symbol": result["symbol"],
                "ai_decision": (
                    _as_dict(
                        result["ai_reasoning"].get(
                            "ai_decision"
                        )
                    ).get(
                        "decision"
                    )
                    or result["ai_reasoning"].get(
                        "final_decision"
                    )
                    or result["ai_reasoning"].get(
                        "decision"
                    )
                ),
                "ai_validation": result[
                    "ai_validation"
                ].get(
                    "valid"
                ),
                "gate_decision": result[
                    "decision_gate"
                ].get(
                    "decision"
                ),
                "trade_plan_status": result[
                    "trade_plan"
                ].get(
                    "status"
                ),
                "broker_allowed": result[
                    "broker_result"
                ].get(
                    "allowed"
                ),
                "broker_executed": result[
                    "broker_result"
                ].get(
                    "executed"
                ),
                "final_safety_allowed": result[
                    "final_safety"
                ].get(
                    "allowed"
                ),
                "dry_run": result[
                    "dry_run"
                ],
                "live_execution": result[
                    "live_execution"
                ],
                "order_executed": result[
                    "order_executed"
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
