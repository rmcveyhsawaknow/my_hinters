---
name: data-analysis
description: Analyze archived public data reproducibly with provenance and uncertainty.
---
# Analyze data
1. Identify source, event IDs, tick/date range, snapshot checksum, and exclusions.
2. Validate schema, duplicates, missingness, and clock calibration.
3. Use an analysis script under `analysis/`; report uncertainty and sensitivity.
4. Save only permitted public data and output needed to reproduce the result.
Check: run the script from a clean checkout and compare outputs.
Example: aggregate event-sourced item gains and losses by item and tick.
