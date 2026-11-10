# AUDIT-CRITERIA.md — Compliance Report Generator

> SAAF A2 standard (Audit Criteria & Controls). This document sits next to `README.md`: the README says what the agent does and how to run it; this document says what the agent must be judged against as an auditee.
>
> **Sources used to draft this document:** `README.md`, the hackathon plan (`plans/hackathon-2/rohan-sobha-compliance-report-generator.md` in SAAF-Project), a read-through of the code (`saaf/core/`, `saaf/knowledge/`, `config.py`, `cli.py`, `tests/`), the merged PRs and issues of this repository, and the CI results of the `Tests` workflow on `main` ([run 37473476071](https://github.com/SAAF-Project/Compliance-Report-Generator/actions/runs/37473476071), commit `606dbb2`: 202 passed, 1 skipped). No Session 6 A2 hand-in existed. No logged real run was available, so nothing below is verified by a live model run (see section 6).
>
> **Branch note:** `main` is the only live implementation. Every other pushed branch belongs to a merged or closed PR; the one unmerged piece of work is closed PR #22 (maintainers and PDCA status), which was closed because that section is not required in this document.

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

Given an engagement profile (company name, industry, country, listed status, audit topic), the agent deterministically maps the entity to applicable regulatory frameworks from a built-in knowledge base (30+ frameworks), then asks an LLM (default Claude `claude-opus-4-6` with adaptive thinking; any OpenAI-compatible endpoint can be configured with `--provider` / `--model` / `--base-url`) to produce a structured compliance overview: mandatory regulations, per-framework control objectives with testing approaches, typical gaps, and a prioritised action summary. Clause references it cites are checked for existence against official clause lists where one is shipped. Output is validated against Pydantic models and rendered as a terminal report or JSON. It supports the **planning phase** of an audit engagement (regulatory scoping); it does not assess the entity's actual compliance.

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
- Given a model response that contains a framework not in the mapped set, the agent rejects it with a `ComplianceReportError` that carries the raw response. After parsing, `ComplianceAgent._check_grounding` compares `framework_assessments[].framework_name` and `mandatory_regulations[].regulation_name` against the mapped frameworks (case-insensitive; the full name, key, name before the dash, and abbreviations in the full name are accepted). **Limitation, stated honestly:** names are matched, not clauses, so a wrong `requirement_source` inside a mapped framework is not caught by this check.
- Given a cited clause in a framework that has an official clause list, the report records a per-reference outcome in `reference_checks`, always labelled `unverified` with a heuristic score below 1.0; a clause missing from the list is flagged, not rejected, and a model-supplied `reference_checks` value is ignored. **Limitation, stated honestly:** this shows a clause exists, not that it says what the model claims, and frameworks without a clause list (e.g. ISO 27001, SOC 2, PCI DSS, SOX) are not checked.

**CO-2 — Valid output**
- Given a response wrapped in markdown fences or surrounded by prose, the agent extracts the JSON object and validates it.
- Given a response with no JSON object, the agent raises `ComplianceReportError` that carries the raw response.
- Given JSON that violates the schema (e.g. an invalid `risk_rating`), the agent raises `ComplianceReportError` and does not return a partial report.
- Given an invalid `--industry`, `--listed-status` or `--audit-topic`, the CLI exits non-zero without calling the API.
- Given a persistent 4xx API error, the agent fails immediately. Given 5xx or connection errors, it retries up to `max_retries` and then fails with `ComplianceReportError`.
- Given `--output findings`, every emitted finding has an `F-NN` id, a title of at most 100 characters, a `risk_rating` in High/Medium/Low/Informational and the other fields the schema requires; `Critical` is mapped to `High`, and optional fields the report does not hold are omitted, not invented.
- Given `--provider openai` with a custom `--base-url`, the same pipeline (mapping, validation, grounding, disclaimer) runs against that endpoint, and a response that is not chat-completions shaped fails with `ComplianceReportError`. Given a flag and an environment variable for the same setting, the flag wins. **Limitation, stated honestly:** only Claude has been used against a real model; output quality and JSON compliance of other models are untested.

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
- Given a run at default log level, stderr logs the input profile, mapped jurisdiction and framework keys, provider, model name and endpoint host, API duration, token counts, stop reason, and the resulting `report_id`.
- Given a JSON output, it includes `report_id`, `generated_at` and the `audit_input`. `audit_input` is agent-owned: `_parse_and_validate` always overwrites it with the trusted input before validation, so a model-supplied value never reaches the report, even if it is invalid. Whenever the model supplies a value that differs from the trusted input, a warning is logged.
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
| ✓ A `reference_checks` entry for each cited clause, labelled `unverified` | ✕ Present a clause reference as verified because it exists in a clause list |

The primary output is a framework overview, not a findings list. `--output findings` exports the gaps as `outputs/schemas/finding-schema.json` findings (see Coverage gaps for what that export cannot express).

## 5. Coverage gaps

- **Grounding check matches names only.** Frameworks and regulations outside the mapping are rejected, but alias matching is a heuristic over `full_name`/key/abbreviations; a legitimate model rewording not covered by it will be rejected (fails closed).
- **Clause references are unverified (partly mitigated).** `requirement_source` and `applicable_sections` are model-generated. For frameworks with an official clause list (`saaf/knowledge/clause_data/`, see README) the agent checks that the cited clause *exists* and records the outcome per reference in `reference_checks` (label `unverified`, heuristic confidence score, never 1.0). That does not show the clause says what the model claims. Frameworks without a clause list (e.g. ISO 27001, SOC 2, PCI DSS, SOX, NERC CIP, APRA CPS 234, FATF, CSRD/ESRS) are not checked; a not-found or unmapped reference is flagged, not rejected.
- **Knowledge base is hand-maintained and mostly unreviewed.** `KB_VERSION` (0.2.0) and per-framework `last_reviewed` / `source` fields exist, but only GDPR, DORA, MiFID II and BIO2 have a `source` and only BIO2 has a `last_reviewed`; the rest are `None` until a person reviews them (issue #30). There is no process for regulatory change. Boundary cases (e.g. a fintech that may or may not be a credit institution under DORA) are listed as an open question in the plan and are not handled explicitly.
- **BIO2 coverage is structural only.** The BIO2 entry (v1.3) lists the ISO 27001/27002 structure, not BIO2's government-specific measures, so the agent cannot ground measure-level citations. Municipalities' status is not stated because the official sources disagree on timing. The Cyberbeveiligingswet is not a separate entry, and private suppliers contractually bound to BIO2 are not modelled (issue #35).
- **Limited jurisdiction coverage (partly mitigated).** The system prompt names US, EU, UK, Australia and Singapore (now documented in the README). Other countries still resolve to a generic jurisdiction and the output may be thin, but the user is now warned in the CLI, log and report (see CO-3). Coverage itself is not extended, and the warning is not shown for Canada, India or Japan, which have only minimal coverage.
- **Findings export is a conversion, not a native output.** `--output findings` maps `Critical` to `High`, emits one finding per gap, and cannot link a recommendation to a single gap because the report does not do so: critical-gap findings carry the whole priority-action list. Root cause, impact, owner and target date are left out.
- **Real entity names are sent to a third-party API by default.** A warning and an opt-in alias exist (issue #12), but anonymisation is not the default and the alias is not checked for leaking the real name. Real-name restoration in `audit_input` means local output stays sensitive.
- **Audit trail is opt-in and partial.** Failed runs are not recorded, and the prompt is stored only as a hash (see section 7).
- **No test or run uses a real model.** CI runs the unit suite on every PR (`Tests`, plus `Lint` and a weekly clause-source e2e job). Model calls are mocked or served by a local HTTP server, so output quality is not evaluated for any provider, and the OpenAI-compatible path has never been run against a real model.
- **Several criteria are verified by code inspection only** (the stderr log fields and the JSON `report_id` / `generated_at` fields; see section 6).

## 6. Status / validation

Status is **Draft**. A row is marked ☑ when the tests it names passed in the `Tests` workflow on `main` ([run 37473476071](https://github.com/SAAF-Project/Compliance-Report-Generator/actions/runs/37473476071), commit `606dbb2`, 202 passed, 1 skipped; the skipped test is the network-dependent clause-source e2e module). Those tests use mocked or stubbed model calls, local HTTP servers or `--dry-run`; no row is verified by a live model run. ☐ means unverified or only partly verified.

| Acceptance criterion | Verified? | Evidence |
|---|---|---|
| CO-1 · US private Healthcare maps to HIPAA and not SOX | ☑ | `TestFrameworkMapper.test_us_healthcare_includes_hipaa`, `TestFrameworkMapper.test_us_private_excludes_sox` |
| CO-1 · EU Financial Services maps to GDPR and DORA | ☑ | `TestFrameworkMapper.test_eu_finserv_includes_gdpr`, `TestFrameworkMapper.test_eu_finserv_includes_dora` |
| CO-1 · Dutch government maps to BIO2; German government, Dutch non-government and non-security topics do not; `NL` still resolves to `EU` | ☑ | `TestBio2Selection.*`, `TestCountryKey.*`, `TestBio2Entry.*` |
| CO-1 · Every `FrameworkMatch` has a rationale | ☑ | `TestFrameworkMapper.test_framework_matches_have_rationale` |
| CO-1 · System prompt lists only the mapped frameworks | ☐ | Partly: `TestSystemPromptBuilder.test_system_prompt_injects_framework_names` shows the mapped names are injected. That nothing else is listed, and the instruction wording, are by code inspection only |
| CO-1 · Out-of-scope framework or regulation is rejected | ☑ | `TestGroundingCheck.*` (mocked responses, not a live model) |
| CO-1 · Cited clauses are checked against official clause lists; results labelled `unverified`; model-supplied checks ignored | ☑ | `TestCheckReferences.*`, `TestShippedClauseData.*`, `TestAgentReferenceChecks.*`. Existence only; the weekly e2e job that re-extracts the lists from the official sources did not run in this workflow (it needs network, see `.github/workflows/e2e-clauses.yml`) |
| CO-2 · Fenced or prose-wrapped JSON is extracted | ☑ | `TestAgentRunSuccess.test_markdown_fenced_json_is_extracted`, `TestAgentRunSuccess.test_prose_wrapped_json_is_extracted`, `TestJsonExtraction.*` |
| CO-2 · No JSON raises `ComplianceReportError` with the raw response | ☑ | `TestAgentRunInvalidOutput.test_no_json_raises_with_raw_response` |
| CO-2 · Schema-invalid JSON raises and returns no partial report | ☑ | `TestAgentRunInvalidOutput.test_schema_invalid_json_raises_with_raw_response` |
| CO-2 · CLI rejects an invalid enum without calling the API | ☑ | `TestCliDryRun.test_invalid_industry_rejected_by_cli` (industry only; listed status and topic use the same argparse `choices`) |
| CO-2 · 4xx fails at once; 5xx and connection errors retry then fail | ☑ | `TestAgentRunApiErrors.*` |
| CO-2 · `--output findings` emits findings with the schema's required fields | ☑ | `FindingsExportTests.*` (checked against required fields and enums copied from `finding-schema.json`, not a schema validator) |
| CO-2 · A custom OpenAI-compatible endpoint runs the same pipeline; malformed endpoint responses fail; flags beat environment variables | ☑ | `TestAgentCustomEndpoint.*`, `TestOpenAICompatibleClient.*`, `TestCreateClient.*`, `TestConfigPrecedence.*`, `TestClientTimeout.*`. Local test server only; never run against a real OpenAI-compatible model |
| CO-3 · Disclaimer is in the rendered report and the JSON | ☑ | `TestDisclaimerNotOverridable.test_disclaimer_in_rendered_report`, `TestDisclaimerNotOverridable.test_disclaimer_in_json_output` |
| CO-3 · An omitted or rewritten disclaimer is replaced by the standard text | ☑ | `TestDisclaimerNotOverridable.*` |
| CO-3 · The report states no compliance conclusion | ☐ | Not implemented (prompt wording only) |
| CO-3 · Unrecognised jurisdiction produces a warning in the CLI, log and report | ☑ | `TestJurisdictionWarning.*` |
| CO-4 · Missing key gives a configuration error; key optional only for `openai` with a custom endpoint; `--dry-run` needs no key | ☑ | `TestConfigDefaults.*`, `TestConfigProviders.*`, `TestCliDryRun.test_dry_run_no_api_key_needed`. `Config` raising is tested; the CLI turning that into exit code 1 is by code inspection |
| CO-4 · Bad `--base-url` is rejected; plain `http://` to a non-local host warns; redirects are not followed | ☑ | `TestValidateBaseUrl.*`, `TestOpenAICompatibleClient.test_redirect_is_not_followed_so_the_key_is_not_forwarded`, `TestConfigPrecedence.test_invalid_base_url_raises_environment_error` |
| CO-4 · No credentials in tracked files | ☑ | Manual `git grep` for `sk-`, `AKIA` and private-key headers, plus a check for tracked `.env` files, on `main` at 606dbb2, 2026-10-06: no matches. Not automated |
| CO-4 · Company-name warning, opt-in alias, alias absent from logs | ☑ | `TestEntityNameDataFlow.*`. Opt-in only; the default still sends the real name |
| CO-5 · Stderr log carries the profile, frameworks, provider, host, model, usage and `report_id` | ☐ | By code inspection (`saaf/core/agent.py`); no test asserts the log lines |
| CO-5 · JSON output includes `report_id`, `generated_at` and `audit_input` | ☐ | By code inspection (`saaf/core/models.py`); no test names these fields in the CLI output |
| CO-5 · A model-supplied `audit_input` is replaced by the trusted input; with `--anonymise` the model sees only the alias and the local report shows the real name | ☑ | `TestAuditInputAgentOwned.*`, `TestEntityNameDataFlow.test_anonymised_run_ignores_model_audit_input_and_restores_real_name` |
| CO-5 · `--audit-trail-dir` writes a full record; company name redacted by default | ☑ | `TestAuditTrail.*`, `TestProviderMetadata.*`, `TestAgentAuditTrailMetadata.*` |
| CO-5 · Endpoint credentials, query string and fragment never reach the record | ☑ | `TestProviderMetadata.test_credentials_and_query_never_reach_the_file`, `TestSanitizeEndpoint.*` |

## 7. Observability

Today: Python `logging` (default INFO, configurable with `--log-level`) writes to stderr. It records the input profile, mapped frameworks, model and token settings, API duration, token counts, stop reason, retries and errors, and the report ID. DEBUG adds prompt sizes and parse details. Opt-in (`--audit-trail-dir`): a per-run JSON record keyed by `report_id` with provider, model, endpoint host, call settings, knowledge-base version, token usage and the raw response (see CO-5). Missing: records for failed runs, storage of the prompt text, persistent log storage by default, and cost tracking. Input includes the company name, which may be sensitive, so persistence would need a redaction decision.
