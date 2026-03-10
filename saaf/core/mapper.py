"""
Deterministic framework mapper — no API calls.

Given an AuditInput, returns the frameworks and regulations in scope.
This is unit-testable and cheap; it runs before any Claude API call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from saaf.core.models import AuditInput
from saaf.knowledge.frameworks import FRAMEWORK_REGISTRY
from saaf.knowledge.regulations import (
    REGULATORY_MATRIX,
    normalise_jurisdiction,
)

_ANY = "*"


@dataclass
class FrameworkMatch:
    key: str
    full_name: str
    description: str
    relevant_domains: list[str]
    rationale: str


@dataclass
class MappingResult:
    resolved_jurisdiction: str
    applicable_framework_keys: list[str]
    framework_matches: list[FrameworkMatch]
    regulation_keys: list[str]


class FrameworkMapper:
    def __init__(self, audit_input: AuditInput) -> None:
        self.input = audit_input
        self.jurisdiction = normalise_jurisdiction(audit_input.country)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def map(self) -> MappingResult:
        reg_keys = self._collect_regulation_keys()
        fw_matches = self._collect_framework_matches(reg_keys)

        # Merge regulation keys with framework-derived keys (deduplicated)
        all_fw_keys = list({m.key for m in fw_matches})

        return MappingResult(
            resolved_jurisdiction=self.jurisdiction,
            applicable_framework_keys=all_fw_keys,
            framework_matches=fw_matches,
            regulation_keys=list(set(reg_keys)),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_regulation_keys(self) -> list[str]:
        """Walk the regulatory matrix and collect all matching keys."""
        collected: set[str] = set()
        jur = self.jurisdiction
        ind = self.input.industry
        lst = self.input.listed_status

        # All combinations of (jurisdiction|*, industry|*, listed_status|*)
        # ordered from least to most specific
        candidates = [
            (_ANY, _ANY, _ANY),
            (jur, _ANY, _ANY),
            (_ANY, ind, _ANY),
            (_ANY, _ANY, lst),
            (jur, ind, _ANY),
            (jur, _ANY, lst),
            (_ANY, ind, lst),
            (jur, ind, lst),
        ]

        for key_tuple in candidates:
            keys = REGULATORY_MATRIX.get(key_tuple, [])
            collected.update(keys)

        return list(collected)

    def _collect_framework_matches(self, reg_keys: list[str]) -> list[FrameworkMatch]:
        """
        Evaluate every framework in the registry against the audit input.
        Returns those that match on topic + industry + listed_status + jurisdiction.
        Always include frameworks identified in the regulatory matrix.
        """
        matches: list[FrameworkMatch] = []
        seen: set[str] = set()

        for fw_key, fw in FRAMEWORK_REGISTRY.items():
            if fw_key in seen:
                continue

            rationale_parts: list[str] = []

            # 1. Topic match
            fw_topics = fw.get("audit_topics", [])
            if _ANY not in fw_topics and self.input.audit_topic not in fw_topics:
                # Only skip if it's not explicitly pulled in by the regulatory matrix
                if fw_key not in reg_keys:
                    continue
                else:
                    rationale_parts.append("Required by regulatory matrix (non-primary topic)")
            else:
                rationale_parts.append(f"Covers audit topic '{self.input.audit_topic}'")

            # 2. Industry match
            fw_industries = fw.get("industries", [_ANY])
            if _ANY not in fw_industries and self.input.industry not in fw_industries:
                if fw_key not in reg_keys:
                    continue
            else:
                if _ANY in fw_industries:
                    rationale_parts.append("Universally applicable across industries")
                else:
                    rationale_parts.append(f"Applicable to '{self.input.industry}' industry")

            # 3. Listed status match
            fw_listed = fw.get("listed_status", [_ANY])
            if _ANY not in fw_listed and self.input.listed_status not in fw_listed:
                if fw_key not in reg_keys:
                    continue
            else:
                if self.input.listed_status in fw_listed:
                    rationale_parts.append(f"Applicable to {self.input.listed_status} entities")

            # 4. Jurisdiction match (if the framework is jurisdiction-restricted)
            fw_jurisdictions = fw.get("jurisdictions")
            extraterritorial = fw.get("extraterritorial", False)

            if fw_jurisdictions:
                jurisdiction_match = self.jurisdiction in fw_jurisdictions
                if not jurisdiction_match and extraterritorial:
                    jurisdiction_match = True
                    rationale_parts.append("Extraterritorial reach (may apply if handling data of residents in that jurisdiction)")
                if not jurisdiction_match and fw_key not in reg_keys:
                    continue
                elif jurisdiction_match:
                    rationale_parts.append(f"Applicable in jurisdiction '{self.jurisdiction}'")

            # 5. Regulatory matrix override
            if fw_key in reg_keys:
                rationale_parts.append("Mandated by jurisdiction/industry regulatory matrix")

            # Filter domains to those relevant to the audit topic
            relevant_domains = self._filter_domains(fw)

            matches.append(FrameworkMatch(
                key=fw_key,
                full_name=fw["full_name"],
                description=fw.get("description", ""),
                relevant_domains=relevant_domains,
                rationale="; ".join(dict.fromkeys(rationale_parts)),  # deduplicate order-preserving
            ))
            seen.add(fw_key)

        # Sort: topic-relevant ones first, then alphabetically by name
        def sort_key(m: FrameworkMatch) -> tuple[int, str]:
            fw = FRAMEWORK_REGISTRY[m.key]
            topics = fw.get("audit_topics", [])
            primary = 0 if (self.input.audit_topic in topics or _ANY in topics) else 1
            return (primary, m.full_name)

        matches.sort(key=sort_key)

        # Cap at 8 frameworks — keep the most relevant (sorted above puts
        # primary-topic matches first, then secondary/regulatory ones).
        return matches[:8]

    def _filter_domains(self, fw: dict) -> list[str]:
        """
        Return the subset of framework domains most relevant to the audit topic.
        For short domain lists, return all. For long ones, do keyword filtering.
        """
        all_domains = fw.get("domains", [])
        if len(all_domains) <= 6:
            return all_domains

        topic = self.input.audit_topic.lower()
        topic_keywords: dict[str, list[str]] = {
            "cybersecurity": [
                "access", "crypt", "incident", "monitor", "security", "network",
                "vulnerability", "patch", "endpoint", "authentication", "protect",
                "detect", "respond", "recover", "govern", "identity",
            ],
            "data privacy": [
                "privacy", "data", "personal", "consent", "breach", "subject",
                "gdpr", "retention", "transfer", "processing", "dpia",
            ],
            "financial reporting": [
                "financial", "reporting", "control", "audit", "coso", "sox",
                "disclosure", "governance", "accuracy", "icfr", "assess",
            ],
            "vendor management": [
                "supplier", "vendor", "third.party", "supply chain", "outsourc",
                "contractor", "procurement", "ict third", "baa",
            ],
            "business continuity": [
                "continu", "recover", "resilience", "backup", "disaster",
                "contingency", "bcm", "bcms", "rpo", "rto",
            ],
            "it general controls": [
                "access", "change", "operations", "config", "audit", "log",
                "identity", "patch", "backup", "network", "secure config",
            ],
            "anti-money laundering": [
                "aml", "kyc", "due diligence", "transaction", "suspicious",
                "cdd", "sar", "sanctions", "beneficial", "monitoring",
            ],
            "esg & sustainability": [
                "climate", "emissions", "environment", "social", "governance",
                "sustainability", "disclosure", "esg", "tcfd", "scope",
            ],
            "operational risk": [
                "risk", "operational", "governance", "control environment",
                "monitoring", "assessment", "framework",
            ],
        }

        keywords = topic_keywords.get(topic, [])
        if not keywords:
            return all_domains

        def domain_matches(d: str) -> bool:
            d_lower = d.lower()
            return any(kw in d_lower for kw in keywords)

        filtered = [d for d in all_domains if domain_matches(d)]
        return filtered if filtered else all_domains[:8]  # fallback to first 8
