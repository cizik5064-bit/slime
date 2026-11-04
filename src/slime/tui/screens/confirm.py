"""Small yes/no and hold-to-confirm modals used for destructive actions."""

from __future__ import annotations

import time
from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

#: Seconds the user must keep Enter pressed for destructive confirmations.
HOLD_SECONDS = 5.0
#: How long without a repeated Enter key event counts as "released". This is
#: deliberately longer than the slowest common keyboard repeat delay (~1s).
_RELEASE_GRACE = 1.25
_HOLD_BAR_WIDTH = 24


class ConfirmScreen(ModalScreen[bool]):
    """Ask for confirmation and return ``True`` only on the confirm button."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel")
    ]

    def __init__(
        self,
        message: str,
        *,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        danger: bool = True,
    ) -> None:
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label
        self.danger = danger

    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Static(self.message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button(
                    self.confirm_label,
                    id="confirm",
                    variant="error" if self.danger else "primary",
                )
                yield Button(self.cancel_label, id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class HoldConfirmScreen(ModalScreen[bool]):
    """Require the user to hold Enter for several seconds.

    Terminal applications do not receive key-up events. While Enter is held,
    the terminal sends repeated key events, so the screen treats a gap between
    Enter presses as the key being released and resets the countdown.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel")
    ]

    def __init__(
        self,
        message: str,
        *,
        cancel_label: str = "Cancel",
        hint: str = "Hold Enter for 5 seconds to confirm.",
    ) -> None:
        super().__init__()
        self.message = message
        self.cancel_label = cancel_label
        self.hint = hint
        self._holding_since: float | None = None
        self._last_enter_at = 0.0

    def compose(self) -> ComposeResult:
        with Container(id="hold-confirm-dialog"):
            yield Static(self.message, id="hold-confirm-message")
            yield Static(self.hint, id="hold-confirm-status")
            with Horizontal(id="hold-confirm-buttons"):
                yield Button(self.cancel_label, id="hold-cancel")

    def on_mount(self) -> None:
        # No widget should own the keyboard: Enter must reach on_key so the
        # repeated key events can drive the hold timer.
        self.set_focus(None)
        self.set_interval(0.1, self._tick)

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            self._enter_pressed()
            event.stop()
            event.prevent_default()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hold-cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _enter_pressed(self) -> None:
        now = time.monotonic()
        if self._holding_since is None:
            self._holding_since = now
        self._last_enter_at = now
        self._render_progress(now)

    def _tick(self) -> None:
        if self._holding_since is None:
            return
        now = time.monotonic()
        if now - self._last_enter_at > _RELEASE_GRACE:
            self._reset()
            return
        if now - self._holding_since >= HOLD_SECONDS:
            self.dismiss(True)
            return
        self._render_progress(now)

    def _render_progress(self, now: float) -> None:
        assert self._holding_since is not None
        elapsed = max(0.0, now - self._holding_since)
        fraction = min(1.0, elapsed / HOLD_SECONDS)
        filled = int(fraction * _HOLD_BAR_WIDTH)
        bar = "█" * filled + "░" * (_HOLD_BAR_WIDTH - filled)
        remaining = max(0.0, HOLD_SECONDS - elapsed)
        self.query_one("#hold-confirm-status", Static).update(
            f"{self.hint}\n[bold bright_green]{bar}[/bold bright_green] "
            f"{remaining:.1f}s"
        )

    def _reset(self) -> None:
        self._holding_since = None
        self._last_enter_at = 0.0
        self.query_one("#hold-confirm-status", Static).update(self.hint)


__all__ = ["HOLD_SECONDS", "ConfirmScreen", "HoldConfirmScreen"]
