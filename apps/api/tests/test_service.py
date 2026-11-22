from app.api.deps import get_service
from app.service import GameService


def test_app_uses_one_shared_service() -> None:
    assert get_service() is get_service()


def test_service_chooses_its_own_unpredictable_seeds() -> None:
    service = GameService()

    seeds = {service.create_room("Adam", 5).session.room.seed for _ in range(5)}

    assert len(seeds) == 5
    assert all(seed >= 0 for seed in seeds)


def test_token_from_one_service_means_nothing_to_another() -> None:
    created = GameService().create_room("Adam", 5)

    assert GameService().authenticate(created.token) is None
