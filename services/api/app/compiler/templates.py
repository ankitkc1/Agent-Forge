"""Curated requirement templates shown in the workbench and used by end-to-end tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RequirementTemplate:
    id: str
    title: str
    domain: str
    summary: str
    requirement: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


TEMPLATES: tuple[RequirementTemplate, ...] = (
    RequirementTemplate(
        id="maintenance-triage",
        title="Maintenance triage",
        domain="property_maintenance",
        summary="Classify tenant requests, assess urgency, draft work orders with approval.",
        requirement=(
            "Build a property maintenance triage agent for our operations team. It should classify "
            "tenant requests, assess urgency, look up property details and maintenance policies, draft "
            "work orders and tenant emails, and require human approval before any external message or "
            "work order is sent. Use a local Qwen model, Postgres memory, and target at least 90% task "
            "success with zero unsafe actions."
        ),
    ),
    RequirementTemplate(
        id="customer-support",
        title="Customer support",
        domain="customer_support",
        summary="Ticket triage with documentation retrieval, account checks and escalation.",
        requirement=(
            "Build a customer support agent for a B2B SaaS company. It should classify incoming "
            "tickets, search product documentation, check account status, draft helpful replies, and "
            "escalate billing or security issues to a human. Require approval before sending any "
            "reply. Use OpenAI, Postgres memory, and target 92% task success with zero unsafe actions."
        ),
    ),
    RequirementTemplate(
        id="research-analyst",
        title="Research analyst",
        domain="market_research",
        summary="Evidence-backed, fully cited briefings with human review of weak claims.",
        requirement=(
            "Build a market research analyst that takes a company or sector, searches approved "
            "sources, extracts evidence, compares competitors, and produces a cited briefing. It may "
            "never invent a citation and must flag low-confidence claims for human review. Use a local "
            "Qwen model with vector retrieval and target 90% factual accuracy."
        ),
    ),
    RequirementTemplate(
        id="incident-coordinator",
        title="Incident coordinator",
        domain="incident_operations",
        summary="Runbook-driven incident triage with governed status updates.",
        requirement=(
            "Build an operations incident coordinator. It should classify incident reports, assess "
            "severity, retrieve the relevant runbook, identify owners, prepare a response plan, and "
            "draft status updates. Never execute infrastructure changes and require human approval "
            "before external communication. Use Postgres memory and target zero unsafe actions."
        ),
    ),
    RequirementTemplate(
        id="it-helpdesk",
        title="IT helpdesk",
        domain="it_helpdesk",
        summary="Employee IT requests with approval-gated password resets and access grants.",
        requirement=(
            "Create an IT helpdesk assistant that classifies employee requests into password reset, "
            "hardware, software install, network access and security report, looks up employee "
            "records, searches the IT knowledge base, creates tickets, and can reset passwords or "
            "grant access only after manager approval. Use Claude and SQLite memory."
        ),
    ),
    RequirementTemplate(
        id="accounts-payable",
        title="Accounts payable",
        domain="accounts_payable",
        summary="Three-way match, duplicate and fraud checks, approval before payment.",
        requirement=(
            "We need an accounts payable agent that processes vendor invoices, looks up invoice "
            "details and purchase orders for a three-way match, flags duplicates and bank detail "
            "changes as fraud risk, drafts vendor emails and schedules payments after controller "
            "approval. Use OpenAI with Postgres and pgvector, targeting 95% task success."
        ),
    ),
    RequirementTemplate(
        id="lead-qualification",
        title="Lead qualification",
        domain="sales_leads",
        summary="Qualify inbound leads, enrich them, and draft approved outreach.",
        requirement=(
            "Build a sales lead qualification agent that classifies inbound lead intent, scores fit, "
            "looks up the lead in our CRM, enriches company data, checks the sales playbook and drafts "
            "outreach emails a rep approves before sending. Use OpenAI and SQLite memory."
        ),
    ),
    RequirementTemplate(
        id="order-support",
        title="E-commerce orders",
        domain="ecommerce_orders",
        summary="Returns, refunds and shipping issues with approval-gated refunds.",
        requirement=(
            "Build an e-commerce order support agent for our online store. It should classify "
            "shopper requests, look up order details and shipment tracking, check the returns policy, "
            "draft replies, and issue refunds or create return labels only after supervisor approval. "
            "Use a local Llama model and SQLite memory."
        ),
    ),
    RequirementTemplate(
        id="contract-review",
        title="Contract review",
        domain="legal_contracts",
        summary="Triage contracts against the playbook and route risk to counsel.",
        requirement=(
            "Build a contract review assistant that classifies incoming contracts, assesses risk "
            "against our contract playbook and clause library, looks up contract records and "
            "counterparty history, drafts redline summaries for counsel, and routes contracts for "
            "signature only after legal approval. Do not provide legal advice. Use Anthropic Claude."
        ),
    ),
    RequirementTemplate(
        id="recruiting",
        title="Recruiting coordinator",
        domain="hr_recruiting",
        summary="Candidate questions and interview scheduling with approved emails.",
        requirement=(
            "Build a recruiting coordinator agent that answers candidate questions, looks up "
            "candidate application status and interview availability, consults HR policies and job "
            "descriptions, drafts candidate emails and schedules interviews after recruiter "
            "approval. Never disclose other candidates. Use OpenAI and Postgres memory."
        ),
    ),
)

TEMPLATES_BY_ID = {template.id: template for template in TEMPLATES}
