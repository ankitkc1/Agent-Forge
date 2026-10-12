"""Domain packs: curated knowledge the compiler and generator use for common agent domains.

A pack contributes defaults (tools, sources, labels, severity levels), detection rules, fixture
records and seed knowledge. Nothing in a pack is trusted *code*: everything is data that flows
through AgentSpec validation and the generator's escaping filters.

Label hints must be disjoint inside a pack so the deterministic offline model used by generated
evaluation suites is unambiguous; ``tests/test_domains.py`` enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolTemplate:
    name: str
    mode: str
    description: str
    inputs: tuple[tuple[str, str, str, bool], ...]
    triggers: tuple[str, ...] = ()
    default: bool = False


@dataclass(frozen=True)
class SourceTemplate:
    name: str
    description: str
    title: str
    sections: tuple[tuple[str, str], ...]
    triggers: tuple[str, ...] = ()
    default: bool = True


@dataclass(frozen=True)
class LabelTemplate:
    name: str
    description: str
    hints: tuple[str, ...]
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityTemplate:
    noun: str
    id_param: str
    id_prefix: str
    records: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DomainPack:
    key: str
    title: str
    detect: tuple[tuple[str, float], ...]
    agent_name: str
    role: str
    objective: str
    description: str
    entity: EntityTemplate
    classify_step: str
    labels: tuple[LabelTemplate, ...]
    assess_step: str | None
    dimension: str | None
    levels: tuple[LabelTemplate, ...]
    retrieve_step: str
    sources: tuple[SourceTemplate, ...]
    lookup_step: str
    draft_step: str
    tools: tuple[ToolTemplate, ...]
    analyze_steps: tuple[tuple[str, str], ...] = ()
    citations: bool = False
    review_always: bool = False
    safety_notes: tuple[str, ...] = field(default=())
    approval_step: str = "human_approval"
    respond_step: str = "respond"

    def label(self, name: str) -> LabelTemplate | None:
        return next((label for label in self.labels if label.name == name), None)


_URGENCY_LEVELS = (
    LabelTemplate(
        "low",
        "Cosmetic or informational; can be scheduled.",
        ("cosmetic", "whenever", "minor", "question", "routine", "no rush"),
    ),
    LabelTemplate(
        "medium",
        "Affects comfort or convenience; handle within days.",
        ("annoying", "intermittent", "slow", "not working", "broken"),
    ),
    LabelTemplate(
        "high",
        "Disrupts normal use; handle within 24 hours.",
        ("urgent", "asap", "today", "completely", "no hot water", "unusable"),
    ),
    LabelTemplate(
        "critical",
        "Safety risk or severe damage; respond immediately.",
        ("emergency", "flooding", "gas smell", "fire", "sparks", "injury", "dangerous"),
    ),
)

_PRIORITY_LEVELS = (
    LabelTemplate(
        "low",
        "General questions or feedback.",
        ("question", "curious", "feedback", "when you can", "no rush"),
    ),
    LabelTemplate(
        "normal",
        "A single user is affected with a workaround.",
        ("issue", "problem", "error", "not working", "help"),
    ),
    # "urgent" is deliberately absent: it is the implicit hint of the "urgent" level below.
    LabelTemplate(
        "high",
        "Blocks a user's work or revenue.",
        ("asap", "blocked", "cannot work", "deadline", "time sensitive"),
    ),
    LabelTemplate(
        "urgent",
        "Many users, security, legal or data loss exposure.",
        ("outage", "everyone", "breach", "data loss", "legal action", "all users"),
    ),
)


PACKS: tuple[DomainPack, ...] = (
    DomainPack(
        key="property_maintenance",
        title="Property maintenance",
        detect=(
            (r"\bmaintenance\b", 3),
            (r"\bpropert(y|ies)\b", 2),
            (r"\btenants?\b", 3),
            (r"\bwork orders?\b", 3),
            (r"\blandlord|building|apartment|facility|facilities\b", 1.5),
            (r"\brepairs?\b", 1),
        ),
        agent_name="maintenance_triage",
        role="maintenance triage agent",
        objective="Triage tenant maintenance requests, assess urgency, and prepare governed work orders.",
        description=(
            "Classifies tenant maintenance requests, assesses urgency, gathers property context and "
            "maintenance policy evidence, and prepares work orders and tenant communications that are "
            "only submitted after explicit human approval."
        ),
        entity=EntityTemplate(
            noun="property",
            id_param="property_id",
            id_prefix="P",
            records=(
                {
                    "property_id": "P-1001",
                    "address": "12 Harbour Street, Unit 4",
                    "type": "apartment",
                    "built": 1998,
                    "manager": "Jordan Lee",
                    "open_work_orders": 1,
                    "warranty": "Hot water system under warranty until 2027-06",
                },
                {
                    "property_id": "P-1002",
                    "address": "88 Ridge Road",
                    "type": "townhouse",
                    "built": 2011,
                    "manager": "Priya Nair",
                    "open_work_orders": 0,
                    "warranty": "None recorded",
                },
                {
                    "property_id": "P-1003",
                    "address": "5 Market Lane, Shop 2",
                    "type": "retail",
                    "built": 1985,
                    "manager": "Sam Ortiz",
                    "open_work_orders": 3,
                    "warranty": "HVAC service contract with CoolAir Pty Ltd",
                },
            ),
        ),
        classify_step="classify_request",
        labels=(
            LabelTemplate(
                "plumbing",
                "Leaks, drains, toilets, taps and hot water.",
                (
                    "leak",
                    "pipe",
                    "drain",
                    "toilet",
                    "tap",
                    "faucet",
                    "sink",
                    "shower",
                    "hot water",
                    "water pressure",
                ),
                (
                    "Water is leaking from under the kitchen sink at {id} and the cabinet below is soaked.",
                    "The shower drain at {id} is blocked and the water pressure is very low.",
                ),
            ),
            LabelTemplate(
                "electrical",
                "Power, outlets, lighting and switchboards.",
                ("power", "outlet", "electrical", "switchboard", "breaker", "light", "wiring", "socket"),
                (
                    "Half the power outlets in the living room at {id} stopped working and the breaker keeps tripping.",
                    "The hallway light at {id} flickers and the socket beside the bed feels warm.",
                ),
            ),
            LabelTemplate(
                "hvac",
                "Heating, cooling and ventilation.",
                (
                    "heating",
                    "air conditioning",
                    "aircon",
                    "hvac",
                    "heater",
                    "ventilation",
                    "thermostat",
                    "cooling",
                ),
                (
                    "The air conditioning at {id} is blowing warm air and the thermostat display is blank.",
                    "Our heater at {id} makes a loud rattling noise and the ventilation fan smells burnt.",
                ),
            ),
            LabelTemplate(
                "appliance",
                "Supplied appliances such as ovens, dishwashers and washers.",
                (
                    "oven",
                    "dishwasher",
                    "fridge",
                    "refrigerator",
                    "washing machine",
                    "dryer",
                    "stove",
                    "microwave",
                ),
                (
                    "The dishwasher at {id} will not start and the oven hinge snapped.",
                    "The fridge supplied with {id} is not keeping food cold.",
                ),
            ),
            LabelTemplate(
                "pest_control",
                "Insects, rodents and other pests.",
                ("pest", "mice", "rats", "cockroach", "ants", "termite", "wasp", "bed bugs"),
                (
                    "We have seen mice and cockroach droppings in the pantry at {id}.",
                    "There is a wasp nest above the back porch of {id}.",
                ),
            ),
            LabelTemplate(
                "general_repair",
                "Doors, windows, locks, walls and other fixtures.",
                ("door", "window", "lock", "wall", "ceiling", "floor", "paint", "fence", "gate"),
                (
                    "The front door lock at {id} is jammed and a window latch is loose.",
                    "There is a crack in the bedroom ceiling and the fence gate at {id} will not close.",
                ),
            ),
        ),
        assess_step="assess_urgency",
        dimension="urgency",
        levels=_URGENCY_LEVELS,
        retrieve_step="retrieve_policies",
        sources=(
            SourceTemplate(
                "maintenance_policies",
                "Response-time SLAs, contractor rules and tenant communication standards.",
                "Maintenance Policy Handbook",
                (
                    (
                        "Response times",
                        "Critical requests such as flooding, a gas smell, fire damage, sparks or exposed wiring require contractor attendance within 2 hours. High urgency requests such as no hot water, a blocked only toilet or a broken lock are attended within 24 hours. Medium requests are scheduled within 5 business days and low urgency cosmetic work within 20 business days.",
                    ),
                    (
                        "Plumbing",
                        "Leaks must be isolated at the nearest valve before a plumber is booked. Blocked drains and toilets are handled by the preferred plumbing contractor. Hot water system faults under warranty are referred to the manufacturer first.",
                    ),
                    (
                        "Electrical",
                        "Only licensed electricians may inspect power outlets, switchboards, breakers or wiring. Tenants must be told not to touch a warm socket or sparking outlet and to switch off power at the breaker if safe.",
                    ),
                    (
                        "Heating and cooling",
                        "Air conditioning, heating and ventilation faults are referred to the HVAC service contractor. Heater faults during winter and cooling faults during heatwaves are treated as high urgency.",
                    ),
                    (
                        "Approvals",
                        "Work orders above 1,500 dollars, any work at a retail property, and every message sent to a tenant must be approved by the property manager before submission.",
                    ),
                ),
                ("polic(y|ies)", "sla", "procedure", "rules"),
            ),
            SourceTemplate(
                "property_documents",
                "Property manuals, warranties, inspection notes and appliance records.",
                "Property Records Summary",
                (
                    (
                        "Appliances",
                        "Supplied appliances include an oven, dishwasher and fridge for apartments built after 1995. Washing machines and dryers are tenant owned unless the lease states otherwise.",
                    ),
                    (
                        "Pest control",
                        "Quarterly pest treatment covers ants, cockroaches, mice and rats. Termite inspections are annual. Wasp nests are removed by the pest control contractor within 3 days.",
                    ),
                    (
                        "Doors, windows and locks",
                        "Lock changes require a locksmith from the approved panel. Windows, doors, walls, ceilings and fences are repaired by the general repairs contractor.",
                    ),
                ),
                ("propert(y|ies) (details|documents|records)", "manuals?", "warrant(y|ies)", "inspection"),
            ),
        ),
        lookup_step="lookup_property",
        draft_step="prepare_action",
        tools=(
            ToolTemplate(
                "property_lookup",
                "read",
                "Look up a property's address, type, manager, warranties and open work orders.",
                (("property_id", "string", "Property identifier, for example P-1001.", True),),
                ("look ?up propert", "property (details|lookup|context)", "propert(y|ies) details"),
                True,
            ),
            ToolTemplate(
                "work_order_lookup",
                "read",
                "List existing work orders for a property to avoid duplicates.",
                (("property_id", "string", "Property identifier, for example P-1001.", True),),
                ("existing work orders", "duplicate", "work order (history|status)"),
            ),
            ToolTemplate(
                "create_work_order",
                "draft",
                "Create a maintenance work order for the appropriate contractor.",
                (
                    ("property_id", "string", "Property identifier, for example P-1001.", True),
                    ("category", "string", "Maintenance category such as plumbing or electrical.", True),
                    ("urgency", "string", "Urgency level: low, medium, high or critical.", True),
                    ("summary", "string", "Short description of the work required.", True),
                ),
                ("work orders?", "create .{0,20}orders?", "dispatch"),
                True,
            ),
            ToolTemplate(
                "send_tenant_email",
                "execute",
                "Send an update email to the tenant about their request.",
                (
                    ("property_id", "string", "Property identifier, for example P-1001.", True),
                    ("subject", "string", "Email subject line.", True),
                    ("body", "string", "Email body text.", True),
                ),
                ("tenant (emails?|messages?|updates?)", "emails?", "notify (the )?tenants?"),
                True,
            ),
            ToolTemplate(
                "schedule_contractor",
                "execute",
                "Book a contractor visit for an approved work order.",
                (
                    ("property_id", "string", "Property identifier, for example P-1001.", True),
                    ("category", "string", "Trade required, for example plumbing.", True),
                    ("window", "string", "Requested attendance window.", False),
                ),
                ("schedul", "book .{0,20}contractor", "contractor visit"),
            ),
        ),
        safety_notes=("Never advise tenants to perform electrical or gas work themselves.",),
    ),
    DomainPack(
        key="customer_support",
        title="Customer support",
        detect=(
            (r"\bcustomer support\b", 4),
            (r"\bsupport (tickets?|agent|team)\b", 3),
            (r"\btickets?\b", 1.5),
            (r"\bhelp ?desk\b", 1),
            (r"\bsaas\b", 2),
            (r"\bcustomers?\b", 1),
            (r"\bsubscription|billing|refund\b", 1),
        ),
        agent_name="customer_support",
        role="customer support agent",
        objective="Resolve customer support tickets safely with verified product context and clear escalation.",
        description=(
            "Triages incoming support tickets, checks the customer's account, retrieves verified product "
            "documentation and support policy, drafts helpful replies and escalates billing, security or "
            "high-priority issues to a human. Replies are only sent after approval."
        ),
        entity=EntityTemplate(
            noun="account",
            id_param="account_id",
            id_prefix="ACCT",
            records=(
                {
                    "account_id": "ACCT-1001",
                    "company": "Northwind Analytics",
                    "plan": "Business",
                    "seats": 48,
                    "status": "active",
                    "renewal_date": "2027-02-01",
                    "open_tickets": 2,
                },
                {
                    "account_id": "ACCT-1002",
                    "company": "Bluebird Clinics",
                    "plan": "Enterprise",
                    "seats": 310,
                    "status": "active",
                    "renewal_date": "2026-12-15",
                    "open_tickets": 0,
                },
                {
                    "account_id": "ACCT-1003",
                    "company": "Tiny Pixel Studio",
                    "plan": "Starter",
                    "seats": 3,
                    "status": "past_due",
                    "renewal_date": "2026-11-03",
                    "open_tickets": 1,
                },
            ),
        ),
        classify_step="classify_ticket",
        labels=(
            LabelTemplate(
                "billing",
                "Invoices, charges, refunds and payment methods.",
                ("invoice", "charge", "charged", "refund", "payment", "billing", "credit card", "receipt"),
                (
                    "We were charged twice on the latest invoice for {id}; please refund the duplicate payment.",
                    "Can you send a receipt and update the credit card on file for {id}?",
                ),
            ),
            LabelTemplate(
                "technical_issue",
                "Errors, bugs, integrations and performance problems.",
                ("error", "bug", "crash", "integration", "api", "timeout", "sync", "exception"),
                (
                    "The API returns a 500 error and the Salesforce integration sync for {id} keeps failing.",
                    "The dashboard crashes with an exception every time we export from {id}.",
                ),
            ),
            LabelTemplate(
                "account_access",
                "Login, password, SSO and permissions.",
                ("login", "log in", "password", "sso", "locked out", "two factor", "permissions", "invite"),
                (
                    "Our admin is locked out of {id}; the password reset email never arrives.",
                    "SSO login fails for new users we invite to {id}.",
                ),
            ),
            LabelTemplate(
                "feature_request",
                "Product suggestions and roadmap questions.",
                ("feature", "roadmap", "suggestion", "would be great", "wish", "enhancement"),
                (
                    "Feature suggestion for {id}: it would be great to schedule reports weekly.",
                    "Is a dark mode enhancement on the roadmap? Our team at {id} keeps asking.",
                ),
            ),
            LabelTemplate(
                "cancellation",
                "Downgrades, cancellations and churn risk.",
                ("cancel", "cancellation", "downgrade", "terminate", "close our account", "switching"),
                (
                    "We want to cancel the subscription for {id} at the end of the term.",
                    "Please downgrade {id} to the starter plan; we are switching providers next quarter.",
                ),
            ),
        ),
        assess_step="assess_priority",
        dimension="priority",
        levels=_PRIORITY_LEVELS,
        retrieve_step="retrieve_context",
        sources=(
            SourceTemplate(
                "product_documentation",
                "Verified product documentation and troubleshooting guides.",
                "Product Documentation",
                (
                    (
                        "API errors",
                        "A 500 error from the API usually indicates a failed upstream dependency. Ask for the request ID and timestamp. Timeouts above 30 seconds should be retried with exponential backoff. Integration sync failures are logged under Settings, Integrations, Activity.",
                    ),
                    (
                        "Login and SSO",
                        "Password reset emails expire after 30 minutes. If a user is locked out after five failed attempts, an admin can unlock them. SSO login for invited users requires the email domain to be verified.",
                    ),
                    (
                        "Exports and dashboards",
                        "Exports larger than 1 million rows run asynchronously. A dashboard crash during export is a known issue fixed in release 4.12.",
                    ),
                ),
                ("documentation", "docs", "knowledge base", "help center", "troubleshoot"),
            ),
            SourceTemplate(
                "support_policies",
                "Refund, escalation and communication policies.",
                "Support Policy",
                (
                    (
                        "Refunds",
                        "Duplicate charges are refunded in full within 5 business days. Refunds above 500 dollars require approval from a billing specialist. Never promise a refund before the charge has been verified on the invoice.",
                    ),
                    (
                        "Escalation",
                        "Escalate to tier 2 when a technical issue blocks all users of an account, to security for suspected compromise, and to billing for disputed invoices. Enterprise accounts receive a response within 1 hour.",
                    ),
                    (
                        "Cancellations",
                        "Cancellation requests are acknowledged within one business day and routed to the account manager. Do not offer discounts without approval.",
                    ),
                ),
                ("polic(y|ies)", "refund rules", "escalation rules", "sla"),
            ),
        ),
        lookup_step="lookup_account",
        draft_step="prepare_response",
        tools=(
            ToolTemplate(
                "account_lookup",
                "read",
                "Look up a customer account's plan, status, seats and renewal date.",
                (("account_id", "string", "Account identifier, for example ACCT-1001.", True),),
                ("account (status|details|lookup)", "check .{0,20}account"),
                True,
            ),
            ToolTemplate(
                "ticket_history_lookup",
                "read",
                "List the account's recent tickets and their outcomes.",
                (("account_id", "string", "Account identifier, for example ACCT-1001.", True),),
                ("ticket history", "previous tickets", "past tickets"),
            ),
            ToolTemplate(
                "draft_reply",
                "draft",
                "Draft a reply to the customer for agent review.",
                (
                    ("account_id", "string", "Account identifier, for example ACCT-1001.", True),
                    ("subject", "string", "Reply subject.", True),
                    ("body", "string", "Reply body.", True),
                ),
                ("draft .{0,20}repl", "repl(y|ies)", "responses?"),
                True,
            ),
            ToolTemplate(
                "escalate_ticket",
                "execute",
                "Escalate the ticket to a specialist queue.",
                (
                    ("account_id", "string", "Account identifier, for example ACCT-1001.", True),
                    ("queue", "string", "Destination queue: tier2, billing or security.", True),
                    ("reason", "string", "Why the ticket is escalated.", True),
                ),
                ("escalat",),
                True,
            ),
        ),
    ),
    DomainPack(
        key="market_research",
        title="Market research",
        detect=(
            (r"\bmarket research\b", 4),
            (r"\bresearch\b", 2),
            (r"\bcompetitors?\b", 2),
            (r"\bbriefings?\b", 2),
            (r"\bmarket\b", 1),
            (r"\bsector|industry analysis\b", 1.5),
            (r"\bcitations?\b|\bcited\b", 1.5),
        ),
        agent_name="market_research",
        role="market research analyst",
        objective="Produce evidence-backed, fully cited market research briefings for human review.",
        description=(
            "Plans research for a company, sector or question, gathers evidence only from approved sources, "
            "extracts and compares findings, verifies every citation and flags low-confidence claims for "
            "human review before a briefing is published."
        ),
        entity=EntityTemplate(
            noun="company",
            id_param="company_id",
            id_prefix="CO",
            records=(
                {
                    "company_id": "CO-1001",
                    "name": "Helios Batteries",
                    "sector": "energy storage",
                    "hq": "Austin, USA",
                    "employees": 1200,
                    "founded": 2014,
                },
                {
                    "company_id": "CO-1002",
                    "name": "Aster Robotics",
                    "sector": "warehouse automation",
                    "hq": "Munich, Germany",
                    "employees": 640,
                    "founded": 2017,
                },
                {
                    "company_id": "CO-1003",
                    "name": "Kelpie Foods",
                    "sector": "plant-based foods",
                    "hq": "Melbourne, Australia",
                    "employees": 310,
                    "founded": 2019,
                },
            ),
        ),
        classify_step="classify_request",
        labels=(
            LabelTemplate(
                "company_profile",
                "Profile of a single company.",
                ("profile", "company overview", "background", "leadership", "funding"),
                (
                    "Prepare a company profile for {id} covering leadership and funding history.",
                    "I need a background overview on {id} before our meeting.",
                ),
            ),
            LabelTemplate(
                "competitor_analysis",
                "Comparison against named competitors.",
                ("competitor", "competitive", "versus", "compare", "rivals", "positioning"),
                (
                    "Compare {id} versus its main competitors on positioning and pricing.",
                    "Who are the rivals of {id} and how does their competitive offer differ?",
                ),
            ),
            LabelTemplate(
                "market_sizing",
                "TAM/SAM estimates and growth rates.",
                ("market size", "tam", "addressable", "growth rate", "cagr", "forecast"),
                (
                    "Estimate the addressable market and CAGR forecast relevant to {id}.",
                    "What is the market size and growth rate for the segment {id} sells into?",
                ),
            ),
            LabelTemplate(
                "trend_analysis",
                "Emerging trends, regulation and technology shifts.",
                ("trend", "emerging", "regulation", "outlook", "shift", "adoption"),
                (
                    "Summarise emerging regulation trends that affect {id} over the next two years.",
                    "What adoption shifts and outlook should we expect around {id}?",
                ),
            ),
        ),
        assess_step=None,
        dimension=None,
        levels=(),
        retrieve_step="gather_sources",
        sources=(
            SourceTemplate(
                "research_library",
                "Curated internal research notes and analyst reports.",
                "Research Library",
                (
                    (
                        "Energy storage",
                        "Grid-scale energy storage deployments grew 45 percent in 2025. Helios Batteries focuses on sodium-ion cells for commercial buildings and raised a Series D round in 2025. Competitors include larger lithium-ion incumbents competing on price.",
                    ),
                    (
                        "Warehouse automation",
                        "The warehouse automation market is forecast to grow at a 14 percent CAGR through 2030. Aster Robotics positions itself on fast deployment of mobile picking robots versus fixed conveyor systems.",
                    ),
                    (
                        "Plant-based foods",
                        "Plant-based food adoption slowed in 2024 before stabilising in 2025. Regulation on labelling is an emerging trend in the EU and Australia. Kelpie Foods competes on ocean-sourced protein.",
                    ),
                ),
                ("research library", "analyst reports?", "internal research", "library"),
            ),
            SourceTemplate(
                "approved_web_sources",
                "Allow-listed public sources such as filings and reputable news.",
                "Approved Web Sources Digest",
                (
                    (
                        "Funding and leadership",
                        "Company profiles must cite funding announcements and leadership changes from filings or reputable news. Unverified social media claims are excluded.",
                    ),
                    (
                        "Methodology",
                        "Market size estimates must state the year, the geography and whether the figure is TAM, SAM or SOM. Growth rate claims require a cited forecast source.",
                    ),
                ),
                ("approved sources", "web sources", "public sources", "filings"),
            ),
        ),
        lookup_step="lookup_company",
        draft_step="draft_brief",
        tools=(
            ToolTemplate(
                "company_lookup",
                "read",
                "Look up a company's sector, headquarters, size and founding year.",
                (("company_id", "string", "Company identifier, for example CO-1001.", True),),
                ("company (data|details|profile)", "look ?up .{0,20}compan"),
                True,
            ),
            ToolTemplate(
                "source_reader",
                "read",
                "Read an approved source document by identifier.",
                (("query", "string", "What to read about.", True),),
                ("read sources?", "source reader"),
            ),
            ToolTemplate(
                "citation_checker",
                "read",
                "Check that a citation exists in the approved source list.",
                (("query", "string", "Citation or claim to check.", True),),
                ("citation check", "verify citations?"),
            ),
        ),
        analyze_steps=(
            ("plan_research", "Plan the research questions and evidence needed."),
            ("extract_evidence", "Extract evidence with citations from gathered sources."),
            ("compare_findings", "Compare findings and note conflicts or gaps."),
        ),
        citations=True,
        approval_step="human_review",
        respond_step="publish_brief",
    ),
    DomainPack(
        key="incident_operations",
        title="Incident operations",
        detect=(
            (r"\bincidents?\b", 3),
            (r"\boutages?\b", 2),
            (r"\brunbooks?\b", 3),
            (r"\bon-?call\b", 2),
            (r"\bsre|devops|operations\b", 1.5),
            (r"\bstatus (page|updates?)\b", 2),
        ),
        agent_name="incident_coordinator",
        role="incident coordinator",
        objective="Coordinate operational incidents with runbooks, owners and governed status updates.",
        description=(
            "Classifies incident reports, assesses severity, retrieves the relevant runbook and incident "
            "history, identifies service owners and drafts response plans and status updates. It never "
            "executes infrastructure changes and requires approval before any external communication."
        ),
        entity=EntityTemplate(
            noun="service",
            id_param="service_id",
            id_prefix="SVC",
            records=(
                {
                    "service_id": "SVC-1001",
                    "name": "checkout-api",
                    "tier": 1,
                    "owner_team": "payments",
                    "on_call": "Avery Chen",
                    "slo": "99.95%",
                },
                {
                    "service_id": "SVC-1002",
                    "name": "search-indexer",
                    "tier": 2,
                    "owner_team": "discovery",
                    "on_call": "Noah Patel",
                    "slo": "99.5%",
                },
                {
                    "service_id": "SVC-1003",
                    "name": "auth-gateway",
                    "tier": 1,
                    "owner_team": "identity",
                    "on_call": "Mia Rossi",
                    "slo": "99.99%",
                },
            ),
        ),
        classify_step="classify_incident",
        labels=(
            LabelTemplate(
                "outage",
                "Service unavailable or failing for users.",
                ("down", "outage", "unavailable", "503", "not responding", "unreachable"),
                (
                    "{id} is down and returning 503 for every request.",
                    "Users report {id} is unreachable and not responding since 09:40.",
                ),
            ),
            LabelTemplate(
                "performance_degradation",
                "Elevated latency or reduced throughput.",
                ("latency", "slow", "degraded", "p99", "throughput", "lag"),
                (
                    "p99 latency on {id} jumped to 4 seconds and throughput is degraded.",
                    "Search results from {id} lag by ten minutes and responses are slow.",
                ),
            ),
            LabelTemplate(
                "security_incident",
                "Suspected compromise or exposure.",
                ("breach", "compromised", "leaked credentials", "suspicious", "unauthorized", "malware"),
                (
                    "We see suspicious unauthorized logins on {id} and possibly leaked credentials.",
                    "Possible malware on a host that runs {id}; it may be compromised.",
                ),
            ),
            LabelTemplate(
                "data_issue",
                "Data corruption, loss or inconsistency.",
                ("corrupt", "missing data", "inconsistent", "data loss", "duplicate records", "wrong totals"),
                (
                    "{id} shows wrong totals and duplicate records after last night's job.",
                    "Reports from {id} have missing data and inconsistent order counts.",
                ),
            ),
            LabelTemplate(
                "deployment_failure",
                "Failed rollout or bad release.",
                ("deploy", "deployment", "rollout", "release", "rollback", "canary"),
                (
                    "The canary deployment of {id} failed and the rollout is stuck.",
                    "Release 2.4 of {id} broke the build pipeline and needs a rollback decision.",
                ),
            ),
        ),
        assess_step="assess_severity",
        dimension="severity",
        levels=(
            LabelTemplate(
                "sev4", "Cosmetic, no customer impact.", ("cosmetic", "internal only", "no impact", "typo")
            ),
            LabelTemplate(
                "sev3", "Minor impact with workaround.", ("some users", "workaround", "intermittent", "minor")
            ),
            LabelTemplate(
                "sev2",
                "Major feature degraded for many customers.",
                ("many users", "major", "degraded", "revenue"),
            ),
            LabelTemplate(
                "sev1",
                "Critical outage, security or data loss.",
                ("all users", "every request", "complete outage", "breach", "data loss", "compromised"),
            ),
        ),
        retrieve_step="retrieve_runbook",
        sources=(
            SourceTemplate(
                "runbooks",
                "Approved operational runbooks.",
                "Operational Runbooks",
                (
                    (
                        "Outage response",
                        "For an outage returning 503 errors, confirm with synthetic checks, page the owning team's on-call engineer, open an incident channel and publish a status update within 15 minutes for tier 1 services.",
                    ),
                    (
                        "Latency",
                        "For p99 latency regressions, compare against the last deployment, check database saturation and cache hit rate. Throughput degradation over 30 percent is treated as sev2.",
                    ),
                    (
                        "Security",
                        "Suspected compromise or leaked credentials: rotate credentials only through the security team, preserve logs, and do not discuss details in public channels.",
                    ),
                    (
                        "Deployments",
                        "A failed canary or stuck rollout is paused. Rollback decisions are made by the service owner; the coordinator never runs infrastructure commands.",
                    ),
                ),
                ("runbooks?", "playbooks?", "procedures?"),
            ),
            SourceTemplate(
                "incident_history",
                "Summaries of past incidents and post-incident reviews.",
                "Incident History",
                (
                    (
                        "INC-2041 checkout outage",
                        "A database connection pool exhaustion caused 503 errors on checkout-api for 22 minutes. Mitigated by restarting pods; follow-up added pool alerts.",
                    ),
                    (
                        "INC-2077 search lag",
                        "The search indexer lagged 15 minutes due to a stuck consumer. Resolved by the discovery team after rebalancing partitions.",
                    ),
                ),
                ("incident history", "past incidents", "post-?mortems?"),
            ),
        ),
        lookup_step="identify_owners",
        draft_step="prepare_response",
        tools=(
            ToolTemplate(
                "service_owner_lookup",
                "read",
                "Find the owning team, tier and on-call engineer for a service.",
                (("service_id", "string", "Service identifier, for example SVC-1001.", True),),
                ("owners?", "on-?call", "service owner"),
                True,
            ),
            ToolTemplate(
                "service_status_lookup",
                "read",
                "Read current health checks and recent deployments for a service.",
                (("service_id", "string", "Service identifier, for example SVC-1001.", True),),
                ("service status", "health checks?", "recent deploy"),
            ),
            ToolTemplate(
                "draft_status_update",
                "draft",
                "Draft a customer-facing or internal status update.",
                (
                    ("service_id", "string", "Service identifier, for example SVC-1001.", True),
                    ("audience", "string", "internal or external.", True),
                    ("message", "string", "Status update text.", True),
                ),
                ("status updates?", "draft .{0,20}updates?", "communications?"),
                True,
            ),
            ToolTemplate(
                "page_on_call",
                "execute",
                "Page the on-call engineer for the owning team.",
                (
                    ("service_id", "string", "Service identifier, for example SVC-1001.", True),
                    ("summary", "string", "What the engineer needs to know.", True),
                ),
                ("page", "alert the on-?call"),
            ),
        ),
        safety_notes=(
            "Never execute infrastructure changes; recommend actions to the service owner instead.",
        ),
    ),
    DomainPack(
        key="it_helpdesk",
        title="IT helpdesk",
        detect=(
            (r"\bit (help ?desk|support|service desk)\b", 4),
            (r"\bservice desk\b", 3),
            (r"\bemployees?\b", 1),
            (r"\blaptops?|devices?\b", 1.5),
            (r"\bpassword resets?\b", 2),
            (r"\baccess requests?\b", 2),
        ),
        agent_name="it_helpdesk",
        role="IT helpdesk agent",
        objective="Resolve employee IT requests quickly while gating access changes behind approval.",
        description=(
            "Classifies employee IT requests, checks employee and device records, retrieves the IT knowledge "
            "base and policies, and prepares tickets, password resets and access grants that require approval "
            "before execution."
        ),
        entity=EntityTemplate(
            noun="employee",
            id_param="employee_id",
            id_prefix="EMP",
            records=(
                {
                    "employee_id": "EMP-1001",
                    "name": "Riley Morgan",
                    "department": "Finance",
                    "device": "Laptop L-5521",
                    "manager": "Dana Kim",
                    "mfa_enrolled": True,
                },
                {
                    "employee_id": "EMP-1002",
                    "name": "Chris Varga",
                    "department": "Engineering",
                    "device": "Laptop L-6610",
                    "manager": "Ola Ade",
                    "mfa_enrolled": True,
                },
                {
                    "employee_id": "EMP-1003",
                    "name": "Taylor Brooks",
                    "department": "Sales",
                    "device": "Tablet T-1209",
                    "manager": "Ivan Petrov",
                    "mfa_enrolled": False,
                },
            ),
        ),
        classify_step="classify_request",
        labels=(
            LabelTemplate(
                "password_reset",
                "Forgotten passwords and locked accounts.",
                ("password", "locked out", "reset", "forgot", "expired"),
                (
                    "{id} forgot their password and is locked out after it expired.",
                    "Please reset the password for {id}; the account is locked out.",
                ),
            ),
            LabelTemplate(
                "hardware",
                "Laptops, monitors, peripherals and broken devices.",
                ("laptop", "monitor", "keyboard", "battery", "screen", "charger", "docking station"),
                (
                    "The laptop screen for {id} is cracked and the charger no longer works.",
                    "{id} needs a replacement keyboard and docking station.",
                ),
            ),
            LabelTemplate(
                "software_install",
                "Installing or updating software.",
                ("install", "software", "license", "update", "upgrade", "application"),
                (
                    "{id} needs a license to install the design software application.",
                    "Please upgrade the analytics software for {id} to the latest update.",
                ),
            ),
            LabelTemplate(
                "network_access",
                "VPN, Wi-Fi and system access.",
                ("vpn", "wifi", "wi-fi", "network", "access to", "shared drive", "permission"),
                (
                    "{id} cannot connect to the VPN and needs access to the finance shared drive.",
                    "The office wifi drops for {id} and network permission is missing.",
                ),
            ),
            LabelTemplate(
                "security_report",
                "Phishing and suspected security issues.",
                ("phishing", "suspicious email", "virus", "hacked", "scam", "clicked a link"),
                (
                    "{id} clicked a link in a suspicious email that looks like phishing.",
                    "{id} thinks their computer has a virus after a scam pop-up.",
                ),
            ),
        ),
        assess_step="assess_priority",
        dimension="priority",
        levels=_PRIORITY_LEVELS,
        retrieve_step="retrieve_knowledge",
        sources=(
            SourceTemplate(
                "it_knowledge_base",
                "Troubleshooting articles for common IT requests.",
                "IT Knowledge Base",
                (
                    (
                        "Passwords",
                        "Self-service password reset is available at the identity portal. Accounts lock after five failed attempts and unlock automatically after 30 minutes. Expired passwords must be changed on a managed device.",
                    ),
                    (
                        "VPN and network",
                        "VPN connection failures are usually caused by an expired certificate; reinstall the VPN profile from the company portal. Shared drive access requires manager approval.",
                    ),
                    (
                        "Hardware",
                        "Cracked screens and failed batteries are replaced through the hardware desk within 2 business days. Loan laptops are available.",
                    ),
                ),
                ("knowledge base", "kb", "articles", "troubleshoot"),
            ),
            SourceTemplate(
                "it_policies",
                "Acceptable use, access control and security policies.",
                "IT Security and Access Policy",
                (
                    (
                        "Access control",
                        "Access to finance, HR or production systems requires written manager approval and is reviewed quarterly. Never grant administrator rights through the helpdesk.",
                    ),
                    (
                        "Security reports",
                        "Phishing reports must be forwarded to the security team immediately. If a user clicked a link, reset their password and revoke active sessions after approval.",
                    ),
                ),
                ("polic(y|ies)", "access control", "acceptable use"),
            ),
        ),
        lookup_step="lookup_employee",
        draft_step="prepare_action",
        tools=(
            ToolTemplate(
                "employee_lookup",
                "read",
                "Look up an employee's department, manager, device and MFA status.",
                (("employee_id", "string", "Employee identifier, for example EMP-1001.", True),),
                ("employee (records?|details|lookup)", "look ?up .{0,20}employee"),
                True,
            ),
            ToolTemplate(
                "device_lookup",
                "read",
                "Look up device inventory and warranty details.",
                (("employee_id", "string", "Employee identifier, for example EMP-1001.", True),),
                ("device (records?|inventory|lookup)", "asset"),
            ),
            ToolTemplate(
                "create_ticket",
                "draft",
                "Create a helpdesk ticket for the request.",
                (
                    ("employee_id", "string", "Employee identifier, for example EMP-1001.", True),
                    ("category", "string", "Ticket category.", True),
                    ("summary", "string", "Ticket summary.", True),
                ),
                ("tickets?",),
                True,
            ),
            ToolTemplate(
                "reset_password",
                "execute",
                "Trigger a password reset and revoke active sessions.",
                (("employee_id", "string", "Employee identifier, for example EMP-1001.", True),),
                ("password resets?", "reset .{0,20}passwords?"),
            ),
            ToolTemplate(
                "grant_access",
                "execute",
                "Grant access to a system or shared resource.",
                (
                    ("employee_id", "string", "Employee identifier, for example EMP-1001.", True),
                    ("resource", "string", "System or resource to grant access to.", True),
                ),
                ("grant .{0,20}access", "access requests?", "provision"),
            ),
        ),
    ),
    DomainPack(
        key="hr_recruiting",
        title="HR and recruiting",
        detect=(
            (r"\brecruit(ing|ment|er)?\b", 3),
            (r"\bcandidates?\b", 3),
            (r"\binterviews?\b", 2),
            (r"\bhiring|job applications?|onboarding\b", 2),
            (r"\bhr\b|\bhuman resources\b", 2),
        ),
        agent_name="recruiting_coordinator",
        role="recruiting coordinator",
        objective="Answer candidate questions and coordinate interviews with approved communications.",
        description=(
            "Classifies candidate and employee questions, looks up application status and interview "
            "availability, retrieves HR policies and job descriptions, and drafts candidate emails and "
            "interview bookings that are sent only after recruiter approval."
        ),
        entity=EntityTemplate(
            noun="candidate",
            id_param="candidate_id",
            id_prefix="CAND",
            records=(
                {
                    "candidate_id": "CAND-1001",
                    "name": "Alex Rivera",
                    "role": "Senior Data Engineer",
                    "stage": "technical interview",
                    "recruiter": "Kim Osei",
                },
                {
                    "candidate_id": "CAND-1002",
                    "name": "Jamie Fox",
                    "role": "Product Designer",
                    "stage": "offer",
                    "recruiter": "Lena Brandt",
                },
                {
                    "candidate_id": "CAND-1003",
                    "name": "Sasha Ito",
                    "role": "Account Executive",
                    "stage": "application review",
                    "recruiter": "Kim Osei",
                },
            ),
        ),
        classify_step="classify_request",
        labels=(
            LabelTemplate(
                "application_status",
                "Where an application stands.",
                ("application", "status", "applied", "heard back", "update on"),
                (
                    "{id} applied three weeks ago and has not heard back on the application status.",
                    "Can I get an update on the application for {id}?",
                ),
            ),
            LabelTemplate(
                "interview_scheduling",
                "Booking or moving interviews.",
                ("interview", "reschedule", "availability", "time slot", "calendar"),
                (
                    "{id} needs to reschedule the interview; what time slot availability is there next week?",
                    "Please book an interview on the calendar for {id}.",
                ),
            ),
            LabelTemplate(
                "offer_question",
                "Compensation, benefits and offer terms.",
                ("offer", "salary", "compensation", "benefits", "equity", "start date"),
                (
                    "{id} has questions about the offer salary and equity.",
                    "What benefits and start date are in the offer for {id}?",
                ),
            ),
            LabelTemplate(
                "onboarding",
                "First-day logistics and paperwork.",
                ("onboarding", "first day", "paperwork", "orientation", "equipment"),
                (
                    "What paperwork does {id} need before the first day orientation?",
                    "Onboarding question from {id}: when will equipment arrive?",
                ),
            ),
        ),
        assess_step=None,
        dimension=None,
        levels=(),
        retrieve_step="retrieve_policies",
        sources=(
            SourceTemplate(
                "hr_policies",
                "Recruiting, interview and onboarding policies.",
                "Recruiting Policy",
                (
                    (
                        "Communication",
                        "Candidates receive an application status update within 10 business days. Never share interview feedback verbatim or disclose other candidates. Salary and equity details are discussed only by the recruiter.",
                    ),
                    (
                        "Interviews",
                        "Interviews can be rescheduled once without approval. Panel availability is managed in the recruiting calendar.",
                    ),
                    (
                        "Onboarding",
                        "New starters complete paperwork in the HR portal before the first day. Equipment ships 5 business days before the start date and orientation runs every Monday.",
                    ),
                ),
                ("hr polic(y|ies)", "polic(y|ies)", "handbook"),
            ),
            SourceTemplate(
                "job_descriptions",
                "Approved job descriptions and hiring stages.",
                "Job Descriptions",
                (
                    (
                        "Senior Data Engineer",
                        "Builds data pipelines. Stages: application review, recruiter screen, technical interview, panel, offer.",
                    ),
                    (
                        "Product Designer",
                        "Owns end-to-end design. Stages: portfolio review, design exercise, panel, offer.",
                    ),
                ),
                ("job descriptions?", "roles?"),
            ),
        ),
        lookup_step="lookup_candidate",
        draft_step="prepare_action",
        tools=(
            ToolTemplate(
                "candidate_lookup",
                "read",
                "Look up a candidate's role, stage and recruiter.",
                (("candidate_id", "string", "Candidate identifier, for example CAND-1001.", True),),
                ("candidate (status|details|lookup|records?)", "application status"),
                True,
            ),
            ToolTemplate(
                "interview_slots_lookup",
                "read",
                "List available interview slots for the candidate's role.",
                (("candidate_id", "string", "Candidate identifier, for example CAND-1001.", True),),
                ("availability", "slots?", "calendar"),
            ),
            ToolTemplate(
                "draft_candidate_email",
                "draft",
                "Draft an email to the candidate.",
                (
                    ("candidate_id", "string", "Candidate identifier, for example CAND-1001.", True),
                    ("subject", "string", "Email subject.", True),
                    ("body", "string", "Email body.", True),
                ),
                ("emails?", "messages?", "draft"),
                True,
            ),
            ToolTemplate(
                "schedule_interview",
                "execute",
                "Book an interview slot on the recruiting calendar.",
                (
                    ("candidate_id", "string", "Candidate identifier, for example CAND-1001.", True),
                    ("slot", "string", "Requested slot.", True),
                ),
                ("schedul", "book .{0,20}interviews?"),
            ),
        ),
        safety_notes=("Never disclose other candidates, interview feedback or protected characteristics.",),
    ),
    DomainPack(
        key="accounts_payable",
        title="Accounts payable",
        detect=(
            (r"\binvoices?\b", 3),
            (r"\baccounts payable\b|\bap\b", 3),
            (r"\bvendors?|suppliers?\b", 2),
            (r"\bpurchase orders?\b|\bpo\b", 2),
            (r"\bpayments?\b", 1),
        ),
        agent_name="invoice_processor",
        role="accounts payable agent",
        objective="Process vendor invoices with three-way matching and approval before payment.",
        description=(
            "Classifies accounts payable requests, looks up invoices, vendors and purchase orders, retrieves AP "
            "policy and vendor contracts, flags discrepancies and duplicates, and drafts vendor emails and "
            "payment schedules that require approval."
        ),
        entity=EntityTemplate(
            noun="invoice",
            id_param="invoice_id",
            id_prefix="INV",
            records=(
                {
                    "invoice_id": "INV-1001",
                    "vendor": "Acme Office Supply",
                    "amount": 1840.50,
                    "currency": "USD",
                    "po_number": "PO-7781",
                    "status": "received",
                    "due_date": "2026-11-15",
                },
                {
                    "invoice_id": "INV-1002",
                    "vendor": "Northline Logistics",
                    "amount": 12600.00,
                    "currency": "USD",
                    "po_number": "PO-7790",
                    "status": "on_hold",
                    "due_date": "2026-11-02",
                },
                {
                    "invoice_id": "INV-1003",
                    "vendor": "Brightlabs Consulting",
                    "amount": 9200.00,
                    "currency": "USD",
                    "po_number": None,
                    "status": "received",
                    "due_date": "2026-12-01",
                },
            ),
        ),
        classify_step="classify_request",
        labels=(
            LabelTemplate(
                "invoice_submission",
                "New invoices submitted for processing.",
                ("new invoice", "submitted", "attached invoice", "please process", "bill"),
                (
                    "Please process the attached invoice {id}; it was submitted yesterday.",
                    "New invoice {id} submitted for the October bill.",
                ),
            ),
            LabelTemplate(
                "payment_status",
                "When an invoice will be paid.",
                ("paid", "payment status", "remittance", "when will", "overdue"),
                (
                    "When will invoice {id} be paid? It is now overdue.",
                    "Vendor asks for the payment status and remittance for {id}.",
                ),
            ),
            LabelTemplate(
                "discrepancy",
                "Amount or quantity mismatch against the PO.",
                ("mismatch", "discrepancy", "does not match", "wrong amount", "price difference", "quantity"),
                (
                    "Invoice {id} does not match the purchase order; there is a price difference.",
                    "The quantity on {id} is a mismatch versus what we received.",
                ),
            ),
            LabelTemplate(
                "duplicate_invoice",
                "Possible duplicate submissions.",
                ("duplicate", "twice", "already received", "same invoice", "resubmitted"),
                (
                    "I think {id} is a duplicate; we already received the same invoice.",
                    "Vendor resubmitted {id} twice this month.",
                ),
            ),
            LabelTemplate(
                "vendor_update",
                "Bank detail or contact changes.",
                ("bank details", "change of address", "new account", "vendor details", "contact change"),
                (
                    "The vendor for {id} sent new bank details and a change of address.",
                    "Please update vendor details; they have a new account number for {id}.",
                ),
            ),
        ),
        assess_step="assess_risk",
        dimension="risk",
        levels=(
            LabelTemplate("low", "Routine; matches PO and contract.", ("routine", "matches", "standard")),
            LabelTemplate("medium", "Minor variance or missing reference.", ("missing", "variance", "late")),
            LabelTemplate(
                "high",
                "Large variance, duplicate or overdue.",
                ("duplicate", "overdue", "large", "wrong amount"),
            ),
            LabelTemplate(
                "critical",
                "Possible fraud such as bank detail changes.",
                ("bank details", "new account", "urgent payment", "fraud"),
            ),
        ),
        retrieve_step="retrieve_policies",
        sources=(
            SourceTemplate(
                "ap_policies",
                "Accounts payable controls and payment policy.",
                "Accounts Payable Policy",
                (
                    (
                        "Three-way match",
                        "Invoices are paid only when the invoice, purchase order and goods receipt match. A price difference above 2 percent or any quantity mismatch is a discrepancy that must be resolved with the vendor.",
                    ),
                    (
                        "Duplicates",
                        "Invoices with the same vendor, amount and date within 90 days are held as possible duplicates.",
                    ),
                    (
                        "Bank detail changes",
                        "Vendor bank detail changes are a fraud risk. Verify by phone using the number on file, never the number in the email, and require approval from the controller.",
                    ),
                    (
                        "Payment terms",
                        "Standard terms are net 30. Overdue invoices are prioritised in the next payment run after approval.",
                    ),
                ),
                ("polic(y|ies)", "controls?", "procedure"),
            ),
            SourceTemplate(
                "vendor_contracts",
                "Vendor contracts and agreed pricing.",
                "Vendor Contract Summaries",
                (
                    (
                        "Acme Office Supply",
                        "Fixed price catalogue; net 30; volume discount of 5 percent above 10,000 dollars per quarter.",
                    ),
                    (
                        "Northline Logistics",
                        "Freight billed per pallet; fuel surcharge capped at 8 percent; disputes within 15 days.",
                    ),
                ),
                ("contracts?", "agreements?", "pricing"),
            ),
        ),
        lookup_step="lookup_invoice",
        draft_step="prepare_action",
        tools=(
            ToolTemplate(
                "invoice_lookup",
                "read",
                "Look up an invoice's vendor, amount, PO number, status and due date.",
                (("invoice_id", "string", "Invoice identifier, for example INV-1001.", True),),
                ("look ?up .{0,20}invoices?", "invoice (details|status|lookup)"),
                True,
            ),
            ToolTemplate(
                "purchase_order_lookup",
                "read",
                "Look up the purchase order and goods receipt linked to an invoice.",
                (("invoice_id", "string", "Invoice identifier, for example INV-1001.", True),),
                ("purchase orders?", "\\bpo\\b", "three-?way match"),
            ),
            ToolTemplate(
                "draft_vendor_email",
                "draft",
                "Draft an email to the vendor about the invoice.",
                (
                    ("invoice_id", "string", "Invoice identifier, for example INV-1001.", True),
                    ("subject", "string", "Email subject.", True),
                    ("body", "string", "Email body.", True),
                ),
                ("vendor (emails?|messages?)", "draft", "emails?"),
                True,
            ),
            ToolTemplate(
                "schedule_payment",
                "execute",
                "Schedule an approved invoice for the next payment run.",
                (
                    ("invoice_id", "string", "Invoice identifier, for example INV-1001.", True),
                    ("amount", "number", "Amount to pay.", True),
                ),
                ("schedul.{0,20}payments?", "pay (the )?invoices?", "payment runs?"),
            ),
        ),
        safety_notes=("Never change vendor bank details or release payments without controller approval.",),
    ),
    DomainPack(
        key="sales_leads",
        title="Sales lead qualification",
        detect=(
            (r"\bleads?\b", 3),
            (r"\bsales\b", 2),
            (r"\bcrm\b", 2),
            (r"\bprospects?\b", 2),
            (r"\boutreach\b", 2),
            (r"\bqualif(y|ication)\b", 2),
        ),
        agent_name="lead_qualifier",
        role="sales lead qualification agent",
        objective="Qualify inbound leads, enrich them and prepare approved outreach.",
        description=(
            "Classifies inbound lead intent, assesses fit, looks up CRM and enrichment data, retrieves the "
            "product catalogue and sales playbook, and drafts outreach emails and CRM updates that a sales "
            "representative approves before they are sent."
        ),
        entity=EntityTemplate(
            noun="lead",
            id_param="lead_id",
            id_prefix="LEAD",
            records=(
                {
                    "lead_id": "LEAD-1001",
                    "company": "Orbit Freight",
                    "employees": 850,
                    "industry": "logistics",
                    "source": "webinar",
                    "owner": "Marta Silva",
                },
                {
                    "lead_id": "LEAD-1002",
                    "company": "Greenleaf Dental",
                    "employees": 35,
                    "industry": "healthcare",
                    "source": "website",
                    "owner": "unassigned",
                },
                {
                    "lead_id": "LEAD-1003",
                    "company": "Quantum Retail Group",
                    "employees": 4200,
                    "industry": "retail",
                    "source": "referral",
                    "owner": "Ben Clarke",
                },
            ),
        ),
        classify_step="classify_intent",
        labels=(
            LabelTemplate(
                "demo_request",
                "Wants a product demo.",
                ("demo", "walkthrough", "see the product", "trial"),
                (
                    "{id} would like a demo walkthrough of the product next week.",
                    "Can we see the product in a trial? Request from {id}.",
                ),
            ),
            LabelTemplate(
                "pricing_question",
                "Asks about pricing or quotes.",
                ("pricing", "price", "quote", "cost", "discount"),
                (
                    "{id} asked for a pricing quote for 200 seats.",
                    "What does it cost and is there a discount? From {id}.",
                ),
            ),
            LabelTemplate(
                "partnership",
                "Partnership or reseller interest.",
                ("partner", "partnership", "reseller", "integration partner", "affiliate"),
                ("{id} is interested in a reseller partnership.", "Integration partner inquiry from {id}."),
            ),
            LabelTemplate(
                "support_request",
                "Existing customer needing support.",
                ("support", "broken", "not working", "help with my account", "bug"),
                (
                    "{id} says the export is broken and needs support.",
                    "Help with my account please, the bug is back. ({id})",
                ),
            ),
        ),
        assess_step="assess_fit",
        dimension="fit",
        levels=(
            LabelTemplate("cold", "Poor fit or no buying signal.", ("student", "just browsing", "no budget")),
            LabelTemplate("warm", "Some fit, unclear timeline.", ("exploring", "next year", "evaluating")),
            LabelTemplate(
                "hot",
                "Strong fit with budget and timeline.",
                ("budget approved", "this quarter", "ready to buy", "seats"),
            ),
        ),
        retrieve_step="retrieve_playbook",
        sources=(
            SourceTemplate(
                "product_catalog",
                "Product tiers, pricing bands and packaging.",
                "Product Catalogue",
                (
                    (
                        "Tiers",
                        "Starter covers up to 10 seats. Business covers 11 to 500 seats with SSO. Enterprise is above 500 seats with a dedicated success manager. Discounts above 15 percent need sales director approval.",
                    ),
                    (
                        "Demos and trials",
                        "Demos are 30 minutes and booked through the shared sales calendar. Trials last 14 days.",
                    ),
                ),
                ("catalog(ue)?", "pricing", "products?"),
            ),
            SourceTemplate(
                "sales_playbook",
                "Qualification criteria and outreach guidelines.",
                "Sales Playbook",
                (
                    (
                        "Qualification",
                        "A hot lead has budget approved, a timeline this quarter and more than 50 seats. Partnerships are routed to the partner team. Existing customers asking for support are routed to support, not sales.",
                    ),
                    (
                        "Outreach",
                        "First outreach within 4 business hours for hot leads. Never send pricing in writing above list discount bands without approval.",
                    ),
                ),
                ("playbook", "qualification criteria", "guidelines"),
            ),
        ),
        lookup_step="lookup_lead",
        draft_step="prepare_outreach",
        tools=(
            ToolTemplate(
                "crm_lead_lookup",
                "read",
                "Look up a lead in the CRM.",
                (("lead_id", "string", "Lead identifier, for example LEAD-1001.", True),),
                ("crm", "lead (details|lookup|records?)"),
                True,
            ),
            ToolTemplate(
                "company_enrichment",
                "read",
                "Enrich the lead's company with firmographic data.",
                (("lead_id", "string", "Lead identifier, for example LEAD-1001.", True),),
                ("enrich", "firmographic"),
            ),
            ToolTemplate(
                "draft_outreach_email",
                "draft",
                "Draft a personalised outreach email.",
                (
                    ("lead_id", "string", "Lead identifier, for example LEAD-1001.", True),
                    ("subject", "string", "Email subject.", True),
                    ("body", "string", "Email body.", True),
                ),
                ("outreach", "emails?", "draft"),
                True,
            ),
            ToolTemplate(
                "update_crm_lead",
                "execute",
                "Update the lead's stage and owner in the CRM.",
                (
                    ("lead_id", "string", "Lead identifier, for example LEAD-1001.", True),
                    ("stage", "string", "New lead stage.", True),
                ),
                ("update .{0,20}crm", "crm updates?"),
            ),
        ),
    ),
    DomainPack(
        key="ecommerce_orders",
        title="E-commerce orders",
        detect=(
            (r"\borders?\b", 2),
            (r"\be-?commerce|online store|shop(ify)?\b", 3),
            (r"\breturns?\b", 2),
            (r"\brefunds?\b", 1.5),
            (r"\bshipping|delivery|parcel\b", 2),
        ),
        agent_name="order_support",
        role="e-commerce order support agent",
        objective="Resolve order, shipping and return requests with approval for refunds.",
        description=(
            "Classifies shopper requests, looks up orders and shipment tracking, retrieves returns and shipping "
            "policies, and drafts replies, return labels and refunds that require approval before execution."
        ),
        entity=EntityTemplate(
            noun="order",
            id_param="order_id",
            id_prefix="ORD",
            records=(
                {
                    "order_id": "ORD-1001",
                    "customer": "Morgan Hale",
                    "total": 129.90,
                    "currency": "USD",
                    "status": "delivered",
                    "carrier": "UPS",
                    "delivered_on": "2026-10-02",
                },
                {
                    "order_id": "ORD-1002",
                    "customer": "Lee Wong",
                    "total": 54.00,
                    "currency": "USD",
                    "status": "in_transit",
                    "carrier": "FedEx",
                    "delivered_on": None,
                },
                {
                    "order_id": "ORD-1003",
                    "customer": "Ana Duarte",
                    "total": 310.25,
                    "currency": "USD",
                    "status": "processing",
                    "carrier": None,
                    "delivered_on": None,
                },
            ),
        ),
        classify_step="classify_request",
        labels=(
            LabelTemplate(
                "return_request",
                "Customer wants to return items.",
                ("return", "send back", "exchange", "wrong size"),
                (
                    "I want to return the jacket from {id}; it is the wrong size.",
                    "Can I exchange or send back the shoes in {id}?",
                ),
            ),
            LabelTemplate(
                "refund_request",
                "Customer wants money back.",
                ("refund", "money back", "reimburse", "chargeback"),
                (
                    "Please refund {id}; I want my money back.",
                    "I will file a chargeback unless {id} is reimbursed.",
                ),
            ),
            LabelTemplate(
                "shipping_delay",
                "Late or lost shipments.",
                ("late", "delayed", "tracking", "lost parcel", "not arrived", "where is my"),
                (
                    "Where is my parcel? {id} has not arrived and tracking is stuck.",
                    "{id} is delayed; the lost parcel status worries me.",
                ),
            ),
            LabelTemplate(
                "damaged_item",
                "Item arrived damaged or defective.",
                ("damaged", "broken", "defective", "cracked", "missing parts"),
                ("The lamp in {id} arrived cracked and damaged.", "{id} is defective and has missing parts."),
            ),
            LabelTemplate(
                "order_change",
                "Change address, items or cancel before shipping.",
                ("change my order", "cancel my order", "change address", "add item", "update address"),
                (
                    "Please change address on {id} before it ships.",
                    "Can you cancel my order {id} or add item two?",
                ),
            ),
        ),
        assess_step="assess_priority",
        dimension="priority",
        levels=_PRIORITY_LEVELS,
        retrieve_step="retrieve_policies",
        sources=(
            SourceTemplate(
                "returns_policy",
                "Returns, exchanges and refund rules.",
                "Returns and Refunds Policy",
                (
                    (
                        "Returns",
                        "Items can be returned within 30 days of delivery in original condition. Exchanges for a wrong size are free. A prepaid return label is issued after the return is approved.",
                    ),
                    (
                        "Refunds",
                        "Refunds are issued to the original payment method within 5 business days after the return is received. Damaged or defective items are refunded without return when the photo shows the damage. Refunds above 250 dollars need supervisor approval.",
                    ),
                ),
                ("returns? polic", "refund polic", "polic(y|ies)"),
            ),
            SourceTemplate(
                "shipping_policy",
                "Carrier SLAs and lost parcel procedure.",
                "Shipping Policy",
                (
                    (
                        "Delivery times",
                        "Standard delivery takes 3 to 5 business days. A parcel is considered lost after 10 business days without a tracking update; then a replacement or refund is offered.",
                    ),
                    (
                        "Order changes",
                        "Address changes and cancellations are possible while the order status is processing. Once in transit, a carrier intercept may be requested.",
                    ),
                ),
                ("shipping polic", "delivery", "carriers?"),
            ),
        ),
        lookup_step="lookup_order",
        draft_step="prepare_action",
        tools=(
            ToolTemplate(
                "order_lookup",
                "read",
                "Look up an order's items, total, status and carrier.",
                (("order_id", "string", "Order identifier, for example ORD-1001.", True),),
                ("order (details|status|lookup)", "look ?up .{0,20}orders?"),
                True,
            ),
            ToolTemplate(
                "shipment_tracking",
                "read",
                "Read carrier tracking events for an order.",
                (("order_id", "string", "Order identifier, for example ORD-1001.", True),),
                ("tracking", "shipments?"),
            ),
            ToolTemplate(
                "draft_customer_reply",
                "draft",
                "Draft a reply to the shopper.",
                (
                    ("order_id", "string", "Order identifier, for example ORD-1001.", True),
                    ("subject", "string", "Reply subject.", True),
                    ("body", "string", "Reply body.", True),
                ),
                ("repl(y|ies)", "draft", "responses?"),
                True,
            ),
            ToolTemplate(
                "issue_refund",
                "execute",
                "Issue a refund to the original payment method.",
                (
                    ("order_id", "string", "Order identifier, for example ORD-1001.", True),
                    ("amount", "number", "Refund amount.", True),
                    ("reason", "string", "Refund reason.", True),
                ),
                ("refunds?",),
            ),
            ToolTemplate(
                "create_return_label",
                "execute",
                "Create a prepaid return label.",
                (("order_id", "string", "Order identifier, for example ORD-1001.", True),),
                ("return labels?", "returns?"),
            ),
        ),
    ),
    DomainPack(
        key="legal_contracts",
        title="Contract review",
        detect=(
            (r"\bcontracts?\b", 3),
            (r"\blegal\b", 2),
            (r"\bclauses?\b", 2),
            (r"\bnda|msa|dpa|redlines?\b", 3),
            (r"\bcounterpart(y|ies)\b", 2),
        ),
        agent_name="contract_reviewer",
        role="contract review assistant",
        objective="Triage and summarise contracts against the playbook, routing risk to legal counsel.",
        description=(
            "Classifies incoming contracts, assesses risk against the contract playbook and clause library, "
            "looks up contract and counterparty records, and drafts redline summaries for counsel. It does not "
            "provide legal advice and routes contracts for signature only after approval."
        ),
        entity=EntityTemplate(
            noun="contract",
            id_param="contract_id",
            id_prefix="CTR",
            records=(
                {
                    "contract_id": "CTR-1001",
                    "type": "NDA",
                    "counterparty": "Vertex Labs",
                    "value": 0,
                    "term_months": 24,
                    "governing_law": "New York",
                },
                {
                    "contract_id": "CTR-1002",
                    "type": "MSA",
                    "counterparty": "Cobalt Systems",
                    "value": 480000,
                    "term_months": 36,
                    "governing_law": "Delaware",
                },
                {
                    "contract_id": "CTR-1003",
                    "type": "DPA",
                    "counterparty": "Lumen Health",
                    "value": 0,
                    "term_months": 12,
                    "governing_law": "Ireland",
                },
            ),
        ),
        classify_step="classify_contract",
        labels=(
            LabelTemplate(
                "nda",
                "Non-disclosure agreements.",
                ("nda", "non-disclosure", "confidentiality agreement", "mutual confidentiality"),
                (
                    "Please review the mutual NDA in {id}.",
                    "{id} is a non-disclosure agreement from a new vendor.",
                ),
            ),
            LabelTemplate(
                "msa",
                "Master services agreements.",
                ("msa", "master services", "master agreement", "services agreement"),
                (
                    "{id} is a master services agreement with liability caps to check.",
                    "Review the MSA terms in {id}.",
                ),
            ),
            LabelTemplate(
                "dpa",
                "Data processing agreements.",
                ("dpa", "data processing", "gdpr", "subprocessor", "personal data"),
                (
                    "{id} is a data processing addendum covering GDPR subprocessors.",
                    "Check personal data terms in the DPA {id}.",
                ),
            ),
            LabelTemplate(
                "amendment",
                "Amendments and renewals.",
                ("amendment", "renewal", "extension", "addendum to extend"),
                (
                    "{id} is an amendment extending the term with a renewal price change.",
                    "Contract extension request under {id}.",
                ),
            ),
        ),
        assess_step="assess_risk",
        dimension="risk",
        levels=(
            LabelTemplate("low", "Standard terms.", ("standard", "template", "mutual")),
            LabelTemplate("medium", "Minor deviations.", ("deviation", "modified", "non-standard")),
            LabelTemplate(
                "high",
                "Material deviations such as uncapped liability.",
                ("uncapped", "unlimited liability", "indemnify", "exclusive"),
            ),
            LabelTemplate(
                "critical",
                "Unacceptable terms or regulatory exposure.",
                ("illegal", "sanctions", "unlimited indemnity", "waive all rights"),
            ),
        ),
        retrieve_step="retrieve_playbook",
        sources=(
            SourceTemplate(
                "contract_playbook",
                "Negotiation positions and fallback clauses.",
                "Contract Playbook",
                (
                    (
                        "Liability",
                        "Liability is capped at 12 months of fees. Uncapped or unlimited liability is a high risk deviation that must go to counsel. Mutual indemnity only for IP infringement.",
                    ),
                    (
                        "Confidentiality",
                        "Mutual NDAs on our template with a 2 year term are standard. One-way NDAs need counsel review.",
                    ),
                    (
                        "Data protection",
                        "DPAs must list subprocessors and include standard contractual clauses for transfers outside the EU.",
                    ),
                ),
                ("playbook", "negotiation", "positions"),
            ),
            SourceTemplate(
                "clause_library",
                "Approved clause language.",
                "Clause Library",
                (
                    (
                        "Termination",
                        "Either party may terminate for convenience with 30 days notice. Auto-renewal terms must allow non-renewal notice of at least 60 days.",
                    ),
                    (
                        "Governing law",
                        "Preferred governing law is New York or Delaware. Other jurisdictions need counsel approval.",
                    ),
                ),
                ("clause library", "clauses?", "templates?"),
            ),
        ),
        lookup_step="lookup_contract",
        draft_step="prepare_summary",
        tools=(
            ToolTemplate(
                "contract_lookup",
                "read",
                "Look up a contract's type, counterparty, value, term and governing law.",
                (("contract_id", "string", "Contract identifier, for example CTR-1001.", True),),
                ("contract (records?|details|lookup)", "look ?up .{0,20}contracts?"),
                True,
            ),
            ToolTemplate(
                "counterparty_lookup",
                "read",
                "Look up counterparty history and sanctions screening.",
                (("contract_id", "string", "Contract identifier, for example CTR-1001.", True),),
                ("counterpart(y|ies)", "sanctions"),
            ),
            ToolTemplate(
                "draft_redline_summary",
                "draft",
                "Draft a redline summary for counsel.",
                (
                    ("contract_id", "string", "Contract identifier, for example CTR-1001.", True),
                    ("summary", "string", "Summary of deviations.", True),
                ),
                ("redlines?", "summar", "draft"),
                True,
            ),
            ToolTemplate(
                "route_for_signature",
                "execute",
                "Route the approved contract for e-signature.",
                (("contract_id", "string", "Contract identifier, for example CTR-1001.", True),),
                ("signature", "e-?sign"),
            ),
        ),
        safety_notes=(
            "Do not provide legal advice; summarise against the playbook and route decisions to counsel.",
        ),
    ),
)

GENERAL_PACK = DomainPack(
    key="general",
    title="General assistant",
    detect=(),
    agent_name="operations_assistant",
    role="operations assistant",
    objective="Handle incoming requests with verified context and approval for side effects.",
    description=(
        "Classifies incoming requests, assesses urgency, retrieves approved knowledge, looks up records and "
        "prepares responses. Any action with side effects requires explicit human approval."
    ),
    entity=EntityTemplate(
        noun="record",
        id_param="record_id",
        id_prefix="REC",
        records=(
            {"record_id": "REC-1001", "title": "Office relocation", "owner": "Facilities", "status": "open"},
            {
                "record_id": "REC-1002",
                "title": "Quarterly report",
                "owner": "Finance",
                "status": "in_progress",
            },
            {
                "record_id": "REC-1003",
                "title": "Vendor onboarding",
                "owner": "Procurement",
                "status": "closed",
            },
        ),
    ),
    classify_step="classify_request",
    labels=(
        LabelTemplate(
            "request",
            "Asks for something to be done.",
            ("please", "request", "need", "could you", "can you"),
            ("Please update {id}; I need the owner changed.", "Could you request a review of {id}?"),
        ),
        LabelTemplate(
            "question",
            "Asks for information.",
            ("what", "how", "why", "when", "question"),
            ("What is the current state of {id} and when is it due?", "Question: how was {id} approved?"),
        ),
        LabelTemplate(
            "complaint",
            "Reports dissatisfaction.",
            ("complaint", "unhappy", "disappointed", "unacceptable", "frustrated"),
            (
                "This is unacceptable; I am frustrated with how {id} was handled.",
                "Complaint about {id}: we are disappointed.",
            ),
        ),
        LabelTemplate("other", "Anything else.", ()),
    ),
    assess_step="assess_urgency",
    dimension="urgency",
    levels=_URGENCY_LEVELS,
    retrieve_step="retrieve_knowledge",
    sources=(
        SourceTemplate(
            "knowledge_base",
            "Approved reference material for the team.",
            "Team Knowledge Base",
            (
                (
                    "Requests",
                    "Requests are acknowledged within one business day. Ownership changes need the current owner's agreement.",
                ),
                (
                    "Questions",
                    "Answers must cite the knowledge base. When information is missing, say so and route the question to the record owner.",
                ),
            ),
        ),
        SourceTemplate(
            "operating_policies",
            "Operating policies and escalation rules.",
            "Operating Policies",
            (
                (
                    "Complaints",
                    "Complaints are escalated to the team lead within 4 hours. Apologise once, state facts and the next step.",
                ),
                (
                    "Urgent issues",
                    "Emergencies, safety risks or legal exposure are escalated immediately by phone.",
                ),
            ),
        ),
    ),
    lookup_step="lookup_record",
    draft_step="prepare_response",
    tools=(
        ToolTemplate(
            "record_lookup",
            "read",
            "Look up a record by identifier.",
            (("record_id", "string", "Record identifier, for example REC-1001.", True),),
            (),
            True,
        ),
        ToolTemplate(
            "draft_response",
            "draft",
            "Draft a response for review.",
            (
                ("record_id", "string", "Record identifier, for example REC-1001.", True),
                ("subject", "string", "Subject line.", True),
                ("body", "string", "Response body.", True),
            ),
            (),
            True,
        ),
    ),
)

ALL_PACKS: tuple[DomainPack, ...] = (*PACKS, GENERAL_PACK)
PACKS_BY_KEY: dict[str, DomainPack] = {pack.key: pack for pack in ALL_PACKS}


def get_pack(key: str | None) -> DomainPack:
    return PACKS_BY_KEY.get(key or "general", GENERAL_PACK)
