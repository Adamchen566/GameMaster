"""The rules engine must stay free of framework, database and model imports."""

import ast
import sys
from pathlib import Path

import app.game

GAME_PACKAGE = Path(app.game.__file__).parent


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "use absolute imports inside app.game"
            assert node.module is not None
            modules.add(node.module)
    return modules


def test_game_package_imports_only_the_standard_library_and_itself() -> None:
    files = sorted(GAME_PACKAGE.glob("*.py"))
    assert files, "the game package should contain modules"

    for path in files:
        for module in imported_modules(path.read_text(encoding="utf-8")):
            inside_package = module == "app.game" or module.startswith("app.game.")
            standard_library = module.split(".")[0] in sys.stdlib_module_names

            assert inside_package or standard_library, f"{path.name} imports {module}"
