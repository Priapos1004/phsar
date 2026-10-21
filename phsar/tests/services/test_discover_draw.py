"""Discover's draw: a per-viewer shuffle bag over the worlds (docs/features/browse.md)."""

from uuid import uuid4

from app.services.browse_service import _REST, WORLDS, _cycle, world_for

N = len(WORLDS)
SEEDS = [uuid4() for _ in range(60)]
CYCLES = 6


def test_each_cycle_draws_every_world_once():
    for seed in SEEDS:
        for cycle in range(CYCLES):
            drawn = [world_for(seed, cycle * N + i) for i in range(N)]
            assert sorted(drawn) == sorted(WORLDS), f"{seed} cycle {cycle}"


def test_every_cycle_is_a_new_order():
    """A fixed order would replay the same rotation forever."""
    first, second = range(N), range(N, 2 * N)
    differ = sum([world_for(s, n) for n in first] != [world_for(s, n) for n in second] for s in SEEDS)
    assert differ == len(SEEDS)


def test_a_drawn_world_sits_out_its_rest():
    """Across cycle edges too, where two independent orders meet."""
    clashes = sum(
        bool(set(_cycle(seed, cycle)[:_REST]) & set(_cycle(seed, cycle - 1)[-_REST:]))
        for seed in SEEDS for cycle in range(1, CYCLES)
    )
    # Without one, this would pass with the edge rule deleted.
    assert clashes, "no edge where the plain orders bring a world back early"
    for seed in SEEDS:
        draws = [world_for(seed, n) for n in range(CYCLES * N)]
        for i, world in enumerate(draws):
            assert world not in draws[i + 1:i + 1 + _REST], (seed, i)
