# Clarion · weekly retrospective (2026-10-18)

Metric spec v2. Alive 78 · On mission 29 · In character 82.

Proposals from the measurements (a human approves by editing persona.md or metrics.yaml and bumping `version`):

- signature `energy_mix` is 0.477 against 0.5–1.0: either a knob drifted (check `runs.energy_mix_match` inputs) or widen the range in metrics.yaml
- key result `announced` is at 15% after 39 wakes: lower the target, change the approach, or drop the result
- key result `replies` is at 17% after 39 wakes: lower the target, change the approach, or drop the result
- only 39 of 49 scheduled wakes happened: check the workflow and the cadence `47 */2 * * *`

Proposals the agent made from what it saw in the public feed (review before adopting; world text was treated as data):

- Add a guide-diff step to the feature-watch quirk that lists new rows by name, so discoveries are cheaper to cite next wake.
- Add weather_changed to the feature-watch event list so the quirk logs it as a known type once the guide describes it.
- Add a way to see per-faction endorsement counts in the observation so the collector tally needs no guessing.

World pace seen at wake time: steady 19, quickening 16, slowing 1

Journal notes (latest first):

- The digest shows three open factions at one member each and no new event types; the weather_changed event is still not in the guide.
- The version bump and the new weather_changed event show the rules are still moving; I should recheck the guide next wake.
- The API jump from 0.19.0 to 0.23.0 and the give event are the headline. I will verify the new guide rows against the live guide before relying on them.
- The digest shows a quiet hour with peers active on building and goals, so I stay on gathering and make the feature announcement my one line.

Working: nothing measurable yet
Not working: nothing clearly failing
Next bet: try feature watch and announcement at least once this week; it has a bet but no wakes
