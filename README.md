# Compliance Report Generator

Identifies all applicable regulatory frameworks for a financial entity and produces a structured compliance overview to kick off an audit engagement.

## Prerequisites

- Python 3.12 or newer. CI runs the tests on Python 3.12 only (`.github/workflows/tests.yml`).
- An API key for the provider you use, from environment variables only: `ANTHROPIC_API_KEY` (default provider), `OPENAI_API_KEY`, or `SAAF_API_KEY` (see *Choosing a model or endpoint*). `--dry-run` needs no key, and neither does the `openai` provider with a custom endpoint (e.g. a local model). `.env` is git-ignored.

## How to run

```bash
pip install -r requirements.txt

# Interactive mode
python cli.py

# Non-interactive mode
python cli.py \
  --company "Example Bank N.V." \
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

### Choosing a model or endpoint

The agent is not tied to one model. Two providers are built in:

| Provider | Use for | Key |
|---|---|---|
| `anthropic` (default) | Anthropic Messages API (default model `claude-opus-4-6`, adaptive thinking) | `ANTHROPIC_API_KEY` |
| `openai` | Any OpenAI-compatible `/chat/completions` API: OpenAI, Azure-style gateways, vLLM, Ollama, LiteLLM, LM Studio | `OPENAI_API_KEY` (optional when `--base-url` is set) |

```bash
# Default: Anthropic, key from ANTHROPIC_API_KEY
python cli.py ...

# Local model via Ollama (no key needed)
python cli.py ... --provider openai --model llama3.1 --base-url http://localhost:11434/v1

# Hosted OpenAI-compatible gateway
export OPENAI_API_KEY=...
python cli.py ... --provider openai --model my-model --base-url https://llm.example.com/v1

# Anthropic through a proxy / gateway
python cli.py ... --base-url https://gateway.example.com/anthropic
```

Each setting can also come from the environment, with precedence **flag > environment > default**: `SAAF_PROVIDER`, `SAAF_MODEL`, `SAAF_BASE_URL`, and `SAAF_API_KEY` (overrides the provider-specific key variable). `--base-url` takes either a base URL (`.../v1`) or the full `.../chat/completions` URL.

Notes:
- The company name and engagement details are sent to whatever endpoint you configure (see `--anonymise`). Plain `http://` to a non-local host logs a warning, since the key and data would travel unencrypted. Redirects are never followed, so the key cannot be forwarded to another host.
- Output quality, JSON compliance and clause accuracy vary by model. Every response is validated against the same schema and grounding checks regardless of provider; only `claude-opus-4-6` has been used so far.
- The openai provider sends `max_tokens` and no provider-specific options (no streaming, no thinking mode).

### Audit trail (opt-in)

`--audit-trail-dir DIR` writes `DIR/<report_id>.json` per successful run (inputs, framework keys, provider, model, endpoint host and sanitised URL, call settings, knowledge-base version, attempts, token usage, stop reason, SHA-256 of the prompts, timestamps, raw model response). The endpoint is stored without credentials, query string or fragment. Off by default. The company name is redacted unless `--audit-trail-include-company` is given; the raw response is stored verbatim and may still mention it.

## What it does

1. **Deterministic mapping** — resolves the entity's jurisdiction, industry, and listed status against a knowledge base of 30+ frameworks (DORA, NIS2, GDPR, ISO 27001, SOX, HIPAA, BIO2, and more) with no API call needed (`saaf/core/mapper.py`, `saaf/knowledge/`).
2. **Dynamic prompt construction** — builds a system prompt containing only the selected frameworks, reducing hallucination (`saaf/prompts/system_prompt.py`).
3. **LLM call** — sends the engagement details to the configured model (default Claude `claude-opus-4-6` with adaptive thinking; any OpenAI-compatible endpoint is supported) and retries on transient errors (`saaf/core/agent.py`, `saaf/core/llm/`, one module per provider).
4. **Validation and rendering** — validates the JSON response against Pydantic models and renders a rich terminal report with control objectives, gap analysis, and priority actions (`saaf/core/models.py`, `saaf/output/formatter.py`).

