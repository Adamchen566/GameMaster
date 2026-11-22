from __future__ import annotations

from fastapi import APIRouter

from app.agents.personas import PERSONAS
from app.api.deps import ServiceDep
from app.api.errors import ApiError
from app.api.schemas import (
    ConfigOut,
    CreateRoomRequest,
    DriverOut,
    ErrorOut,
    GameOut,
    RoomCreatedOut,
    SeatPersonaOut,
)

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
    bot_seats = request.player_count if request.spectate else request.player_count - 1
    if request.ai_seats > bot_seats:
        raise ApiError(422, "too_many_ai_seats", "There are not that many bot seats at this table.")
    if request.ai_seats > 0 and request.seats is None and not service.llm_available:
        raise ApiError(409, "llm_not_configured", "This server has no language model configured.")
    if request.gm == "ai" and not service.gm_ai_available:
        raise ApiError(409, "llm_not_configured", "This server has no model for the game master.")
    if request.seats is not None:
        if len(request.seats) != bot_seats:
            raise ApiError(
                422, "wrong_seat_count", f"This table has {bot_seats} bot seats to fill."
            )
        for choice in {choice for choice in request.seats if choice != "bot"}:
            driver = service.drivers.get(choice)
            if driver is None or not driver.available:
                raise ApiError(
                    409, "driver_unavailable", f"This server cannot use '{choice}' right now."
                )

    created = service.create_room(
        request.nickname,
        request.player_count,
        ai_seats=request.ai_seats,
        ai_style=request.ai_style,
        gm=request.gm,
        language=request.language,
        seats=request.seats,
        spectate=request.spectate,
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
    return ConfigOut(
        llm_available=service.llm_available,
        gm_ai_available=service.gm_ai_available,
        drivers=[
            DriverOut(
                id=driver.id,
                label=driver.label,
                available=driver.available,
                problem=driver.current_problem(),
            )
            for driver in service.drivers.values()
        ],
        personas=[
            SeatPersonaOut(
                name=persona.name, title=persona.title, manner=persona.manner, color=persona.color
            )
            for persona in PERSONAS
        ],
    )
