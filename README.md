# Compliance Report Generator

Identifies all applicable regulatory frameworks for a financial entity and produces a structured compliance overview to kick off an audit engagement.

## How to run

```bash
pip install -r requirements.txt

# Interactive mode
python cli.py

# Non-interactive mode
python cli.py \
  --company "Dutch National Bank" \
  --industry "Financial Services" \
  --country Netherlands \
  --listed-status Public \
  --audit-topic Cybersecurity

# Dry-run (no API call — preview framework selection only)
python cli.py --company "..." --industry "Financial Services" \
  --country Netherlands --listed-status Public \
  --audit-topic Cybersecurity --dry-run

# JSON output
python cli.py ... --output json

# SAAF finding-schema export (critical gaps and framework key gaps as findings;
# Critical is mapped to High, see saaf/output/findings.py)
python cli.py ... --output findings
```

Requires `ANTHROPIC_API_KEY` set in the environment.

### Audit trail (opt-in)

`--audit-trail-dir DIR` writes `DIR/<report_id>.json` per successful run (inputs, framework keys, model, SHA-256 of the prompts, timestamps, raw model response). Off by default. The company name is redacted unless `--audit-trail-include-company` is given; the raw response is stored verbatim and may still mention it.

## What it does

1. **Deterministic mapping** — resolves the entity's jurisdiction, industry, and listed status against a knowledge base of 30+ frameworks (DORA, NIS2, GDPR, ISO 27001, SOX, HIPAA, and more) with no API call needed (`saaf/core/mapper.py`, `saaf/knowledge/`).
2. **Dynamic prompt construction** — builds a system prompt containing only the selected frameworks, reducing hallucination (`saaf/prompts/system_prompt.py`).
3. **Claude API call** — sends the engagement details to Claude (`claude-opus-4-6`) with adaptive thinking enabled and retries on transient errors (`saaf/core/agent.py`).
4. **Validation and rendering** — validates the JSON response against Pydantic models and renders a rich terminal report with control objectives, gap analysis, and priority actions (`saaf/core/models.py`, `saaf/output/formatter.py`).

## Input / output

- **Input**: company name, industry (e.g. `Financial Services`, `Healthcare`), country/jurisdiction, listed status (`Public` / `Private` / `Government`), audit topic (e.g. `Cybersecurity`, `Data Privacy`, `Financial Reporting`)
- **Output**: rich terminal report or JSON listing applicable regulatory frameworks, control objectives, key gaps, and priority remediation actions

## Data flow

Only the five engagement fields (company name, industry, country, listed status, audit topic) are sent to Anthropic's API, together with a system prompt built from the mapped frameworks. `--dry-run` sends nothing.

- `company_name` is sent **verbatim**. A real (non-dry-run) call prints a warning on stderr; it does not prompt or block. Suppress it with `--yes` (alias `--no-warn`) in non-interactive use.
- `--anonymise` (or `--alias NAME`, which implies it) sends a placeholder (default `Entity A`) instead. The real name stays on your machine, and logs show only the alias. The `audit_input` in the report shown or saved locally has the real name restored, so treat that output as sensitive. Industry, country, listed status and audit topic are still sent.
- Prefer synthetic or anonymised names for testing.

## Supported jurisdictions

The knowledge base targets **US, EU (incl. EEA member countries), UK, Australia and Singapore**. Canada, India and Japan have minimal partial coverage. Any other country resolves to a generic global framework set, so output may be thin. In that case the CLI prints a warning to stderr (also with `--dry-run`), a warning is logged, and the report carries a visible warning (`warnings` field in JSON).

## Clause references

`requirement_source` and `applicable_sections` are written by the model. Where a framework has an official clause list (`saaf/knowledge/clause_data/<KEY>.json`), the agent checks that each cited article, paragraph, section or control **exists**, and records one entry per reference in `reference_checks` (JSON output; summarised in the terminal report). `reference_checks` is computed by the agent and is never requested from the model.

