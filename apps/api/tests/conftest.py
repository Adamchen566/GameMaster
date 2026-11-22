"""Settings every test starts from."""

from __future__ import annotations

import os

# Tests must not depend on what happens to be installed or configured on the machine
# running them (an API key in the environment, a logged-in Claude Code). A test that
# wants a driver asks for it explicitly.
os.environ["LLM_DRIVERS"] = "none"
