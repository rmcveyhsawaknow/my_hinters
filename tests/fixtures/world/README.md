# World fixtures

`terrain.txt` holds the 128 rows of terrain codes from the public snapshot
`https://hinterglass.com/live/world.json` fetched read-only on 2026-10-17 at
14:11:24 UTC (world tick 3702, day 10). The raw snapshot's SHA-256 was
`21767406ecfebaf9df2e7c1085f634a4a7a343632f076908f44478f94e2cb561`; the extracted
rows file has SHA-256 `9b844dbc4018c874905df3911268847a89e500e23507feab16ab7fa671f9d529`.

Codes: `W` deep water, `w` shallow water, `s` sand, `g` grass, `f` forest,
`h` hills, `m` mountain. Row index is `y`, column index is `x`.

Everything else in this directory is synthetic: fictional peers, invented
events, no real whispers. Fixtures never contain credentials.