Every entry has `status: "unverified"` and a `confidence` score. Existence is not meaning: even a clause that exists can be cited for the wrong reason, so no reference is ever marked verified and no score reaches 1.0. The score is a fixed heuristic per outcome, not a probability (`CONFIDENCE` in `saaf/core/reference_check.py`):

| `check` | meaning | confidence |
|---|---|---|
| `identifier_found` | cited clause exists in the official list | 0.70 |
| `parent_identifier_found` | cited more finely than the list (e.g. point (b)); the parent exists | 0.60 |
| `framework_not_covered` | mapped framework without a clause list; not checked | 0.30 |
| `no_locator` | framework named but no checkable clause cited | 0.25 |
| `identifier_not_found` | framework covered, clause not in its official list | 0.10 |
| `unmapped_framework` | names no framework in the mapped set | 0.05 |

A mismatch only warns and labels; the report is not rejected. Sub-paragraphs are accepted when the parent exists, but rejected at a level where the list enumerates the siblings (the list holds `art:32(1)`..`(4)`, so `Art. 32(7)` is not found, while `Art. 32(1)(b)` is accepted).

Granularity is the most specific level an auditor can test against without losing the purpose of the legislation, set per framework (`GRANULARITY` in `saaf/knowledge/clauses.py`; the reasoning is in each data file's `granularity_rationale`):

| Framework | Instruments | Validated down to |
|---|---|---|
| GDPR, DORA, NIS2 | Regulation/Directive text | article + numbered paragraph, recitals (NIS2 also Annexes I-II) |
| UK_GDPR | UK GDPR, Data Protection Act 2018 | article/paragraph, recitals; section/subsection, schedule/paragraph |
| MiFID_II | Directive 2014/65/EU (consolidated), MiFIR (consolidated) | article + numbered paragraph, recitals, Directive annexes |
| HIPAA | 45 CFR Parts 160, 164 | standard / implementation specification (CFR paragraph) |
| GLBA | 15 U.S.C. 6801-6809, 6821-6827; 16 CFR 314; 12 CFR 1016 | statute subsection; CFR paragraph. "Section 501(b)" is read as 15 U.S.C. 6801(b) |
| NIST_CSF | CSF 2.0 | subcategory (CSF 1.1 ids such as PR.AC-1 are not valid) |
| NIST_800_53 | SP 800-53 Rev 5 | control and enhancement; withdrawn controls excluded |
| CCPA_CPRA | Cal. Civ. Code 1798.100-1798.199.100 | section (CPPA regulations out of scope) |

Not covered yet (references are labelled `framework_not_covered`, not checked): ISO 27001, COBIT, ISO 22301, ISO 31000, PDPA (SG), SOX, COSO, HITRUST CSF, PCI DSS, SOC 2, CSA CCM, NERC CIP, CMMC, APRA CPS 234, AU Privacy Act, FATF AML, CSRD/ESRS, GRI, TCFD. Several are paywalled (ISO, PCI DSS, HITRUST, COBIT).

Updating the lists: an agent may refresh the data from the official sources, but only through a pull request that cites them. Run the scripts in `tools/clause_sources/` (stdlib only; see `common.py` for the data format), then `python3 -I tools/clause_sources/provenance_table.py` and put its table (`source`, `last_reviewed`) in the PR for a maintainer to check. `last_reviewed` in the data files is the retrieval date, not a maintainer's sign-off.

## Audit criteria

See [AUDIT-CRITERIA.md](AUDIT-CRITERIA.md) for control objectives, acceptance criteria, known gaps and observability.

## Related plan

[Compliance Report Generator — Rohan Sobha](https://github.com/Iodine98/SAAF-Project/blob/main/plans/hackathon-2/rohan-sobha-compliance-report-generator.md)

## Part of SAAF Project

[saaf-portal.vercel.app](https://saaf-portal.vercel.app)

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
```

CI (`.github/workflows/tests.yml`) runs the same suite on every pull request and push to `main`, and posts a short test report as a PR comment and job summary. The suite makes no API calls.
