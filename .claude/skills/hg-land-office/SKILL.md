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

## Acquisition and the lot market

The office's first drive is land: the `stake_lots` knob makes every work wake stake up to two free
5x5 lots (one claim sign on the lot's anchor tile, nearest lots first, a ring of lots left around
every other agent's hut). `hglab land board` shows lots staked, for sale and free, and today's price:
`lot_price` starts at the base (5 wood), doubles at half the lots gone, reaches ten times at a tenth
free and stops at the cap one give can carry (50). One standing sale goal lists the lots at that
price with a deliver condition into the vault; when the price moves, the round cancels and reposts
it. A `goal_done` on the sale goal deeds the buyer the lot they named by whisper, or the unsold lot
nearest their hut; the deed is announced, the profile registry updated, and the claim sign rewritten
with the buyer's name when the office passes. A 10x10 plot is four lots.

## Worth, price and a client's site (2026-10-22)

A lot's price is its worth at today's scarcity: `lot_value` scores resources within two tiles (ore 3,
stone 1.5, wood 1, fiber and berries 0.5, capped at 6), vista (water along the edge: river view 1,
coast 2; mountains within three: 1; hills inside: 0.5), venues (others' structures within ten tiles,
0.3 each, cap 2) and demand (residents seen within two days within fifteen tiles, 0.5 each, cap 1.5);
`lot_price` multiplies the scarcity price by one plus half the score, so ore-rich land with a river
view costs several times what plain sand does, never above the fifty one give can carry. Claim signs
carry each lot's tags and price; the standing sale goal asks the median. A `site_requests` entry in
`config/plots.yaml` is a client's brief: `surveys_due` finds the best buildable lot that can grow into
the free lots beside it, near the brief's marks and with the resources it wants; the office whispers
the client `SITE for <id>: lot, anchor, price` and says so in public; `paid_deeds` reads the client's
gives into office storehouses from the public log and announces the deed. The client's `house` knob
with `site_from: land_office` asks once a day, reads the answer from its inbox (never copied into a
record), carries the wood to the vault, and builds on the bought lot.
