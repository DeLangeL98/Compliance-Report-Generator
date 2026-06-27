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
  --industry financial_services \
  --country Netherlands \
  --listed-status listed \
  --audit-topic compliance

# Dry-run (no API call — preview framework selection only)
python cli.py --company "..." --industry financial_services \
  --country Netherlands --listed-status listed \
  --audit-topic compliance --dry-run

# JSON output
python cli.py ... --output json
```

Requires `ANTHROPIC_API_KEY` set in the environment.

## What it does

1. **Deterministic mapping** — resolves the entity's jurisdiction, industry, and listed status against a knowledge base of 30+ frameworks (DORA, NIS2, GDPR, ISO 27001, SOX, HIPAA, and more) with no API call needed (`saaf/core/mapper.py`, `saaf/knowledge/`).
2. **Dynamic prompt construction** — builds a system prompt containing only the selected frameworks, reducing hallucination (`saaf/prompts/system_prompt.py`).
3. **Claude API call** — sends the engagement details to Claude (`claude-opus-4-6`) with extended thinking enabled and retries on transient errors (`saaf/core/agent.py`).
4. **Validation and rendering** — validates the JSON response against Pydantic models and renders a rich terminal report with control objectives, gap analysis, and priority actions (`saaf/core/models.py`, `saaf/output/formatter.py`).

## Input / output

- **Input**: company name, industry (e.g. `financial_services`, `healthcare`), country/jurisdiction, listed status (`listed` / `private` / `government`), audit topic (e.g. `compliance`, `cybersecurity`, `data_privacy`)
- **Output**: rich terminal report or JSON listing applicable regulatory frameworks, control objectives, key gaps, and priority remediation actions

## Related plan

[Compliance Report Generator — Rohan Sobha](https://github.com/Iodine98/SAAF-Project/blob/main/plans/hackathon-2/rohan-sobha-compliance-report-generator.md)

## Part of SAAF Project

[saaf-portal.vercel.app](https://saaf-portal.vercel.app)
