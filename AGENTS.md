# Base44 Setup Notes — Due Diligence Agents

## What this repo is

`dd-agents` is an **open-source CLI tool** for forensic M&A due diligence. It is a
Python package (published to PyPI as `dd-agents`) that reads a data room of
contracts, runs 13 specialist AI agents across 9 domains, cross-references
findings, and emits an interactive HTML report + Excel workbook + per-subject
JSON.

**This repository does NOT contain the `src/` package source** — only docs,
examples, config templates, scripts, and pre-generated sample reports. The
Dockerfile references `COPY src/ src/` but `src/` is absent here; the runnable
package lives on PyPI.

## What the preview shows

Because there is no web app or dev server, the preview serves the tool's
**generated sample report** (`docs/sample-report/index.html`, a fully
self-contained interactive HTML file) via nginx on port 3000. This is the
actual product output a user would get from `dd-agents run`.

## Running a real analysis (optional, needs credentials)

```bash
pip install dd-agents            # from PyPI
dd-agents run examples/project-atlas/deal-config.json
```

This requires an **Anthropic API key** (`ANTHROPIC_API_KEY`) or an
Anthropic-compatible gateway (`ANTHROPIC_BASE_URL`). It is a long-running CLI
job (minutes), not a web service, so it is not part of the preview. The key is
declared as an optional secret — the preview boots without it.

## Verify the preview

```bash
docker compose -f docker-compose.base44.yml up -d
curl -sf -H "Host: external.preview.example" http://localhost:3000/ | head
```
