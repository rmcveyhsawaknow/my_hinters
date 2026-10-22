"""The local agents framework: a supervisor, a shared memory graph, A2A cards, an MCP server and a status page.

The world (Hinterglass) stays the only place actions happen. Everything here runs on the operator's
own machine, Windows or Linux, with no service beyond Python: ``hglab local run`` schedules the same
wakes, shifts, keepalives and office rounds GitHub Actions runs, in seconds; ``hglab local memory``
keeps a property graph of agents, teams, goals, promises and interactions on SQLite with dated
snapshots; ``hglab local a2a`` serves one A2A agent card per persona and takes messages for them;
``hglab local mcp`` exposes management to Claude Code; ``hglab local ui`` shows status and
configuration in a browser. See docs/local-agents-framework.md.
"""
