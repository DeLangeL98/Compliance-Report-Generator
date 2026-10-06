# AUDIT-CRITERIA.md — Compliance Report Generator

> SAAF A2 standard (Audit Criteria & Controls). This document sits next to `README.md`: the README says what the agent does and how to run it; this document says what the agent must be judged against as an auditee.
>
> **Sources used to draft this document:** `README.md`, the hackathon plan (`plans/hackathon-2/rohan-sobha-compliance-report-generator.md` in SAAF-Project), and a read-through of `saaf/core/agent.py`, `saaf/core/models.py`, `saaf/prompts/system_prompt.py`, `config.py`, `cli.py` and `tests/test_saaf.py`. No Session 6 A2 hand-in existed. No logged real run was available, so nothing below is verified by a live run (see section 6).
>
> **Branch note:** `main` is the only live implementation. `origin/rohan-sobha/add-readme` has no diff against `main`.

---

## Metadata

| Field | Value |
|---|---|
| **Agent** | Compliance Report Generator |
| **Repository** | https://github.com/SAAF-Project/Compliance-Report-Generator |
| **Maintainer(s)** | Rohan Sobha |
| **Last reviewed** | 2026-10-06 |
| **Status** | Draft |

## 1. What the agent does

Given an engagement profile (company name, industry, country, listed status, audit topic), the agent deterministically maps the entity to applicable regulatory frameworks from a built-in knowledge base (30+ frameworks), then asks an LLM (default Claude `claude-opus-4-6` with adaptive thinking; any OpenAI-compatible endpoint can be configured with `--provider` / `--model` / `--base-url`) to produce a structured compliance overview: mandatory regulations, per-framework control objectives with testing approaches, typical gaps, and a prioritised action summary. Output is validated against Pydantic models and rendered as a terminal report or JSON. It supports the **planning phase** of an audit engagement (regulatory scoping); it does not assess the entity's actual compliance.

The agent makes LLM calls at runtime, so AI-specific frameworks (EU AI Act, OWASP LLM) are in scope below.

## 2. Control objectives & framework mapping

These describe the agent's own trustworthy behaviour, not the regulations it reports on.

| Control objective | Framework + clause/area | Why relevant |
|---|---|---|
| CO-1 — Framework scoping is grounded: every framework in the output comes from the deterministic knowledge base, and the model cannot introduce frameworks of its own. | OWASP LLM Top 10 — LLM09 Overreliance / LLM01 Prompt Injection (constrained output scope); EU AI Act Art. 15 (accuracy, robustness) | The core risk of this agent is a plausible but invented regulation or clause reaching an audit plan. |
| CO-2 — Output is structurally valid and complete: malformed or schema-violating model output is rejected, not silently repaired or passed on. | EU AI Act Art. 15; COBIT 2019 DSS06 (manage business process controls) | Auditors consume the JSON downstream; invalid output must fail loudly. |
| CO-3 — Output is positioned as decision support: a human-review disclaimer always accompanies the report, and model-generated content is not presented as legal or audit-ready conclusions. | EU AI Act Art. 14 (human oversight) & Art. 13 (transparency); IIA Standard 2310 / 1220 (due professional care, reliance on evidence) | Output is generic to a profile and not tested against real entity evidence. |
| CO-4 — Engagement data and secrets are handled safely: API key only from the environment, and no real entity data is needed to use the agent. | GDPR Art. 5(1)(c) & 32 (minimisation, security); ISO 27001 Annex A 5.17 / 8.24; OWASP LLM06 Sensitive Information Disclosure | Company name and profile are sent to the configured model endpoint, which may be third-party or self-hosted. |
| CO-5 — Runs are traceable and reproducible enough to review: inputs, selected frameworks, provider, model, endpoint, and outcome are logged. | EU AI Act Art. 12 (record-keeping); IIA Standard 2330 (documenting information) | A reviewer must be able to see what produced a report. |

## 3. Acceptance criteria (testable, pass/fail)

