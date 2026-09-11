"""Deterministic anchored and rolling walk-forward window generation."""

from __future__ import annotations

from trading_bot.domain.identifiers import deterministic_id
from trading_bot.validation.models import (
    EvaluationRange,
    WalkForwardMode,
    WalkForwardSpec,
    WalkForwardWindow,
)


def generate_walk_forward_windows(spec: WalkForwardSpec) -> tuple[WalkForwardWindow, ...]:
    windows: list[WalkForwardWindow] = []
    oos_start = spec.first_oos_start
    sequence = 0
    while oos_start < spec.end:
        oos_end = min(oos_start + spec.oos_window, spec.end)
        if spec.mode is WalkForwardMode.ANCHORED:
            train_start = spec.train_start
        else:
            train_start = oos_start - spec.training_window
        training = EvaluationRange(train_start, oos_start)
        oos = EvaluationRange(oos_start, oos_end)
        data_start = train_start - spec.warmup_duration
        identifier = deterministic_id(
            "walk-forward-window-v1", spec, sequence, training, oos, data_start
        )
        windows.append(WalkForwardWindow(identifier, sequence, training, oos, data_start))
        sequence += 1
        oos_start += spec.step
    return tuple(windows)
