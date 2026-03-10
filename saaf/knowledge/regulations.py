"""
Regulatory matrix — maps (jurisdiction_group, industry, listed_status) tuples
to lists of applicable framework keys from the framework registry.

Jurisdiction aliases normalise country/region inputs to canonical keys.
"""

# ---------------------------------------------------------------------------
# Jurisdiction alias map — maps user inputs to canonical keys
# ---------------------------------------------------------------------------

JURISDICTION_ALIASES: dict[str, str] = {
    # United States
    "US": "US", "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    # United Kingdom
    "UK": "UK", "GB": "UK", "UNITED KINGDOM": "UK", "GREAT BRITAIN": "UK", "ENGLAND": "UK",
    "WALES": "UK", "SCOTLAND": "UK", "NORTHERN IRELAND": "UK",
    # European Union / EEA
    "EU": "EU", "EUROPEAN UNION": "EU", "EEA": "EU",
    "AT": "EU", "AUSTRIA": "EU",
    "BE": "EU", "BELGIUM": "EU",
    "BG": "EU", "BULGARIA": "EU",
    "HR": "EU", "CROATIA": "EU",
    "CY": "EU", "CYPRUS": "EU",
    "CZ": "EU", "CZECH REPUBLIC": "EU", "CZECHIA": "EU",
    "DK": "EU", "DENMARK": "EU",
    "EE": "EU", "ESTONIA": "EU",
    "FI": "EU", "FINLAND": "EU",
    "FR": "EU", "FRANCE": "EU",
    "DE": "EU", "GERMANY": "EU",
    "GR": "EU", "GREECE": "EU",
    "HU": "EU", "HUNGARY": "EU",
    "IE": "EU", "IRELAND": "EU",
    "IT": "EU", "ITALY": "EU",
    "LV": "EU", "LATVIA": "EU",
    "LT": "EU", "LITHUANIA": "EU",
    "LU": "EU", "LUXEMBOURG": "EU",
    "MT": "EU", "MALTA": "EU",
    "NL": "EU", "NETHERLANDS": "EU", "THE NETHERLANDS": "EU",
    "PL": "EU", "POLAND": "EU",
    "PT": "EU", "PORTUGAL": "EU",
    "RO": "EU", "ROMANIA": "EU",
    "SK": "EU", "SLOVAKIA": "EU",
    "SI": "EU", "SLOVENIA": "EU",
    "ES": "EU", "SPAIN": "EU",
    "SE": "EU", "SWEDEN": "EU",
    "IS": "EU", "ICELAND": "EU",
    "LI": "EU", "LIECHTENSTEIN": "EU",
    "NO": "EU", "NORWAY": "EU",
    # Australia
    "AU": "AU", "AUS": "AU", "AUSTRALIA": "AU",
    # Singapore
    "SG": "SG", "SGP": "SG", "SINGAPORE": "SG",
    # Canada
    "CA": "CA", "CAN": "CA", "CANADA": "CA",
    # India
    "IN": "IN", "IND": "IN", "INDIA": "IN",
    # Japan
    "JP": "JP", "JPN": "JP", "JAPAN": "JP",
}

# Wildcard sentinel
_ANY = "*"


def normalise_jurisdiction(country: str) -> str:
    """Return the canonical jurisdiction key, or 'OTHER' if unknown."""
    return JURISDICTION_ALIASES.get(country.upper().strip(), "OTHER")


# ---------------------------------------------------------------------------
# Regulatory matrix
#
# Key tuple: (jurisdiction, industry, listed_status)
# Use _ANY ("*") as wildcard in any position.
# More specific entries take priority but ALL matching entries are combined.
# ---------------------------------------------------------------------------

