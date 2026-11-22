from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ServiceDep
from app.api.schemas import CreateRoomRequest, ErrorOut, GameOut, RoomCreatedOut

router = APIRouter(tags=["rooms"])


@router.post(
    "/rooms",
    status_code=201,
    response_model=RoomCreatedOut,
    responses={422: {"model": ErrorOut}},
)
def create_room(request: CreateRoomRequest, service: ServiceDep) -> RoomCreatedOut:
    """Create a single-player room: you host, bots fill the other seats.

    The response is the only time the reconnect token is shown.
    """
    created = service.create_room(request.nickname, request.player_count)
    room = created.session.room
    return RoomCreatedOut(
        room_code=room.code,
        game_id=room.game_id,
        player_id=created.session.seat.player_id,
        token=created.token,
        game=GameOut.from_view(created.view, room),
    )
