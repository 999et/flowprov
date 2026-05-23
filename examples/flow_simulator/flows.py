"""Five realistic flow definitions used by the simulator.

These mirror the kind of agentic workflows a fintech like Deriv would actually
run in n8n / BuildShip: security triage, financial reconciliation classifier,
customer support routing, payment-decision agent, KYC-update summariser.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FlowDef:
    flow_id: str
    flow_name: str
    node_id: str
    prompt_template: str
    model_name: str
    temperature: float = 0.0


HACKERONE_TRIAGE = FlowDef(
    flow_id="security.hackerone.triage",
    flow_name="HackerOne Report Triage",
    node_id="llm.triage",
    prompt_template=(
        "You are a senior security analyst. Triage this HackerOne report.\n\n"
        "Report title: {title}\n"
        "Report body: {body}\n"
        "Affected asset: {asset}\n\n"
        "Output: severity (P0-P3), likely component, recommended owner."
    ),
    model_name="gpt-4o-mini",
)

RECON_CLASSIFY = FlowDef(
    flow_id="finance.recon.classify",
    flow_name="Reconciliation Exception Classifier",
    node_id="llm.classify",
    prompt_template=(
        "Classify this unreconciled finance event.\n\n"
        "Rail: {rail}\n"
        "Amount: {amount} {currency}\n"
        "Reference: {reference}\n"
        "Counterparty: {counterparty}\n\n"
        "Output: category, confidence, brief reasoning."
    ),
    model_name="gpt-4o-mini",
)

SUPPORT_ROUTE = FlowDef(
    flow_id="support.ticket.route",
    flow_name="Support Ticket Router",
    node_id="llm.route",
    prompt_template=(
        "Route this customer support ticket to the right team.\n\n"
        "Subject: {subject}\n"
        "Body: {body}\n"
        "Customer tier: {tier}\n\n"
        "Output: team, priority, ETA bucket."
    ),
    model_name="gpt-4o-mini",
)

PAYMENT_DECIDE = FlowDef(
    flow_id="finance.payment.decide",
    flow_name="Payment Decision Agent",
    node_id="llm.decide",
    prompt_template=(
        "Decide whether to approve, hold, or reject this payment.\n\n"
        "Amount: {amount} {currency}\n"
        "Direction: {direction}\n"
        "Risk score: {risk_score}\n"
        "KYC level: {kyc_level}\n\n"
        "Output: decision (APPROVE|HOLD|REJECT), justification."
    ),
    model_name="gpt-4o-mini",
)

KYC_SUMMARIZE = FlowDef(
    flow_id="kyc.update.summarize",
    flow_name="KYC Update Summariser",
    node_id="llm.summarize",
    prompt_template=(
        "Summarise this KYC update for a compliance reviewer.\n\n"
        "User ID: {user_id}\n"
        "Fields changed: {fields_changed}\n"
        "Previous values: {previous}\n"
        "New values: {new}\n\n"
        "Output: summary, key points, recommended action."
    ),
    model_name="gpt-4o-mini",
)


ALL_FLOWS = [
    HACKERONE_TRIAGE,
    RECON_CLASSIFY,
    SUPPORT_ROUTE,
    PAYMENT_DECIDE,
    KYC_SUMMARIZE,
]


# Per-flow input generators — return a list of distinct "input classes" so
# that the simulator can repeat each one and build up an in-class baseline.

def hackerone_inputs() -> list[dict]:
    return [
        {
            "title": "SSRF in image preview endpoint",
            "body": "The /preview endpoint fetches arbitrary URLs; reachable on internal AWS metadata",
            "asset": "api.deriv.com",
        },
        {
            "title": "Stored XSS in support chat",
            "body": "Markdown is rendered unsanitised in agent-facing chat UI",
            "asset": "support.deriv.com",
        },
        {
            "title": "IDOR on account positions",
            "body": "GET /positions/:id returns positions for any user id without auth check",
            "asset": "trade.deriv.com",
        },
    ]


def recon_inputs() -> list[dict]:
    return [
        {"rail": "SEPA", "amount": 12450.00, "currency": "EUR", "reference": "DERIV-TX-88231", "counterparty": "Acme Bank"},
        {"rail": "USDT-TRC20", "amount": 5000.00, "currency": "USDT", "reference": "0xabc123", "counterparty": "Binance"},
        {"rail": "SWIFT", "amount": 200000.00, "currency": "USD", "reference": "MT103-99812", "counterparty": "JP Morgan"},
        {"rail": "FPX", "amount": 8500.00, "currency": "MYR", "reference": "FPX-MY-7712", "counterparty": "Maybank"},
    ]


def support_inputs() -> list[dict]:
    return [
        {"subject": "Withdrawal pending 5 days", "body": "I have not received my BTC withdrawal from Tuesday", "tier": "gold"},
        {"subject": "Cannot login", "body": "2FA app reset, need recovery", "tier": "standard"},
        {"subject": "MT5 platform freezing", "body": "Charts hang after opening 4+ instruments", "tier": "platinum"},
    ]


def payment_inputs() -> list[dict]:
    return [
        {"amount": 500.00, "currency": "USD", "direction": "deposit", "risk_score": 0.12, "kyc_level": "verified"},
        {"amount": 25000.00, "currency": "EUR", "direction": "withdrawal", "risk_score": 0.34, "kyc_level": "verified"},
        {"amount": 9999.99, "currency": "USD", "direction": "deposit", "risk_score": 0.78, "kyc_level": "partial"},
    ]


def kyc_inputs() -> list[dict]:
    return [
        {"user_id": "u-44182", "fields_changed": "address", "previous": "Kuala Lumpur", "new": "Singapore"},
        {"user_id": "u-77291", "fields_changed": "phone", "previous": "+60-12-***", "new": "+65-91-***"},
    ]


INPUTS_BY_FLOW = {
    HACKERONE_TRIAGE.flow_id: hackerone_inputs(),
    RECON_CLASSIFY.flow_id: recon_inputs(),
    SUPPORT_ROUTE.flow_id: support_inputs(),
    PAYMENT_DECIDE.flow_id: payment_inputs(),
    KYC_SUMMARIZE.flow_id: kyc_inputs(),
}
