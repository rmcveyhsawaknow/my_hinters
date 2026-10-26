"""`hglab navy`: the Admiralty's chart of the sea round the island, its works and how far they stand."""

from __future__ import annotations

from pathlib import Path

import typer

navy_app = typer.Typer(help="The Admiralty: the sea charted round the island, piers over the shallow shelf, causeways across bays and lakes.")


@navy_app.command("chart")
def chart_command(agent: str = typer.Option("Fathomark", "--agent", help="The Navy's in-world name, for its position on the chart")) -> None:
    """The chart in words (as the Navy's model reads it) and every work with its bridges standing (no key needed)."""
    from hglab import navy
    from hglab.cli_personas import fetch_public_world, world_cache_path
    from hglab.terrain3d import ground_of

    world = fetch_public_world(world_cache_path(Path.cwd()))
    if not world:
        raise typer.BadParameter("the public world snapshot could not be read")
    me = next((a for a in world.get("agents") or [] if isinstance(a, dict) and a.get("name") == agent), None)
    here = (int(me["x"]), int(me["y"])) if me and isinstance(me.get("x"), int) else None
    typer.echo(navy.brief(world, here, None, ground_of(world)))
    c = navy.chart(world)
    structures = list(world.get("structures") or [])
    bridges, taken = navy.bridges_of(structures), navy.taken_tiles(structures)
    typer.echo("")
    for work in c.works:
        built = sum(1 for t in work.tiles if t in bridges)
        state = "finished" if navy.finished(work, bridges) else ("blocked" if navy.next_tile(work, bridges, taken) is None else f"next {navy.next_tile(work, bridges, taken)}")
        extra = f", saves {work.saves} steps" if work.kind == "causeway" else ""
        typer.echo(f"  {work.id:12} {work.kind:8} shore {work.shore} -> {work.far}: {built}/{len(work.tiles)} bridges, {state}{extra}")


def register(app: typer.Typer) -> None:
    app.add_typer(navy_app, name="navy")
