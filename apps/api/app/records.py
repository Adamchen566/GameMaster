"""Export the complete record of a game, for keeping and for replaying later.

    python -m app.records                  list the stored games
    python -m app.records <game_id>        write records/<game_id>.json
    python -m app.records <game_id> --out game.json

The record holds everything: who sat where and which model played each seat,
every event (the deal, every ballot and mission card included), the public
record, what each AI seat thought, and every model turn with exactly what the
model was shown and what it answered. It reveals every secret of the game, so
it is meant for a game that is over.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agents.personas import persona_for
from app.agents.thoughts import Thought
from app.agents.turns import TurnRecord
from app.api.deps import database_for
from app.config import get_settings
from app.game.codec import encode_event
from app.game.public_log import public_log
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore
from app.storage.schema import games
from app.storage.thoughts import SqlThoughtStore
from app.storage.turns import SqlTurnStore

FORMAT = "avalon-game-record/1"


def game_record(database: Database, game_id: str) -> dict[str, Any]:
    room = SqlRoomStore(database).by_game_id(game_id)
    if room is None:
        raise LookupError(f"No game {game_id} in this database.")
    repository = SqlGameRepository(database)
    state = repository.load(game_id)
    events = repository.events(game_id)

    def thought(item: Thought) -> dict[str, Any]:
        return {"version": item.version, "player_id": item.player_id, "text": item.text}

    def turn(item: TurnRecord) -> dict[str, Any]:
        return {
            "version": item.version,
            "player_id": item.player_id,
            "driver": item.driver,
            "source": item.source,
            "fallback_reason": item.fallback_reason,
            "attempts": item.attempts,
            "duration_ms": item.duration_ms,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "observation": item.observation,
            "exchanges": list(item.exchanges),
        }

    return {
        "format": FORMAT,
        "exported_at": datetime.now(UTC).isoformat(),
        "game_id": game_id,
        "room": {
            "code": room.code,
            "seed": room.seed,
            "gm": room.gm,
            "language": room.language,
            "spectated": room.spectator is not None,
        },
        "seats": [
            {
                "player_id": seat.player_id,
                "seat": index,
                "name": seat.name,
                "is_bot": seat.is_bot,
                "agent": (seat.agent or "random") if seat.is_bot else None,
                "driver": seat.driver,
                "style": seat.style,
                "persona": persona.title
                if (persona := persona_for(seat.name)) and seat.is_bot
                else None,
                "role": next(
                    (p.role.value for p in state.players if p.id == seat.player_id and p.role),
                    None,
                ),
            }
            for index, seat in enumerate(room.seats)
        ],
        "result": {
            "phase": state.phase.value,
            "winner": state.winner.value if state.winner else None,
            "reason": state.win_reason.value if state.win_reason else None,
            "version": state.version,
        },
        "events": [
            {"version": version, "type": kind, "payload": payload}
            for version, (kind, payload) in enumerate(map(encode_event, events), start=1)
        ],
        "public_log": [entry.to_json() for entry in public_log(events)],
        "thoughts": [thought(item) for item in SqlThoughtStore(database).for_game(game_id)],
        "model_turns": [turn(item) for item in SqlTurnStore(database).for_game(game_id)],
    }


def _list(database: Database) -> None:
    with database.transaction() as connection:
        rows = connection.execute(
            select(games.c.id, games.c.created_at, games.c.version, games.c.winner).order_by(
                games.c.created_at
            )
        )
        for row in rows:
            print(
                f"{row.id}  {row.created_at:%Y-%m-%d %H:%M}  events={row.version}  winner={row.winner}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.records", description=__doc__.split("\n")[0]
    )
    parser.add_argument("game_id", nargs="?")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    database = database_for(get_settings())
    if database is None:
        parser.error("Games are kept in memory (DATABASE_URL=memory); there is nothing to export.")
    if args.game_id is None:
        _list(database)
        return 0
    record = game_record(database, args.game_id)
    out: Path = args.out or Path("records") / f"{args.game_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(record['events'])} events, {len(record['model_turns'])} model turns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
