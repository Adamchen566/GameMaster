from fastapi import FastAPI

from app.api import games, rooms
from app.api.errors import install_error_handlers
from app.config import get_settings
from app.observability import configure_logging, install_request_logging

_settings = get_settings()
configure_logging(_settings.log_format, _settings.log_level)

app = FastAPI(title="Avalon AI Game Master")
install_request_logging(app)
install_error_handlers(app)
app.include_router(rooms.router)
app.include_router(games.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