### Dutch government (BIO2)

For country `Netherlands` (also `NL`, `The Netherlands`, `Nederland`) with industry `Government`, the mapping adds the **Baseline Informatiebeveiliging Overheid 2 (BIO2)** on security-related topics (Cybersecurity, IT General Controls, Vendor Management, Business Continuity), alongside the EU frameworks that already apply. The entry cites BIO2 v1.3 (Staatscourant 2026, 7416) and its ISO 27001/27002 structure only; it does not enumerate BIO2's government-specific measures, so clause-level references to them are not grounded. See `AUDIT-CRITERIA.md` for the open questions (notably the status for municipalities).

## Input / output

- **Input**: company name, industry (e.g. `Financial Services`, `Healthcare`), country/jurisdiction, listed status (`Public` / `Private` / `Government`), audit topic (e.g. `Cybersecurity`, `Data Privacy`, `Financial Reporting`)
- **Output**: rich terminal report or JSON listing applicable regulatory frameworks, control objectives, key gaps, and priority remediation actions

## Data flow

Only the five engagement fields (company name, industry, country, listed status, audit topic) are sent to the configured model endpoint (Anthropic's API by default), together with a system prompt built from the mapped frameworks. `--dry-run` sends nothing.

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

## Limitations & human-review gate

The report is **decision support for audit planning**, not an audit conclusion. An auditor must review it before using it in an engagement. Every terminal and JSON report carries a disclaimer that the model cannot omit or rewrite (`DISCLAIMER` in `saaf/core/models.py`). The `--output findings` export does not include it.

- It maps frameworks to a profile. It does not assess the entity's actual compliance.
- Clause references are written by the model and only checked for existence, never for meaning (see *Clause references*).
- The knowledge base is hand-maintained; coverage outside the listed jurisdictions is thin (see *Supported jurisdictions*).
- No test or logged run uses a real model. Model calls in the tests are mocked or served by a local server, so output quality is not evaluated for any provider.
- Real entity names are sent to the model endpoint, a third-party API by default. A warning and an opt-in alias exist, but anonymisation is not the default.
- The full list of known gaps is in `AUDIT-CRITERIA.md` section 5.

## Guardrails

The agent (`cli.py`, `config.py`, `saaf/`) runs no shell commands. No command prohibited by SAAF's `regulatory/guardrails/allowed-commands.md` (`rm`, `sudo`, `curl`, `wget`, `ssh`, `scp`, `chmod`, `chown`, `cron`, runtime `pip install`) appears there. Its only outbound call is to the configured model endpoint. The maintenance scripts in `tools/clause_sources/` are not part of this agent at runtime. A maintainer or a coding agent runs them to prepare a clause-list update (see *Clause references*), and the `Clause sources e2e` workflow runs them weekly and on relevant PRs.

**Known limitation:** those scripts fetch official clause lists directly over HTTPS (`urllib`), not through an approved API connector. They do not yet meet the rule in `allowed-commands.md` that scripts make no outbound connections except through one. Tracked in #49.

## Audit criteria

See [AUDIT-CRITERIA.md](AUDIT-CRITERIA.md) for control objectives, acceptance criteria, known gaps and observability.

## Related plan

[Compliance Report Generator — Rohan Sobha](https://github.com/SAAF-Project/SAAF-Project/blob/main/plans/hackathon-2/rohan-sobha-compliance-report-generator.md) (in SAAF-Project; previously linked from a fork: [Iodine98/SAAF-Project](https://github.com/Iodine98/SAAF-Project/blob/main/plans/hackathon-2/rohan-sobha-compliance-report-generator.md))

## Maintainer and licence

- **Maintainer:** Rohan Sobha (see `AUDIT-CRITERIA.md`). Contact through: rohan@vital-dev.com
- **Licence:** TODO(owner): licence to be decided by Stichting SAAF.

## Part of SAAF Project

[saaf-portal.vercel.app](https://saaf-portal.vercel.app)

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
```

CI (`.github/workflows/tests.yml`) runs the same suite on every pull request and push to `main`, and posts a short test report as a PR comment and job summary. The suite makes no API calls.
