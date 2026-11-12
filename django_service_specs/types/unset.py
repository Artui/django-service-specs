from __future__ import annotations

from typing import final


@final
class UnsetType:
    """Singleton sentinel type. Always falsy; identity-equal to itself only.

    Don't instantiate this directly — use the module-level ``UNSET`` singleton.
    ``UnsetType()`` returns that same instance, but the sentinel is the value
    you compare against and ``UnsetType`` is only useful as a type annotation.
    """

    _instance: UnsetType | None = None

    def __new__(cls) -> UnsetType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False

    def __copy__(self) -> UnsetType:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> UnsetType:
        return self


UNSET: UnsetType = UnsetType()
