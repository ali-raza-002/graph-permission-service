"""Demo dataset for Lumen Labs, a small product company.

The relationships are chosen so the console has interesting answers to explain:
nested teams, inherited folder access, an org-wide handbook, a public press kit, an
external contractor who can edit but not reshare, and a blocked user.
"""

from __future__ import annotations

from dataclasses import dataclass

ORG = ("lumen", "Lumen Labs")


@dataclass(frozen=True)
class SeedUser:
    handle: str
    name: str
    title: str


@dataclass(frozen=True)
class SeedFolder:
    id: str
    name: str
    description: str
    parent_id: str | None = None


@dataclass(frozen=True)
class SeedDocument:
    id: str
    folder_id: str
    title: str
    owner: str
    body: str


USERS = [
    SeedUser("anne", "Anne Liu", "Staff Engineer, Platform lead"),
    SeedUser("ben", "Ben Okafor", "Product Designer"),
    SeedUser("chloe", "Chloe Martin", "CEO"),
    SeedUser("dev", "Dev Patel", "Software Engineer"),
    SeedUser("erin", "Erin Walsh", "Security Engineer"),
    SeedUser("fatima", "Fatima Noor", "Contractor, Northwind Integrations"),
    SeedUser("gus", "Gus Romero", "Engineering Manager"),
]

TEAMS = [
    ("platform", "Platform"),
    ("engineering", "Engineering"),
    ("design", "Design"),
    ("leadership", "Leadership"),
]

FOLDERS = [
    SeedFolder("handbook", "Company Handbook", "Policies and guides for everyone at Lumen."),
    SeedFolder("engineering", "Engineering", "Design docs, RFCs and on-call material."),
    SeedFolder("rfcs", "RFCs", "Proposals under review.", "engineering"),
    SeedFolder("incidents", "Incident Reviews", "Blameless postmortems.", "engineering"),
    SeedFolder("design", "Design", "Research, specs and the design system."),
    SeedFolder("leadership", "Leadership", "Planning and board material."),
    SeedFolder("partners", "Partner Workspace", "Shared with Northwind Integrations."),
]

DOCUMENTS = [
    SeedDocument(
        "welcome",
        "handbook",
        "Welcome to Lumen Labs",
        "chloe",
        "We build tools that make complex systems legible. This handbook explains how we "
        "work: how decisions get made, where to ask for help, and what we expect from "
        "each other.\n\nYour first week: pair with your onboarding buddy, ship one small "
        "change to production, and read the security policy.",
    ),
    SeedDocument(
        "security-policy",
        "handbook",
        "Security Policy",
        "erin",
        "Access is granted through relationships, never through shared passwords. Every "
        "permission check in our products is answered by Warden and recorded in the "
        "decision log.\n\nReport suspected incidents in #security within 15 minutes.",
    ),
    SeedDocument(
        "press-kit",
        "handbook",
        "Press Kit",
        "chloe",
        "Logos, product screenshots and approved boilerplate. This document is public: "
        "anyone with the link can read it.",
    ),
    SeedDocument(
        "rfc-012-rebac",
        "rfcs",
        "RFC-012: Relationship-based access control",
        "anne",
        "Problem: role checks are scattered across services and drift apart.\n\nProposal: "
        "move every permission decision to a Zanzibar-style service. Tenants describe "
        "their model in a DSL, applications write relationship tuples, and checks are "
        "evaluated against a consistent snapshot.\n\nRollout: shadow mode for two weeks, "
        "comparing decisions with the legacy checks.",
    ),
    SeedDocument(
        "rfc-013-audit",
        "rfcs",
        "RFC-013: Event-sourced audit trail",
        "dev",
        "Every write emits an event keyed by revision. Auditors can replay the store to "
        "any point in time and see exactly who had access.",
    ),
    SeedDocument(
        "oncall-runbook",
        "engineering",
        "On-call Runbook",
        "gus",
        "Pager rotation, escalation paths and the first five commands to run when the "
        "check latency SLO burns.",
    ),
    SeedDocument(
        "pg-failover-review",
        "incidents",
        "2026-08-14 Postgres failover",
        "erin",
        "Impact: 6 minutes of elevated check latency. Root cause: replica promotion while "
        "the revision counter was cached. Fix: consistency tokens on every write path.",
    ),
    SeedDocument(
        "credential-leak-review",
        "incidents",
        "Credential exposure investigation",
        "erin",
        "Restricted while the investigation is open. Engineers involved in the affected "
        "deploy are blocked from this document until it closes.",
    ),
    SeedDocument(
        "design-system-v3",
        "design",
        "Design system v3",
        "ben",
        "Typography moves to the system font stack, a single accent color, and hairline "
        "separators. Components follow platform conventions first.",
    ),
    SeedDocument(
        "onboarding-research",
        "design",
        "Onboarding research synthesis",
        "ben",
        "Twelve interviews. New admins want to see why someone can access a document "
        "before they trust the sharing model.",
    ),
    SeedDocument(
        "fy27-plan",
        "leadership",
        "FY27 planning",
        "chloe",
        "Three bets: enterprise SSO, the permissions console, and partner integrations.",
    ),
    SeedDocument(
        "integration-spec",
        "partners",
        "Northwind integration API spec",
        "fatima",
        "Endpoints, webhooks and the sandbox environment for the Northwind connector.",
    ),
    SeedDocument(
        "partner-sla",
        "partners",
        "Partner SLA draft",
        "anne",
        "Response times, uptime commitments and the escalation matrix for partners.",
    ),
]

