from fastapi import FastAPI

from app.api import games, rooms
from app.api.errors import install_error_handlers

app = FastAPI(title="Avalon AI Game Master")
install_error_handlers(app)
app.include_router(rooms.router)
app.include_router(games.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
