"""Swarm state management package."""

# Intentionally left lightweight so importing `src.swarm.database` does not
# eagerly pull in the Pydantic model layer during tests and tooling.
