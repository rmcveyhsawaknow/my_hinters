# Plan pages

Generators for the plan pages the agents and the owner work from (`skills/hg-blueprint-design`). Each folder holds a
`make_plan.py` that reads the repository's blueprints, the public world snapshot (`runs/local/world.json`), the land
office's site requests and the blueprint ledgers, and a `template.html` it inlines the data into. Run one from the
repository root with the project venv (`.venv/Scripts/python tools/plan_pages/nyc-north/make_plan.py`); the page lands
beside the script and is published with the Artifact tool, never committed (see `.gitignore` here).

- `nyc-north`: several designs on one map with the land office's segments (Midtown, Central Park, Uptown; 2026-11-03).
- `nintendo-land`: districts, tubes and the build order across the teams (2026-11-03).

To make a new one, copy the nearer folder, change its `DESIGNS`, `BOUNDS` and builders, and keep the page's rules:
data inline as one JSON literal, no external scripts, light and dark themes from CSS tokens on `:root`, readable at
phone width.
