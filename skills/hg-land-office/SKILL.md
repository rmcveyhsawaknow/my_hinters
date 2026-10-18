---
name: hg-land-office
description: Run the land office - survey the world in 10x10 plots, register plots for a posted fee, keep the deed registry, buy surplus through standing offers, and grow the vault toward brokerage and lending.
---
# The land office
1. The ledger is `config/plots.yaml` (schema `schemas/plots.json`): the registrar persona, the grid, the posted fee and its reward, the registration goal title (posted verbatim), standing offers and any pre-registered plots. `hglab land validate` checks it against the registrar's hats.
2. `hglab land board` shows the survey (plots occupied and free), the vault, the registration goal, the offers and the registry, from public data alone.
3. `hglab land round --agent land-broker [--dry-run] [--fixture FILE]` runs one round: deeds for every paid registration in the public log (a `goal_done` on the registration goal, or a collective member's fee given into the vault), the profile registry update, a deed sign when the office stands inside the plot, the registration goal and affordable offers (two open goals at a time, rewards escrowed from the pack), and the office line when nothing else spoke. The shift job runs it after the work shift.
4. The vault is the registrar's `private` storehouse; the planner's build priority puts it first. Every collective agent's work shift deposits surplus into an adjacent vault; the office counts the vault toward lending.
5. Phases: survey and registry now; brokerage (seller demolishes, buyer builds, the office takes a share through a deliver-condition goal) as plots fill; lending against deeds when the vault passes 200 items. New phases are proposed through the weekly retro, never by the agent editing its own files.
Check: a registration is a dated public record and a mediator's promise, never a wall; fees and offers are posted in public before anyone pays; no goal is aimed at a collective member; nothing from inbox or notebook enters a record.
Example: `hglab land round --agent land-broker --fixture tests/fixtures/observe/land-broker.json --dry-run` prints the survey and the office line; with a vault in view it posts the registration goal with its deliver condition.
