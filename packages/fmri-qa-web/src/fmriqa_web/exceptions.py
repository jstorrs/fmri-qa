"""Exceptions `fmriqa_web` raises."""

from fmriqa.exceptions import FmriqaError

__all__ = ["InvalidResultError", "NameCollisionError"]


class NameCollisionError(FmriqaError, ValueError):
    """Two files would be filed under one name.

    The browser has no filesystem to refuse the second write, so naming refuses
    up front. `collisions` maps each contested filed name to the input names
    that would have received it.
    """

    def __init__(self, collisions: dict[str, tuple[str, ...]]) -> None:
        self.collisions = collisions
        detail = "; ".join(
            f"{filed!r} <- {', '.join(sources)}"
            for filed, sources in sorted(collisions.items())
        )
        super().__init__(f"files would be filed under the same name: {detail}")


class InvalidResultError(FmriqaError, ValueError):
    """A string handed to `bridge.document_json` is not an `analyze_json` result.

    `index` is the item's position and `problem` says what is wrong with it.
    """

    def __init__(self, index: int, problem: str) -> None:
        self.index = index
        self.problem = problem
        super().__init__(f"result {index} is not an analyze_json result: {problem}")