REGULATORY_MATRIX: dict[tuple[str, str, str], list[str]] = {

    # ── Universal (always apply regardless of jurisdiction) ───────────────
    (_ANY, _ANY, _ANY): [
        "ISO_31000",    # Risk management — universal best practice
    ],

    # ── Universal by audit topic (cross-jurisdiction) ─────────────────────
    # These are handled dynamically in the mapper based on topic, not here.

    # ── US — all industries ───────────────────────────────────────────────
    ("US", _ANY, _ANY): [
        "CCPA_CPRA",    # Extraterritorial reach if touching CA consumers
        "NIST_CSF",
    ],

    ("US", _ANY, "Public"): [
        "SOX",
        "COSO",
    ],

    ("US", "Financial Services", _ANY): [
        "GLBA",
        "PCI_DSS",
        "FATF_AML",
        "NIST_800_53",
    ],

    ("US", "Financial Services", "Public"): [
        "SOX",
        "COSO",
    ],

    ("US", "Healthcare", _ANY): [
        "HIPAA",
        "HITRUST_CSF",
        "PCI_DSS",        # If payment card processing occurs
    ],

    ("US", "Technology", _ANY): [
        "SOC2",
        "CSA_CCM",
        "PCI_DSS",
    ],

    ("US", "Technology", "Public"): [
        "SOX",
        "COSO",
    ],

    ("US", "Retail", _ANY): [
        "PCI_DSS",
    ],

    ("US", "Retail", "Public"): [
        "SOX",
        "COSO",
    ],

    ("US", "Energy", _ANY): [
        "NERC_CIP",
        "NIST_800_53",
    ],

    ("US", "Energy", "Public"): [
        "SOX",
        "COSO",
    ],

    ("US", "Manufacturing", _ANY): [
        "CMMC",           # If defence contractor
    ],

    ("US", "Government", "Government"): [
        "NIST_800_53",
        "CMMC",
    ],

    # ── EU — all industries ───────────────────────────────────────────────
    ("EU", _ANY, _ANY): [
        "GDPR",
        "NIS2",
        "ISO_27001",
    ],

    ("EU", "Financial Services", _ANY): [
        "GDPR",
        "NIS2",
        "DORA",
        "MiFID_II",
        "FATF_AML",
        "PCI_DSS",
    ],

    ("EU", "Financial Services", "Public"): [
        "CSRD_ESRS",
        "TCFD",
        "GRI",
    ],

    ("EU", "Healthcare", _ANY): [
        "GDPR",
        "NIS2",
        "ISO_27001",
    ],

    ("EU", "Technology", _ANY): [
        "GDPR",
        "NIS2",
        "SOC2",
        "CSA_CCM",
    ],

    ("EU", "Energy", _ANY): [
        "GDPR",
        "NIS2",
    ],

    ("EU", _ANY, "Public"): [
        "CSRD_ESRS",
        "TCFD",
        "GRI",
    ],

    # ── UK ────────────────────────────────────────────────────────────────
    ("UK", _ANY, _ANY): [
        "UK_GDPR",
        "ISO_27001",
        "NIST_CSF",
    ],

    ("UK", "Financial Services", _ANY): [
        "UK_GDPR",
        "GLBA",           # If operating in US markets
        "PCI_DSS",
        "FATF_AML",
    ],

    ("UK", "Financial Services", "Public"): [
        "TCFD",
        "GRI",
    ],

    ("UK", _ANY, "Public"): [
        "TCFD",
    ],

    # ── Australia ─────────────────────────────────────────────────────────
    ("AU", _ANY, _ANY): [
        "AU_PRIVACY_ACT",
        "ISO_27001",
        "NIST_CSF",
    ],

    ("AU", "Financial Services", _ANY): [
        "APRA_CPS234",
        "AU_PRIVACY_ACT",
        "FATF_AML",
        "PCI_DSS",
    ],

    ("AU", "Healthcare", _ANY): [
        "AU_PRIVACY_ACT",
    ],

    ("AU", _ANY, "Public"): [
        "TCFD",
        "GRI",
    ],

    # ── Singapore ─────────────────────────────────────────────────────────
    ("SG", _ANY, _ANY): [
        "PDPA_SG",
        "ISO_27001",
        "NIST_CSF",
    ],

    ("SG", "Financial Services", _ANY): [
        "PDPA_SG",
        "FATF_AML",
        "PCI_DSS",
    ],

    # ── Canada ────────────────────────────────────────────────────────────
    ("CA", _ANY, _ANY): [
        "ISO_27001",
        "NIST_CSF",
    ],

    ("CA", "Financial Services", _ANY): [
        "FATF_AML",
        "PCI_DSS",
    ],

    ("CA", "Energy", _ANY): [
        "NERC_CIP",       # Shared with US for bulk electric systems
    ],

    # ── Other / global default ────────────────────────────────────────────
    ("OTHER", _ANY, _ANY): [
        "ISO_27001",
        "NIST_CSF",
        "ISO_22301",
    ],
}
