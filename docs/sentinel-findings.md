# Compliance-Report-Generator — review findings

Repository: `SAAF-Project/Compliance-Report-Generator`, commit `99f26d2` (main, 2026-11-10).
Method: read every file under `saaf/`, `cli.py`, `config.py`, the workflows and the tests;
re-ran the mapper logic over all 2,160 input combinations
(8 jurisdictions × 10 industries × 3 listed statuses × 9 topics).

Each finding has a Sentinel check ID where SAAF Sentinel now detects the pattern
(the `sentinel/` package in this repository). "Contract" checks need the repo's adapter; "static" checks need nothing.

| # | Severity | Finding | Sentinel |
|---|----------|---------|----------|
| 1 | High | Mapper silently drops mandatory regulations (8-framework cap) | CT003, SEN003 |
| 2 | High | `extraterritorial` makes GDPR / UK GDPR / CCPA apply in every country | CT003 (invariant) |
| 3 | High | Cap + grounding check reject correct reports | CT003 |
| 4 | Medium | Model controls `report_id`, `generated_at`, `audit_input` | CT001, SEN005 |
| 5 | Medium | Audit-trail records are overwritten when the model repeats an ID | CT001 |
| 6 | Medium | Rich-markup injection from model text into the terminal report | CT002, SEN001 |
| 7 | Medium | Provider API key is sent to any custom `--base-url` | checklist |
| 8 | Medium | Retries have no backoff; 429 is never retried | SEN002 |
| 9 | Low | Truncated / refused responses are not detected (`stop_reason`) | SEN004 |
| 10 | Low | Completeness is never checked: empty or partial reports pass | CT004 |
| 11 | Low | Reference-check fallback uses substring matching (`iso` in "provisions") | checklist |
| 12 | Low | Engagement text goes into the prompt unbounded and unescaped | checklist |
| 13 | Low | Hard-wired adaptive thinking breaks other Anthropic models | checklist |
| 14 | Info | CI: actions pinned to tags; dependencies unpinned | SEN006 |

---

## 1. Mapper silently drops mandatory regulations — High

`saaf/core/mapper.py:188` returns `matches[:8]`. Sorting puts topic-matching frameworks
first, so regulations pulled in only by the regulatory matrix are cut first. Nothing logs it.

* 478 of 2,160 input combinations lose at least one regulatory-matrix key.
* README's own example (NL, Financial Services, Public, Cybersecurity) keeps SOC 2 and
  CSA CCM (voluntary) but drops **MiFID II, FATF AML, CSRD/ESRS, TCFD, GRI, ISO 31000**.
* NL / EU, Financial Services, Public, **IT General Controls**: drops **GDPR and NIS2**
  (and 6 more) while keeping COBIT, CSA CCM, SOC 2, NIST CSF.
* US, Financial Services, Public, Vendor Management: drops **SOX**, COSO, NIST 800-53, PCI DSS.

Repro: `python cli.py --company X --industry "Financial Services" --country NL
--listed-status Public --audit-topic "IT General Controls" --dry-run` — GDPR is absent.

Fix: never truncate `regulation_keys`; cap only the optional (topic-only) frameworks, and
log/warn what was cut. Add a test that `set(regulation_keys) <= set(selected keys)`.

## 2. `extraterritorial` applies everywhere — High

`saaf/core/mapper.py:153`: when the jurisdiction does not match, `extraterritorial=True`
counts as a match unconditionally. GDPR, UK GDPR and CCPA/CPRA carry the flag, so they are
selected for every country and, being topic matches, outrank local law in the sort.

Example: AU, Financial Services, Private, Vendor Management keeps **CCPA, GDPR, UK GDPR**
and drops **APRA CPS 234 and the Australian Privacy Act**.