**CO-1 — Grounded scoping**
- Given a US, private, Healthcare profile, the agent's mapping includes HIPAA and excludes SOX (`--dry-run`, no API call).
- Given an EU, Financial Services profile, the mapping includes GDPR and DORA.
- Given a Dutch government profile (`Netherlands`, `Government`, a security topic), the mapping includes BIO2 as well as the EU frameworks. Given a German government, a Dutch non-government, or a Dutch government ESG profile, it does not include BIO2 (`tests/test_bio2.py`).
- Given any profile, every `FrameworkMatch` carries a non-empty rationale.
- Given any profile, the system prompt lists only the mapped frameworks and instructs the model not to reference others.
- Given a model response that contains a framework not in the mapped set, the agent rejects it with a `ComplianceReportError` that carries the raw response. After parsing, `ComplianceAgent._check_grounding` compares `framework_assessments[].framework_name` and `mandatory_regulations[].regulation_name` against the mapped frameworks (case-insensitive; the full name, key, name before the dash, and abbreviations in the full name are accepted). **Limitation, stated honestly:** names are matched, not clauses, so a wrong `requirement_source` inside a mapped framework is not caught (see Coverage gaps).

**CO-2 — Valid output**
- Given a response wrapped in markdown fences or surrounded by prose, the agent extracts the JSON object and validates it.
- Given a response with no JSON object, the agent raises `ComplianceReportError` that carries the raw response.
- Given JSON that violates the schema (e.g. an invalid `risk_rating`), the agent raises `ComplianceReportError` and does not return a partial report.
- Given an invalid `--industry`, `--listed-status` or `--audit-topic`, the CLI exits non-zero without calling the API.
- Given a persistent 4xx API error, the agent fails immediately. Given 5xx or connection errors, it retries up to `max_retries` and then fails with `ComplianceReportError`.

**CO-3 — Decision support, not conclusions**
- Given any successful run, the rendered report and the JSON both contain the disclaimer text.
- Given a model response that omits or rewrites `disclaimer`, the output still carries the standard disclaimer. `disclaimer` is excluded from the model-facing schema and forced to `DISCLAIMER` (`saaf/core/models.py`) after validation in `_parse_and_validate`.
- Given any run, the report does not state that the entity is compliant or non-compliant. **Limitation, stated honestly:** only enforced by prompt wording ("typical gaps for this profile"), not by a check.
- Given a country that does not resolve to a known jurisdiction, the CLI prints a warning to stderr (also with `--dry-run`), the agent logs a warning, and the report (terminal and JSON `warnings` field) carries a visible note that coverage is generic. The warning is set by the agent after validation, so a model-supplied `warnings` value is overwritten. **Limitation, stated honestly:** this only signals the gap; coverage was not extended, and Canada, India and Japan resolve to known keys with minimal matrix entries and do not trigger the warning.

**CO-4 — Data and secrets**
- Given the provider's key variable unset (`ANTHROPIC_API_KEY` by default, or `OPENAI_API_KEY` / `SAAF_API_KEY`), a real run exits with a clear configuration error. `--dry-run` works without a key. A key is optional only for the `openai` provider with a custom `--base-url`.
- Given a `--base-url` that is not http(s), has no host, or embeds credentials, the CLI exits with a configuration error. Given plain `http://` to a non-local host, a warning is logged. Redirects from the endpoint are never followed. **Limitation, stated honestly:** a custom endpoint receives the same engagement data and API key as the default one; the agent cannot vouch for what that endpoint does with them.
- Given a scan of tracked files, no API keys or credentials are present. A scan found none on 2026-10-06 (patterns `sk-`, `AKIA`, private-key headers, tracked `.env`).
- Given a run, only the five engagement fields are sent to the API. A real (non-dry-run) call prints a stderr warning that `company_name` is sent verbatim (non-blocking; `--yes` / `--no-warn` suppresses it), and `--anonymise` / `--alias NAME` sends a placeholder instead, with the real name restored only in the locally shown `audit_input` and absent from logs. **Limitation, stated honestly:** anonymisation is opt-in, the default still sends the real name, nothing enforces synthetic names, and the other four fields are still sent.

