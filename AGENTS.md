# Base44 Dev Environment — Due Diligence Agents

## Project Overview
This is `dd-agents`, an open-source forensic M&A due diligence CLI tool built on the Claude Agent SDK. It analyzes data rooms across 9 domain specialists, cross-references findings, and produces interactive HTML + Excel reports.

## Important: Source Code Status
The Python source package (`src/dd_agents/`) is **not present** in this repository — only docs, config, examples, and a pre-generated sample report are tracked. The Dockerfile and `pyproject.toml` reference `src/` but it does not exist in the working tree.

## What Runs in the Preview
Since the CLI source is missing and this is a CLI tool (not a web app), the preview serves the **sample interactive HTML report** (`docs/marketing/sample-report-atlas/index.html`) via nginx on port 3000. This is a self-contained 520KB HTML file with embedded CSS/JS that demonstrates the tool's output: executive dashboard, domain findings, cross-domain synthesis, risk heatmap, and filtering.

## Compose Setup
- `docker-compose.base44.yml` — single `nginx:alpine` service serving the sample report
- Port 3000 → nginx port 80
- Health check: `GET /`

## Verification
```bash
docker compose -f docker-compose.base44.yml up -d
curl -sf http://localhost:3000/   # should return the HTML report
```

## Secrets
No external secrets required for the preview (static HTML). The full CLI tool would need `ANTHROPIC_API_KEY` to run agents, but that source code isn't in this repo.
