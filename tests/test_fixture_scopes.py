"""The two environment fixtures have DIFFERENT scopes, and both matter. §16.3.

`env` is session-scoped because `start_local` is shareable, and booting one
dev server per test raced its own ports -- three sightings of an intermittent
`Failed connecting to test server` fixture error before it was fixed.

`skip_env` must stay function-scoped: a time-skipping environment cannot be
shared, and these tests advance the clock by a year. Sharing one would let a
test that jumps forward decide what "now" means for every test after it, and
the failure would look like a flake rather than a scope mistake.

Asserted against pytest-asyncio's own marker rather than by reading the source,
so a reformat cannot fake a pass and a real change cannot hide behind one.
"""
from tests import conftest


def test_env_is_shared_for_the_whole_session():
    marker = conftest.env._fixture_function_marker
    assert marker.scope == "session", (
        "one dev server per test is what caused the intermittent startup "
        "failure -- see docs/RULINGS.md")
    assert conftest.env._loop_scope == "session", (
        "a session-scoped async fixture needs a session-scoped loop, or the "
        "client is used from a loop it was not created on")


def test_skip_env_is_never_shared():
    marker = conftest.skip_env._fixture_function_marker
    assert marker.scope == "function", (
        "§16.3 -- time-skipping environments cannot be shared between tests")