Fix: treat extraterritorial frameworks as conditional (lower sort rank, flagged "only if
the entity processes data of residents of X"), and never let them displace matrix keys.

## 3. Cap + grounding check reject correct reports — High

`saaf/core/agent.py:263` rejects any framework/regulation name outside the (capped)
mapping. When finding 1 drops GDPR, a model that correctly names GDPR for a Dutch bank
causes `ComplianceReportError`, the run fails and nothing is written to the audit trail.
Fixing finding 1 removes most of this; the grounding check should validate against the
uncapped mandatory set.

## 4. Model controls `report_id`, `generated_at` and `audit_input` — Medium

`saaf/core/agent.py:225-237`: `audit_input` is only injected when the model omits it, and
`ComplianceReport(**data)` accepts `report_id` / `generated_at` from the model (the schema
sent to the model still lists them; only `disclaimer`, `warnings` and `reference_checks`
are stripped, `system_prompt.py:88-92`). Consequences:

* the report can state a different country, industry or listed status than was audited;
* with `--anonymise`, `cli.py:279` restores only `company_name`, so other model edits stay;
* timestamps in a compliance artefact are model-written.

Fix: after validation, always set `report.audit_input = audit_input`,
`report.report_id = uuid4()`, `report.generated_at = now()`; pop them from the schema.

## 5. Audit-trail overwrite — Medium

`saaf/core/audit_trail.py:124` writes `<report_id>.json` with `write_text` (overwrite).
Path traversal is blocked (`:93`), but models commonly emit placeholder IDs such as
`RPT-2026-001`; two runs then overwrite each other's evidence silently.
Fix: finding 4's fix, plus open with `"x"` (exclusive create) and fail loudly on collision.

## 6. Rich-markup injection into the terminal report — Medium

`saaf/output/formatter.py` interpolates model text into Rich markup strings
(e.g. `:99` executive summary, `:175` gaps, `:220` sources, table cells via `add_row`).
Model text containing `[/x]` raises `MarkupError` after a paid, successful API call;
`[link=…]…[/link]` produces clickable links the auditor did not write; an unknown tag such
as `Art. 28(3)[a]` silently loses `[a]`. The file already uses `markup=False` for the
reference note (`:56`, `:62`), so the fix is known: wrap model text in
`rich.markup.escape()` or `Text(...)`.

## 7. Provider key sent to any custom endpoint — Medium

`config.py:57` falls back to `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` even when `--base-url`
points at a third-party gateway or a plain-http host (only a warning, `endpoint.py`).
A real OpenAI/Anthropic key is forwarded to whatever host is configured.
Fix: when `base_url` is set, use only `SAAF_API_KEY` (or an explicit flag) and refuse
non-loopback `http://` unless `--allow-insecure` is given.

## 8. Retries without backoff; 429 not retried — Medium

`saaf/core/agent.py:167-187` retries immediately in a tight loop.
`anthropic_client.py:57` and `openai_compatible.py` mark only `>= 500` retryable, so
rate limits (429) fail the run at once while overload (529) is hammered with no delay.
Fix: exponential backoff with jitter; treat 429 as retryable and honour `Retry-After`.

## 9. Truncation / refusal not detected — Low

`stop_reason` / `finish_reason` are logged but never checked (`agent.py:198`). A
`max_tokens` / `length` stop yields a misleading "invalid JSON" error; a refusal is parsed
as if it were a report. Fix: branch on the stop reason before parsing.

## 10. No completeness check — Low

A response with empty `framework_assessments` and `mandatory_regulations` passes schema
and grounding validation. Nothing checks that every mapped mandatory regulation is
assessed. Fix: require each mapped regulation key to appear (or be explicitly marked N/A
with a reason).

## 11. Substring alias matching in reference checks — Low

`saaf/core/reference_check.py:85` (`alias in compact`) with aliases such as `iso` and `gri`
means "Supervisory provisions…" or "Data integrity…" count as naming ISO 27001 / GRI and are
scored `framework_not_covered` (0.30) instead of `unmapped_framework` (0.05). Only the
fallback path is affected (`frameworks_named` itself is word-bounded). Fix: reuse
`clauses._phrase_spans` word-boundary matching.

## 12. Unbounded engagement text in the prompt — Low

`company_name` and `country` are free text, inserted verbatim into the user message
(`system_prompt.py:129`) with no length limit or newline stripping. Grounding blocks extra
frameworks, but gaps, ratings and the executive summary can be steered. Fix: length limits,
strip control characters/newlines, and fence the values as data.

## 13. Adaptive thinking hard-wired — Low

`anthropic_client.py:41` always sends `thinking={"type": "adaptive"}`. The README says the
agent is model-agnostic, but any Anthropic model without adaptive thinking fails with a
non-retryable 400. Make it a config option.

## 14. CI hygiene — Info

Actions are pinned to tags (`actions/checkout@v4`, third-party
`EnricoMi/publish-unit-test-result-action@v2` with `pull-requests: write`); Ruff and
dependencies are unpinned (`anthropic>=0.40.0`), so reports are not reproducible run to
run. Pin actions to SHAs and add a lock file.
