"""
Framework Registry — static knowledge base of audit/compliance frameworks.

Each entry describes:
  - full_name: official name
  - domains: control domains / chapters
  - audit_topics: which audit topics it covers ("*" = all)
  - industries: which industries it applies to ("*" = universal)
  - listed_status: which listing statuses trigger it ("*" = all)
  - jurisdictions: if present, limits to these canonical jurisdiction keys
  - extraterritorial: if True, applies to any org handling data from that region
  - description: brief explanation for the system prompt
"""

FRAMEWORK_REGISTRY: dict[str, dict] = {

    # ── Universal frameworks ──────────────────────────────────────────────

    "ISO_27001": {
        "full_name": "ISO/IEC 27001:2022 — Information Security Management",
        "description": (
            "The leading international standard for information security management systems (ISMS). "
            "Provides a systematic approach to managing sensitive information through people, "
            "processes, and IT. Annex A contains 93 controls across 4 themes."
        ),
        "domains": [
            "Information Security Policies",
            "Organisation of Information Security",
            "Human Resource Security",
            "Asset Management",
            "Access Control",
            "Cryptography",
            "Physical and Environmental Security",
            "Operations Security",
            "Communications Security",
            "System Acquisition, Development and Maintenance",
            "Supplier Relationships",
            "Information Security Incident Management",
            "Business Continuity Management",
            "Compliance",
        ],
        "audit_topics": ["Cybersecurity", "Data Privacy", "IT General Controls", "Vendor Management", "Business Continuity"],
        "industries": ["*"],
        "listed_status": ["*"],
    },

    "NIST_CSF": {
        "full_name": "NIST Cybersecurity Framework v2.0",
        "description": (
            "A voluntary framework of standards, guidelines, and best practices for managing "
            "cybersecurity risk. Version 2.0 adds a 'Govern' function and expanded supply-chain "
            "guidance. Widely used as a benchmark even outside the US."
        ),
        "domains": ["Govern", "Identify", "Protect", "Detect", "Respond", "Recover"],
        "audit_topics": ["Cybersecurity", "IT General Controls", "Business Continuity", "Vendor Management"],
        "industries": ["*"],
        "listed_status": ["*"],
    },

    "COBIT": {
        "full_name": "COBIT 2019 — Control Objectives for Information and Related Technologies",
        "description": (
            "An IT governance and management framework from ISACA covering how IT should be "
            "directed, managed, and monitored. Widely used for IT General Controls audits and "
            "as a bridge between IT and financial/operational governance."
        ),
        "domains": [
            "Evaluate, Direct and Monitor (EDM)",
            "Align, Plan and Organise (APO)",
            "Build, Acquire and Implement (BAI)",
            "Deliver, Service and Support (DSS)",
            "Monitor, Evaluate and Assess (MEA)",
        ],
        "audit_topics": ["IT General Controls", "Financial Reporting", "Vendor Management", "Operational Risk"],
        "industries": ["*"],
        "listed_status": ["*"],
    },

    "ISO_22301": {
        "full_name": "ISO 22301:2019 — Business Continuity Management",
        "description": (
            "International standard for business continuity management systems (BCMS). "
            "Specifies requirements for planning, establishing, implementing, and improving "
            "a BCMS to protect against, reduce the likelihood of, and ensure recovery from "
            "disruptive incidents."
        ),
        "domains": [
            "Context of the Organisation",
            "Leadership and Commitment",
            "Planning (BIA, Risk Assessment)",
            "Support (Resources, Communication)",
            "Operation (BCMS Plans, Exercises)",
            "Performance Evaluation",
            "Improvement",
        ],
        "audit_topics": ["Business Continuity", "Operational Risk"],
        "industries": ["*"],
        "listed_status": ["*"],
    },

    "ISO_31000": {
        "full_name": "ISO 31000:2018 — Risk Management Guidelines",
        "description": (
            "Provides principles, framework, and process for managing risk across any "
            "organisation or sector. Commonly used as the overarching risk management "
            "standard alongside sector-specific frameworks."
        ),
        "domains": [
            "Principles",
            "Framework (Leadership, Integration, Design, Implementation, Evaluation)",
            "Process (Scope, Risk Assessment, Risk Treatment, Communication)",
        ],
        "audit_topics": ["Operational Risk", "Financial Reporting", "Business Continuity"],
        "industries": ["*"],
        "listed_status": ["*"],
    },

    # ── Data Privacy ──────────────────────────────────────────────────────

    "GDPR": {
        "full_name": "General Data Protection Regulation (EU) 2016/679",
        "description": (
            "EU/EEA regulation governing personal data processing. Applies to any organisation "
            "processing personal data of EU/EEA residents, regardless of where the organisation "
            "is based (extraterritorial reach). Key obligations include lawful basis, data subject "
            "rights, DPIAs, 72-hour breach notification, and DPAs with processors."
        ),
        "domains": [
            "Lawful Basis for Processing (Art. 6)",
            "Special Category Data (Art. 9)",
            "Data Subject Rights (Arts. 12–22)",
            "Data Protection by Design and Default (Art. 25)",
            "Records of Processing Activities — RoPA (Art. 30)",
            "Data Protection Impact Assessments — DPIA (Art. 35)",
            "Data Breach Notification — 72-hour rule (Art. 33–34)",
            "Data Processing Agreements / DPAs (Art. 28)",
            "International Data Transfers (Arts. 44–49)",
            "Data Protection Officer — DPO (Arts. 37–39)",
        ],
        "audit_topics": ["Data Privacy", "Cybersecurity", "Vendor Management"],
        "industries": ["*"],
        "listed_status": ["*"],
        "jurisdictions": [
            "EU", "EEA", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE",
            "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
            "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
            "IS", "LI", "NO",  # EEA non-EU
        ],
        "extraterritorial": True,
    },

    "UK_GDPR": {
        "full_name": "UK GDPR & Data Protection Act 2018",
        "description": (
            "Post-Brexit UK equivalent of EU GDPR, retained in UK law. Almost identical in "
            "structure and obligations. Regulated by the ICO. Applies to processing of UK "
            "residents' personal data."
        ),
        "domains": [
            "Lawful Basis for Processing",
            "Data Subject Rights",
            "Data Protection by Design",
            "Data Protection Impact Assessments",
            "Breach Notification — 72-hour rule",
            "Data Processing Agreements",
            "International Data Transfers",
            "Data Protection Officer",
        ],
        "audit_topics": ["Data Privacy", "Cybersecurity", "Vendor Management"],
        "industries": ["*"],
        "listed_status": ["*"],
        "jurisdictions": ["UK", "GB"],
        "extraterritorial": True,
    },

    "CCPA_CPRA": {
        "full_name": "California Consumer Privacy Act / California Privacy Rights Act (CCPA/CPRA)",
        "description": (
            "California state privacy law granting consumers rights over their personal information. "
            "CPRA (2023) strengthened CCPA, adding sensitive personal information rights, opt-out "
            "of sharing, and the California Privacy Protection Agency (CPPA)."
        ),
        "domains": [
            "Consumer Rights (Know, Delete, Opt-Out, Non-Discrimination)",
            "Sensitive Personal Information",
            "Data Minimisation and Retention",
            "Privacy Notice",
            "Vendor Contracts",
            "Security Obligations",
        ],
        "audit_topics": ["Data Privacy", "Vendor Management"],
        "industries": ["*"],
        "listed_status": ["*"],
        "jurisdictions": ["US", "USA", "United States"],
        "extraterritorial": True,
    },

    "PDPA_SG": {
        "full_name": "Personal Data Protection Act 2012 (Singapore)",
        "description": (
            "Singapore's primary data protection legislation, administered by the PDPC. "
            "Governs collection, use, and disclosure of personal data. 2021 amendments "
            "introduced mandatory breach notification, data portability, and higher penalties."
        ),
        "domains": [
            "Consent Obligation",
            "Purpose Limitation Obligation",
            "Notification Obligation",
            "Access and Correction Obligation",
            "Accuracy Obligation",
            "Protection Obligation",
            "Retention Limitation Obligation",
            "Transfer Limitation Obligation",
            "Mandatory Data Breach Notification",
        ],
        "audit_topics": ["Data Privacy", "Cybersecurity"],
        "industries": ["*"],
        "listed_status": ["*"],
        "jurisdictions": ["SG", "SGP", "Singapore"],
    },

    # ── Financial / Capital Markets ───────────────────────────────────────

    "SOX": {
        "full_name": "Sarbanes-Oxley Act 2002 (SOX)",
        "description": (
            "US federal law requiring public companies to implement and assess internal controls "
            "over financial reporting (ICFR). Section 302 requires CEO/CFO certification of "
            "financial statements. Section 404 requires management and auditor assessment of ICFR. "
            "IT General Controls (ITGCs) are critical to SOX compliance."
        ),
        "domains": [
            "Financial Statement Accuracy — CEO/CFO Certification (Sec. 302)",
            "Internal Control over Financial Reporting — ICFR (Sec. 404)",
            "Audit Committee Independence (Sec. 301)",
            "Document Retention (Sec. 802)",
            "Whistleblower Protections (Sec. 806)",
            "IT General Controls — Access, Change Management, Operations",
        ],
        "audit_topics": ["Financial Reporting", "IT General Controls"],
        "industries": [
            "Financial Services", "Technology", "Retail", "Energy",
            "Manufacturing", "Telecommunications", "Real Estate", "Healthcare",
        ],
        "listed_status": ["Public"],
        "jurisdictions": ["US", "USA", "United States"],
    },

    "COSO": {
        "full_name": "COSO Internal Control — Integrated Framework (2013) & ERM (2017)",
        "description": (
            "The dominant framework for designing and evaluating internal controls, widely "
            "used in SOX compliance. The five components are Control Environment, Risk Assessment, "
            "Control Activities, Information & Communication, and Monitoring. The 2017 ERM "
            "framework integrates enterprise risk management with strategy."
        ),
        "domains": [
            "Control Environment",
            "Risk Assessment",
            "Control Activities",
            "Information and Communication",
            "Monitoring Activities",
            "Enterprise Risk Management (ERM 2017)",
        ],
        "audit_topics": ["Financial Reporting", "Operational Risk", "IT General Controls"],
        "industries": ["*"],
        "listed_status": ["Public", "Private"],
    },

    "MiFID_II": {
        "full_name": "Markets in Financial Instruments Directive II (MiFID II / MiFIR)",
        "description": (
            "EU legislation regulating investment firms and trading venues. Key requirements "
            "include best execution, transaction reporting, product governance, client "
            "categorisation, and inducements/conflicts of interest management."
        ),
        "domains": [
            "Client Categorisation",
            "Best Execution",
            "Transaction Reporting",
            "Product Governance",
            "Conflicts of Interest",
            "Inducements",
            "Record Keeping",
        ],
        "audit_topics": ["Financial Reporting", "Operational Risk"],
        "industries": ["Financial Services"],
        "listed_status": ["*"],
        "jurisdictions": [
            "EU", "EEA", "AT", "BE", "DE", "FR", "IE", "IT", "LU", "NL", "ES", "SE",
        ],
    },

    # ── Healthcare ────────────────────────────────────────────────────────

    "HIPAA": {
        "full_name": "Health Insurance Portability and Accountability Act (HIPAA)",
        "description": (
            "US federal law protecting the privacy and security of Protected Health Information "
            "(PHI). Applies to covered entities (healthcare providers, insurers, clearinghouses) "
            "and their business associates. The Security Rule mandates administrative, physical, "
            "and technical safeguards. HITECH (2009) strengthened penalties and breach notification."
        ),
        "domains": [
            "Privacy Rule — PHI Handling and Minimum Necessary",
            "Security Rule — Administrative Safeguards",
            "Security Rule — Physical Safeguards",
            "Security Rule — Technical Safeguards",
            "Breach Notification Rule",
            "Business Associate Agreements (BAAs)",
            "HITECH Act — Enhanced Penalties and EHR Incentives",
        ],
        "audit_topics": ["Data Privacy", "Cybersecurity", "Vendor Management"],
        "industries": ["Healthcare"],
        "listed_status": ["*"],
        "jurisdictions": ["US", "USA", "United States"],
    },

    "HITRUST_CSF": {
        "full_name": "HITRUST Common Security Framework (CSF)",
        "description": (
            "A certifiable framework that harmonises HIPAA, ISO 27001, NIST CSF, PCI DSS, "
            "and other standards for the healthcare industry. Provides a prescriptive, "
            "risk-based approach with three assurance levels (e1, i1, r2)."
        ),
        "domains": [
            "Access Control",
            "Audit Logging and Monitoring",
            "Configuration Management",
            "Contingency Planning",
            "Identification and Authentication",
            "Incident Management",
            "Risk Management",
            "Transmission Protection",
            "Wireless Protection",
        ],
        "audit_topics": ["Cybersecurity", "Data Privacy", "IT General Controls"],
        "industries": ["Healthcare"],
        "listed_status": ["*"],
        "jurisdictions": ["US", "USA", "United States"],
    },

    # ── Payment & Financial Data ──────────────────────────────────────────

    "PCI_DSS": {
        "full_name": "PCI DSS v4.0 — Payment Card Industry Data Security Standard",
        "description": (
            "Mandatory standard for any organisation that stores, processes, or transmits "
            "cardholder data (CHD). Published by the PCI SSC. Version 4.0 (2022) adds "
            "customised implementation options and stronger authentication requirements."
        ),
        "domains": [
            "Req 1–2: Network Security Controls and Secure Configurations",
            "Req 3–4: Account Data Protection and Cryptography",
            "Req 5–6: Malware Protection and Secure Software Development",
            "Req 7–9: Access Control and Physical Security",
            "Req 10–11: Logging, Monitoring, and Security Testing",
            "Req 12: Organisational Security and Policies",
        ],
        "audit_topics": ["Cybersecurity", "Data Privacy", "IT General Controls"],
        "industries": ["Financial Services", "Retail", "Technology", "Healthcare"],
        "listed_status": ["*"],
    },

    "GLBA": {
        "full_name": "Gramm-Leach-Bliley Act (GLBA) / FTC Safeguards Rule",
        "description": (
            "US law requiring financial institutions to explain data-sharing practices and "
            "protect customer NPI (non-public personal information). The FTC Safeguards Rule "
            "(updated 2023) requires a formal written information security programme with "
            "specific technical controls."
        ),
        "domains": [
            "Financial Privacy Rule — Notice and Opt-Out",
            "Safeguards Rule — Written Information Security Programme",
            "Safeguards Rule — Risk Assessment",
            "Safeguards Rule — Access Controls and Encryption",
            "Safeguards Rule — Incident Response",
            "Safeguards Rule — Vendor Oversight",
        ],
        "audit_topics": ["Data Privacy", "Cybersecurity", "Vendor Management"],
        "industries": ["Financial Services"],
        "listed_status": ["*"],
        "jurisdictions": ["US", "USA", "United States"],
    },

    # ── Technology & Cloud ────────────────────────────────────────────────

    "SOC2": {
        "full_name": "SOC 2 Type II — System and Organisation Controls",
        "description": (
            "AICPA attestation standard for service organisations, evaluating controls relevant "
            "to the Trust Services Criteria: Security (mandatory), Availability, Processing "
            "Integrity, Confidentiality, and Privacy. Type II covers a period (typically 12 months)."
        ),
        "domains": [
            "CC1: Control Environment",
            "CC2: Communication and Information",
            "CC3: Risk Assessment",
            "CC4: Monitoring Activities",
            "CC5: Control Activities",
            "CC6: Logical and Physical Access Controls",
            "CC7: System Operations",
            "CC8: Change Management",
            "CC9: Risk Mitigation",
        ],
        "audit_topics": ["Cybersecurity", "Data Privacy", "IT General Controls", "Vendor Management"],
        "industries": ["Technology", "Financial Services", "Healthcare"],
        "listed_status": ["*"],
    },

    "CSA_CCM": {
        "full_name": "Cloud Security Alliance — Cloud Controls Matrix (CCM) v4",
        "description": (
            "A cybersecurity control framework for cloud computing, providing a detailed "
            "understanding of security concepts and principles aligned to cloud service providers. "
            "Maps to ISO 27001, NIST CSF, PCI DSS, HIPAA, and other standards."
        ),
        "domains": [
            "Application and Interface Security",
            "Audit Assurance and Compliance",
            "Business Continuity Management and Operational Resilience",
            "Change Control and Configuration Management",
            "Data Security and Privacy Lifecycle Management",
            "Datacenter Security",
            "Encryption and Key Management",
            "Governance, Risk and Compliance",
            "Human Resources Security",
            "Identity and Access Management",
            "Infrastructure and Virtualisation Security",
            "Interoperability and Portability",
            "Logging and Monitoring",
            "Security Incident Management",
            "Supply Chain Management",
            "Threat and Vulnerability Management",
        ],
        "audit_topics": ["Cybersecurity", "IT General Controls", "Vendor Management"],
        "industries": ["Technology", "Financial Services", "Healthcare"],
        "listed_status": ["*"],
    },

    # ── EU / Digital ──────────────────────────────────────────────────────

    "DORA": {
        "full_name": "Digital Operational Resilience Act (EU) 2022/2554",
        "description": (
            "EU regulation applicable from January 2025 requiring financial entities to strengthen "
            "ICT risk management, resilience testing, incident reporting, and third-party ICT "
            "provider oversight. Applies to banks, insurers, investment firms, payment institutions, "
            "and critical ICT providers serving them."
        ),
        "domains": [
            "ICT Risk Management Framework",
            "ICT-Related Incident Management and Reporting",
            "Digital Operational Resilience Testing (TLPT)",
            "ICT Third-Party Risk Management",
            "Information and Intelligence Sharing",
        ],
        "audit_topics": ["Cybersecurity", "Business Continuity", "Vendor Management", "IT General Controls"],
        "industries": ["Financial Services"],
        "listed_status": ["*"],
        "jurisdictions": [
            "EU", "EEA", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE",
            "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
            "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
        ],
    },

    "NIS2": {
        "full_name": "NIS2 Directive (EU) 2022/2555 — Network and Information Security",
        "description": (
            "EU directive applicable from October 2024 expanding cybersecurity requirements "
            "to a wider range of sectors and entities. Introduces stricter governance, "
            "incident reporting (24-hour initial / 72-hour detailed), supply chain security, "
            "and management body accountability."
        ),
        "domains": [
            "Risk Management Policies",
            "Incident Handling",
            "Business Continuity",
            "Supply Chain Security",
            "Network and Information System Security",
            "Policies on Cryptography",
            "Human Resources Security",
            "Multi-Factor Authentication",
            "Management Body Accountability",
        ],
        "audit_topics": ["Cybersecurity", "Business Continuity", "Vendor Management"],
        "industries": [
            "Energy", "Financial Services", "Healthcare", "Technology",
            "Manufacturing", "Telecommunications", "Government",
        ],
        "listed_status": ["*"],
        "jurisdictions": [
            "EU", "EEA", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE",
            "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
            "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
        ],
    },

    # ── Energy & Critical Infrastructure ─────────────────────────────────

    "NERC_CIP": {
        "full_name": "NERC CIP — Critical Infrastructure Protection Standards",
        "description": (
            "Mandatory reliability standards for bulk electric systems in North America. "
            "CIP-002 through CIP-014 cover asset identification, security management, "
            "personnel training, electronic security perimeters, physical security, "
            "incident reporting, recovery plans, and supply chain risk."
        ),
        "domains": [
            "CIP-002: BES Cyber System Categorisation",
            "CIP-003: Security Management Controls",
            "CIP-004: Personnel and Training",
            "CIP-005: Electronic Security Perimeters",
            "CIP-006: Physical Security",
            "CIP-007: Systems Security Management",
            "CIP-008: Incident Reporting",
            "CIP-009: Recovery Plans",
            "CIP-010: Configuration Change Management",
            "CIP-011: Information Protection",
            "CIP-013: Supply Chain Risk Management",
        ],
        "audit_topics": ["Cybersecurity", "IT General Controls", "Vendor Management"],
        "industries": ["Energy"],
        "listed_status": ["*"],
        "jurisdictions": ["US", "USA", "United States", "CA", "Canada"],
    },

    # ── Government / Federal ──────────────────────────────────────────────

    "NIST_800_53": {
        "full_name": "NIST SP 800-53 Rev 5 — Security and Privacy Controls",
        "description": (
            "Comprehensive catalogue of security and privacy controls for US federal information "
            "systems, required by FISMA. Also widely adopted in critical infrastructure and "
            "defence contracting. Organised into 20 control families."
        ),
        "domains": [
            "Access Control (AC)",
            "Audit and Accountability (AU)",
            "Awareness and Training (AT)",
            "Configuration Management (CM)",
            "Contingency Planning (CP)",
            "Identification and Authentication (IA)",
            "Incident Response (IR)",
            "Maintenance (MA)",
            "Media Protection (MP)",
            "Personnel Security (PS)",
            "Risk Assessment (RA)",
            "System and Communications Protection (SC)",
            "System and Information Integrity (SI)",
        ],
        "audit_topics": ["Cybersecurity", "IT General Controls", "Business Continuity"],
        "industries": ["Government", "Technology", "Energy"],
        "listed_status": ["Government", "Public"],
        "jurisdictions": ["US", "USA", "United States"],
    },

    "CMMC": {
        "full_name": "Cybersecurity Maturity Model Certification (CMMC) 2.0",
        "description": (
            "US Department of Defense framework requiring defence contractors to implement "
            "and certify cybersecurity controls. Level 1 (17 practices), Level 2 (110 practices "
            "aligned to NIST 800-171), Level 3 (additional NIST 800-172 practices)."
        ),
        "domains": [
            "Access Control",
            "Awareness and Training",
            "Audit and Accountability",
            "Configuration Management",
            "Identification and Authentication",
            "Incident Response",
            "Maintenance",
            "Media Protection",
            "Personnel Security",
            "Physical Protection",
            "Risk Assessment",
            "Security Assessment",
            "System and Communications Protection",
            "System and Information Integrity",
        ],
        "audit_topics": ["Cybersecurity", "IT General Controls", "Vendor Management"],
        "industries": ["Manufacturing", "Technology", "Government"],
        "listed_status": ["*"],
        "jurisdictions": ["US", "USA", "United States"],
    },

    # ── Australia ─────────────────────────────────────────────────────────

    "APRA_CPS234": {
        "full_name": "APRA CPS 234 — Information Security (Australia)",
        "description": (
            "Prudential standard from APRA (Australian Prudential Regulation Authority) "
            "requiring APRA-regulated entities (banks, insurers, super funds) to maintain "
            "information security capability and notify APRA of material incidents."
        ),
        "domains": [
            "Information Security Capability",
            "Policy Framework",
            "Information Asset Identification and Classification",
            "Implementation of Controls",
            "Incident Management",
            "Testing Control Effectiveness",
            "Internal Audit",
            "APRA Notification",
        ],
        "audit_topics": ["Cybersecurity", "IT General Controls"],
        "industries": ["Financial Services"],
        "listed_status": ["*"],
        "jurisdictions": ["AU", "AUS", "Australia"],
    },

    "AU_PRIVACY_ACT": {
        "full_name": "Privacy Act 1988 (Australia) — Australian Privacy Principles (APPs)",
        "description": (
            "Australian federal privacy law applying to organisations with annual turnover > "
            "AUD 3M and all health service providers. 13 Australian Privacy Principles (APPs) "
            "cover collection, use, disclosure, and security of personal information. "
            "2023 amendments propose stronger enforcement and a right to erasure."
        ),
        "domains": [
            "APP 1: Open and Transparent Management",
            "APP 3: Collection of Solicited Personal Information",
            "APP 5: Notification of Collection",
            "APP 6: Use and Disclosure",
            "APP 7: Direct Marketing",
            "APP 8: Cross-Border Disclosure",
            "APP 11: Security of Personal Information",
            "APP 12: Access to Personal Information",
            "APP 13: Correction of Personal Information",
            "Notifiable Data Breaches (NDB) Scheme",
        ],
        "audit_topics": ["Data Privacy", "Cybersecurity"],
        "industries": ["*"],
        "listed_status": ["*"],
        "jurisdictions": ["AU", "AUS", "Australia"],
    },

    # ── Anti-Money Laundering ─────────────────────────────────────────────

    "FATF_AML": {
        "full_name": "FATF Recommendations — Anti-Money Laundering / Counter-Terrorist Financing",
        "description": (
            "International standards from the Financial Action Task Force (FATF) on AML/CFT. "
            "Translated into local law (e.g. Bank Secrecy Act / FinCEN in the US, POCA in the UK, "
            "AML-CTF Act in Australia). Requires risk-based customer due diligence, transaction "
            "monitoring, suspicious activity reporting, and record-keeping."
        ),
        "domains": [
            "Risk-Based Approach",
            "Customer Due Diligence (CDD) and KYC",
            "Enhanced Due Diligence (EDD) for High-Risk Customers",
            "Beneficial Ownership Identification",
            "Ongoing Monitoring",
            "Suspicious Activity / Transaction Reporting (SAR/STR)",
            "Record Keeping",
            "Sanctions Screening",
            "Training and Compliance Programme",
        ],
        "audit_topics": ["Anti-Money Laundering"],
        "industries": ["Financial Services"],
        "listed_status": ["*"],
    },

    # ── ESG ───────────────────────────────────────────────────────────────

    "CSRD_ESRS": {
        "full_name": "EU Corporate Sustainability Reporting Directive (CSRD) / ESRS",
        "description": (
            "EU directive requiring large and listed companies to report on sustainability "
            "using European Sustainability Reporting Standards (ESRS). Applies from 2024 "
            "(large PIEs) to 2028 (SMEs). Requires double materiality assessment, limited "
            "assurance, and tagging in XBRL."
        ),
        "domains": [
            "Double Materiality Assessment",
            "General Disclosures (ESRS 2)",
            "Climate Change (E1)",
            "Pollution (E2), Water (E3), Biodiversity (E4), Circular Economy (E5)",
            "Own Workforce (S1), Value Chain Workers (S2)",
            "Business Conduct (G1)",
            "Digital Tagging and Assurance",
        ],
        "audit_topics": ["ESG & Sustainability", "Financial Reporting"],
        "industries": [
            "Financial Services", "Energy", "Manufacturing", "Retail",
            "Technology", "Telecommunications", "Real Estate",
        ],
        "listed_status": ["Public"],
        "jurisdictions": [
            "EU", "EEA", "AT", "BE", "DE", "FR", "IE", "IT", "LU", "NL", "ES", "SE",
        ],
    },

    "GRI": {
        "full_name": "GRI Standards — Global Reporting Initiative",
        "description": (
            "The most widely used global sustainability reporting framework. GRI Standards "
            "enable organisations to report on their economic, environmental, and social impacts. "
            "Often used alongside CSRD/ESRS and TCFD. Updated Universal Standards (GRI 1, 2, 3) "
            "effective 2023."
        ),
        "domains": [
            "GRI 1: Foundation (Reporting Principles)",
            "GRI 2: General Disclosures (Governance, Strategy)",
            "GRI 3: Material Topics",
            "Economic Standards (200 series)",
            "Environmental Standards (300 series — Emissions, Energy, Water, Waste)",
            "Social Standards (400 series — Employment, Health & Safety, Human Rights)",
        ],
        "audit_topics": ["ESG & Sustainability"],
        "industries": ["*"],
        "listed_status": ["Public", "Private"],
    },

    "TCFD": {
        "full_name": "TCFD — Task Force on Climate-related Financial Disclosures",
        "description": (
            "Framework for disclosing climate-related financial risks and opportunities "
            "across four pillars: Governance, Strategy, Risk Management, and Metrics & Targets. "
            "Now incorporated into IFRS S2 (climate) and CSRD/ESRS E1. Mandatory in UK and "
            "increasingly required globally."
        ),
        "domains": [
            "Governance — Board and Management Oversight of Climate Risk",
            "Strategy — Climate Scenarios and Business Impact",
            "Risk Management — Identification, Assessment, Integration",
            "Metrics and Targets — GHG emissions (Scope 1, 2, 3)",
        ],
        "audit_topics": ["ESG & Sustainability", "Financial Reporting"],
        "industries": ["Financial Services", "Energy", "Manufacturing", "Retail", "Technology"],
        "listed_status": ["Public"],
    },
}
