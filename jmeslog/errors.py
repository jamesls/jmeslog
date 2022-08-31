from typing import List


class ValidationError(Exception):
    def __init__(self, errors: List[str]) -> None:
        self.errors = errors

    def __str__(self) -> str:
        new_line = '\n'
        return (
            f"The change entry is invalid:{new_line}{new_line}"
            f"{new_line.join(self.errors)}"
        )


class NoChangesFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("There are no pending changes.")
