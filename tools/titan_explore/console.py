"""Questions asked to the user in the terminal (injectable input and output)."""

from __future__ import annotations

from collections.abc import Callable

_YES = {"y", "yes"}
_NO = {"n", "no"}


class Console:
    def __init__(self, input_fn: Callable[[str], str] = input, output_fn: Callable[..., None] = print) -> None:
        self._input = input_fn
        self._print = output_fn

    def say(self, text: str) -> None:
        self._print(text)

    def pause(self, text: str) -> None:
        self._input(f"{text} [Enter] ")

    def ask_yes_no(self, question: str) -> bool:
        while True:
            answer = self._input(f"{question} (y/n) ").strip().lower()
            if answer in _YES:
                return True
            if answer in _NO:
                return False
            self._print("Answer \"y\" (yes) or \"n\" (no).")

    def ask_choice(self, question: str, choices: list[str]) -> str:
        listing = " / ".join(f"{index}) {choice}" for index, choice in enumerate(choices, 1))
        while True:
            answer = self._input(f"{question} [{listing}] ").strip().lower()
            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                return choices[int(answer) - 1]
            for choice in choices:
                if answer == choice.lower():
                    return choice
            self._print(f"Choose one of: {listing}.")

    def ask_text(self, question: str, allow_empty: bool = False) -> str:
        while True:
            answer = self._input(f"{question} ").strip()
            if answer or allow_empty:
                return answer
            self._print("An answer is required.")

    def confirm_typed(self, question: str, word: str = "YES") -> bool:
        """Confirmation of a risky action: only typing `word` exactly counts as consent."""
        return self._input(f"{question} (type {word} to confirm) ").strip() == word
