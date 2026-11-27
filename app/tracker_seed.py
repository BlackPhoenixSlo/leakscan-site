"""Enable-time seed of a new watch (spec "Seed (service)"). Filled by the seed lane."""


def start(watch_id):
    """Run the seed for watch_id off the request thread (TRACKER_SEED_INLINE=1: inline, for tests)."""
    raise NotImplementedError
