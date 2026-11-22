from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ServiceDep
from app.api.errors import ApiError
from app.api.schemas import ConfigOut, CreateRoomRequest, ErrorOut, GameOut, RoomCreatedOut

router = APIRouter(tags=["rooms"])


@router.post(
    "/rooms",
    status_code=201,
    response_model=RoomCreatedOut,
    responses={409: {"model": ErrorOut}, 422: {"model": ErrorOut}},
)
def create_room(request: CreateRoomRequest, service: ServiceDep) -> RoomCreatedOut:
    """Create a single-player room: you host, bots fill the other seats.

    The response is the only time the reconnect token is shown.
    """
    if request.ai_seats > request.player_count - 1:
        raise ApiError(422, "too_many_ai_seats", "There are not that many bot seats at this table.")
    if (request.ai_seats > 0 or request.gm == "ai") and not service.llm_available:
        raise ApiError(409, "llm_not_configured", "This server has no language model configured.")

    created = service.create_room(
        request.nickname,
        request.player_count,
        ai_seats=request.ai_seats,
        ai_style=request.ai_style,
        gm=request.gm,
        language=request.language,
    )
    room = created.session.room
    return RoomCreatedOut(
        room_code=room.code,
        game_id=room.game_id,
        player_id=created.session.seat.player_id,
        token=created.token,
        game=GameOut.from_snapshot(service.snapshot(created.session), room),
    )


@router.get("/config", response_model=ConfigOut)
def get_config(service: ServiceDep) -> ConfigOut:
    """What this server offers, so the lobby only shows choices that will work."""
    return ConfigOut(llm_available=service.llm_available)
