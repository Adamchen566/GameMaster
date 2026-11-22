from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import ServiceDep, SessionDep
from app.api.schemas import ActionRequest, ErrorOut, GameOut

router = APIRouter(tags=["games"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorOut} for status in (401, 403, 404, 409, 422)
}


@router.get("/games/{game_id}", response_model=GameOut, responses=_ERRORS)
def get_game(session: SessionDep, service: ServiceDep) -> GameOut:
    """The game as your seat is allowed to see it."""
    # `view` also restarts a pending AI turn after a server restart.
    service.view(session)
    return GameOut.from_snapshot(service.snapshot(session), session.room)


@router.post("/games/{game_id}/actions", response_model=GameOut, responses=_ERRORS)
def submit_action(request: ActionRequest, session: SessionDep, service: ServiceDep) -> GameOut:
    """Submit one action. Random bots answer at once; model seats play in the background."""
    action = request.to_action(session.seat.player_id, session.room.seed)
    service.submit(session, action)
    return GameOut.from_snapshot(service.snapshot(session), session.room)