**CO-5 — Traceability**
- Given a run at default log level, stderr logs the input profile, mapped jurisdiction and framework keys, model name, API duration, token counts, stop reason, and the resulting `report_id`.
- Given a JSON output, it includes `report_id`, `generated_at` and the `audit_input`.
- Given `--audit-trail-dir DIR`, each successful run writes `DIR/<report_id>.json` containing the inputs (company name redacted unless `--audit-trail-include-company`), framework keys, provider, model, endpoint host and sanitised URL, call settings (max tokens, retries, timeout), knowledge-base version, attempts, token usage, stop reason, prompt SHA-256, timestamps and the raw response.
- Given an endpoint URL containing credentials, a query string or a fragment, the audit record contains none of them.
- **Limitation, stated honestly:** the audit trail is opt-in and off by default. Without it, logs go to stderr only and nothing is persisted. The prompt itself is stored only as a hash, the raw response is stored verbatim (and may echo the company name), and runs that fail parsing or validation get no record because no `report_id` exists yet. The recorded endpoint is what the client was configured to call; it does not prove which backend served the request (gateways may route to other models).

## 4. Good output / never do

| A correct output MUST contain | The agent must NEVER |
|---|---|
| ✓ Only frameworks that appear in the deterministic mapping, each with the rationale for why it applies | ✕ Invent frameworks, clauses or citations not in the provided knowledge |
| ✓ For each framework: control objectives with a clause reference (`requirement_source`) and a concrete `testing_approach` | ✕ Present output as audit-ready or as a compliance conclusion with no human-review gate |
| ✓ A `gap_risk_summary` with rating, prioritised actions and a plain-English executive summary | ✕ Run commands outside the allowlist (`regulatory/guardrails/allowed-commands.md`) |
| ✓ `report_id`, `generated_at`, the echoed `audit_input`, and the disclaimer | ✕ Hard-code credentials or secrets |
| ✓ Valid JSON conforming to the `ComplianceReport` Pydantic model | ✕ Silently return a partial or schema-invalid report |

Findings do not use `outputs/schemas/finding-schema.json` today. The output is a framework overview, not a findings list (see Coverage gaps).

## 5. Coverage gaps