_TEAM_TUPLES = [
    "org:lumen#admin@user:chloe",
    *(f"org:lumen#member@user:{h}" for h in ("anne", "ben", "dev", "erin", "gus")),
    "team:platform#lead@user:anne",
    "team:platform#member@user:dev",
    "team:engineering#lead@user:gus",
    "team:engineering#member@team:platform#member",
    "team:engineering#member@user:erin",
    "team:design#member@user:ben",
    "team:leadership#member@user:chloe",
    "team:leadership#member@user:gus",
    *(f"team:{t}#org@org:lumen" for t, _ in TEAMS),
]

_FOLDER_TUPLES = [
    *(f"folder:{f.id}#org@org:lumen" for f in FOLDERS),
    *(f"folder:{f.id}#parent@folder:{f.parent_id}" for f in FOLDERS if f.parent_id),
    "folder:handbook#viewer@org:lumen#member",
    "folder:handbook#owner@user:chloe",
    "folder:engineering#editor@team:engineering#member",
    "folder:engineering#viewer@team:design#member",
    "folder:incidents#viewer@team:leadership#member",
    "folder:design#editor@team:design#member",
    "folder:design#viewer@team:engineering#member",
    "folder:leadership#editor@team:leadership#member",
    "folder:partners#editor@user:fatima",
    "folder:partners#viewer@team:engineering#member",
]

_DOCUMENT_TUPLES = [
    *(f"document:{d.id}#parent@folder:{d.folder_id}" for d in DOCUMENTS),
    *(f"document:{d.id}#org@org:lumen" for d in DOCUMENTS),
    *(f"document:{d.id}#owner@user:{d.owner}" for d in DOCUMENTS),
    "document:press-kit#viewer@user:*",
    "document:credential-leak-review#blocked@user:dev",
    "document:fy27-plan#viewer@user:anne",
    "document:rfc-012-rebac#editor@user:erin",
]

TUPLES = [*_TEAM_TUPLES, *_FOLDER_TUPLES, *_DOCUMENT_TUPLES]

# Checks replayed by the seed script so the decision log and charts have history.
SAMPLE_TRAFFIC = [
    ("document:rfc-012-rebac", "can_view", "user:dev"),
    ("document:rfc-012-rebac", "can_edit", "user:erin"),
    ("document:rfc-012-rebac", "can_share", "user:fatima"),
    ("document:credential-leak-review", "can_view", "user:dev"),
    ("document:credential-leak-review", "can_view", "user:anne"),
    ("document:fy27-plan", "can_view", "user:anne"),
    ("document:fy27-plan", "can_view", "user:ben"),
    ("document:integration-spec", "can_edit", "user:fatima"),
    ("document:integration-spec", "can_share", "user:fatima"),
    ("document:partner-sla", "can_view", "user:fatima"),
    ("document:press-kit", "can_view", "user:visitor"),
    ("document:welcome", "can_view", "user:fatima"),
    ("document:design-system-v3", "can_edit", "user:anne"),
    ("document:design-system-v3", "can_view", "user:anne"),
    ("document:pg-failover-review", "can_view", "user:chloe"),
    ("document:oncall-runbook", "can_delete", "user:chloe"),
    ("document:oncall-runbook", "can_delete", "user:dev"),
    ("folder:engineering", "editor", "user:dev"),
    ("folder:leadership", "viewer", "user:erin"),
]