- **Grounding check matches names only.** Frameworks and regulations outside the mapping are rejected, but alias matching is a heuristic over `full_name`/key/abbreviations; a legitimate model rewording not covered by it will be rejected (fails closed).
- **Clause references are unverified.** `requirement_source` and `applicable_sections` are model-generated and not checked against any source text, so a plausible but wrong article number can pass validation.
- **Knowledge base is hand-maintained and static.** There is no versioning, no review date per framework, and no process for regulatory change. Boundary cases (e.g. a fintech that may or may not be a credit institution under DORA) are listed as an open question in the plan and are not handled explicitly.
- **BIO2 coverage is structural only.** The BIO2 entry (v1.3) lists the ISO 27001/27002 structure, not BIO2's government-specific measures, so the agent cannot ground measure-level citations. Municipalities' status is not stated because the official sources disagree on timing. The Cyberbeveiligingswet is not a separate entry, and private suppliers contractually bound to BIO2 are not modelled (issue #35).
- **Limited jurisdiction coverage (partly mitigated).** The system prompt names US, EU, UK, Australia and Singapore (now documented in the README). Other countries still resolve to a generic jurisdiction and the output may be thin, but the user is now warned in the CLI, log and report (see CO-3). Coverage itself is not extended, and the warning is not shown for Canada, India or Japan, which have only minimal coverage.
- **Not mapped to `finding-schema.json`.** Output cannot be fed directly into other SAAF components.
- **Real entity names are sent to a third-party API by default.** A warning and an opt-in alias exist (issue #12), but anonymisation is not the default and the alias is not checked for leaking the real name. Real-name restoration in `audit_input` means local output stays sensitive.
- **Audit trail is opt-in and partial.** Failed runs are not recorded, and the prompt is stored only as a hash (see section 7).
- **Tests are mostly unit-level.** `tests/test_agent_run.py` exercises `ComplianceAgent.run` with a mocked client (success, JSON extraction, no-JSON, schema-invalid, 4xx/5xx/connection errors), and grounding and disclaimer tests also use mocked responses. Not evaluated against real model output.
- **Unused config.** `Config.timeout_seconds` is defined but not passed to the API client.
- **Repo ownership.** Plan was submitted on the maintainer's behalf by a colleague; the Check and Act PDCA phases are not started.

## 6. Status / validation

Status is **Draft**. The test suite (`tests/test_saaf.py`, 496 lines, unittest) could not be run while writing this document because dependencies were not installed in that environment, so no criterion below is marked as verified. Tests that appear to cover each criterion are named so a reviewer can run them (`pip install -r requirements.txt && python -m unittest tests.test_saaf`).

| Acceptance criterion | Verified? | Evidence |
|---|---|---|
| CO-1 #1–#3 (mapping) | ☐ | Candidate tests: `TestFrameworkMapper.test_us_healthcare_includes_hipaa`, `test_us_private_excludes_sox`, `test_eu_finserv_includes_dora`, `test_framework_matches_have_rationale` — not yet run |
| CO-1 #4 (prompt lists only mapped frameworks) | ☐ | Candidate: `TestSystemPromptBuilder.test_system_prompt_injects_framework_names` — not yet run |
| CO-1 #5 (out-of-scope framework rejected) | ☑ | `TestGroundingCheck.*` passed on 2026-10-06 (`python -m unittest discover -s tests`, 52 tests OK); mocked API only, not a live model run |
| CO-2 #1–#2 (JSON extraction) | ☑ | `tests.test_agent_run`: `TestAgentRunSuccess.test_markdown_fenced_json_is_extracted`, `test_prose_wrapped_json_is_extracted`, `TestAgentRunInvalidOutput.test_no_json_raises_with_raw_response` (mocked client, run 2026-10-06, passing). Also candidate: `TestJsonExtraction.*` |
| CO-2 #3 (schema violation) | ☑ | `tests.test_agent_run`: `TestAgentRunInvalidOutput.test_schema_invalid_json_raises_with_raw_response` (mocked client, run 2026-10-06, passing) |
| CO-2 #4 (CLI rejects bad enum) | ☐ | Candidate: `TestCliDryRun.test_invalid_industry_rejected_by_cli` — not yet run |
| CO-2 #5 (API retry behaviour) | ☑ | `tests.test_agent_run`: `TestAgentRunApiErrors.test_4xx_fails_immediately_without_retry`, `test_5xx_retries_max_retries_then_fails`, `test_connection_error_retries_max_retries_then_fails`, `test_transient_5xx_then_success_returns_report` (mocked client, run 2026-10-06, passing) |
| CO-3 #1 (disclaimer shown) | ☑ | `TestDisclaimerNotOverridable.test_disclaimer_in_rendered_report`, `test_disclaimer_in_json_output`; `python -m unittest discover -s tests` passed (53 tests), 2026-10-06 |
| CO-3 #2 (disclaimer omitted/rewritten) | ☑ | `TestDisclaimerNotOverridable.test_omitted_disclaimer_gets_standard_text`, `test_rewritten_disclaimer_is_replaced`, `test_schema_hides_disclaimer_from_model`; same run |
| CO-3 #3 (no compliance conclusion) | ☐ | Not implemented (prompt wording only) |
| CO-3 #4 (unrecognised-jurisdiction warning) | ☑ | `python -m unittest discover -s tests` run on this branch before merging main (56 tests OK, not re-run after the merge), including `TestJurisdictionWarning.*` (CLI stderr incl. `--dry-run`, agent log, report field, formatter, schema exclusion; agent run uses a stubbed model call, not a live API call) |
| CO-4 #1 (missing key) | ☐ | Candidate: `TestCliDryRun.test_dry_run_no_api_key_needed` covers dry-run only |
| CO-4 #2 (secret scan) | ☑ | Manual grep of tracked files, 2026-10-06, no matches |
| CO-4 #3 (warning, opt-in alias) | ☑ | `TestEntityNameDataFlow.*` (7 tests, mocked agent, no API call); full suite `python -m unittest discover -s tests` passed, 55 tests. Opt-in only; default still sends real name |
| CO-5 #1–#2 | ☐ | By code inspection (`saaf/core/agent.py`); no test, no live run |
| CO-5 #3 | ☐ | Known limitation |

## 7. Observability

Today: Python `logging` (default INFO, configurable with `--log-level`) writes to stderr. It records the input profile, mapped frameworks, model and token settings, API duration, token counts, stop reason, retries and errors, and the report ID. DEBUG adds prompt sizes and parse details. Opt-in (`--audit-trail-dir`): a per-run JSON record keyed by `report_id` with provider, model, endpoint host, call settings, knowledge-base version, token usage and the raw response (see CO-5). Missing: records for failed runs, storage of the prompt text, persistent log storage by default, and cost tracking. Input includes the company name, which may be sensitive, so persistence would need a redaction decision.
