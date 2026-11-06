"""
Spring Physics Engine for Windows Dynamic Island.
Implements damped harmonic oscillators (Hooke's law) for smooth, bouncy
Apple-like animations with overshoot and settling.
"""

from __future__ import annotations
import math


class SpringValue:
    """1D damped spring animator."""

    def __init__(
        self,
        initial: float = 0.0,
        stiffness: float = 280.0,
        damping: float = 22.0,
        mass: float = 1.0,
    ) -> None:
        self.value: float = float(initial)
        self.target: float = float(initial)
        self.velocity: float = 0.0
        self.stiffness: float = stiffness
        self.damping: float = damping
        self.mass: float = mass

    def set_target(self, target: float, impulse: float = 0.0) -> None:
        self.target = float(target)
        if impulse != 0.0:
            self.velocity += impulse

    def snap(self, value: float) -> None:
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0

    def step(self, dt: float) -> float:
        # Clamp dt to prevent instability on frame drops
        dt = min(max(dt, 0.001), 0.05)
        # Sub-stepping for high stiffness stability
        substeps = 2
        sub_dt = dt / substeps
        for _ in range(substeps):
            displacement = self.value - self.target
            spring_force = -self.stiffness * displacement
            damping_force = -self.damping * self.velocity
            acceleration = (spring_force + damping_force) / self.mass
            self.velocity += acceleration * sub_dt
            self.value += self.velocity * sub_dt

        if abs(self.value - self.target) < 0.08 and abs(self.velocity) < 0.5:
            self.value = self.target
            self.velocity = 0.0

        return self.value

    @property
    def is_settled(self) -> bool:
        return abs(self.value - self.target) < 0.1 and abs(self.velocity) < 0.8


class IslandPhysics:
    """Manages all animated dimensions of the Dynamic Island."""

    def __init__(self) -> None:
        # Main pill geometry (bouncy spring for expansion/contraction)
        self.width = SpringValue(126.0, stiffness=310.0, damping=21.0)
        self.height = SpringValue(36.0, stiffness=320.0, damping=22.0)
        self.corner_radius = SpringValue(18.0, stiffness=340.0, damping=25.0)

        # Secondary split circle (for multitasking: Music + Timer)
        # offset_x is distance from main pill's right edge to secondary circle center
        self.split_gap = SpringValue(0.0, stiffness=290.0, damping=19.0)
        self.split_size = SpringValue(0.0, stiffness=310.0, damping=20.0)

        # Content crossfade & hover scale
        self.expand_progress = SpringValue(0.0, stiffness=260.0, damping=24.0)
        self.hover_scale = SpringValue(1.0, stiffness=400.0, damping=26.0)
        self.alert_progress = SpringValue(0.0, stiffness=320.0, damping=22.0)
        self.y_offset = SpringValue(8.0, stiffness=280.0, damping=22.0)
        self.opacity = SpringValue(1.0, stiffness=260.0, damping=24.0)

    def set_preset(self, preset: str) -> None:
        """Switch physics feel: 'bouncy' (Apple-like), 'snappy', 'gentle', 'jelly'."""
        if preset == "bouncy":
            for s in (self.width, self.height, self.split_gap, self.split_size):
                s.stiffness = 300.0
                s.damping = 18.5
        elif preset == "snappy":
            for s in (self.width, self.height, self.split_gap, self.split_size):
                s.stiffness = 440.0
                s.damping = 31.0
        elif preset == "gentle":
            for s in (self.width, self.height, self.split_gap, self.split_size):
                s.stiffness = 190.0
                s.damping = 22.0
        elif preset == "jelly":
            for s in (self.width, self.height, self.split_gap, self.split_size):
                s.stiffness = 340.0
                s.damping = 12.5

    def step(self, dt: float) -> None:
        self.width.step(dt)
        self.height.step(dt)
        self.corner_radius.step(dt)
        self.split_gap.step(dt)
        self.split_size.step(dt)
        self.expand_progress.step(dt)
        self.hover_scale.step(dt)
        self.alert_progress.step(dt)
        self.y_offset.step(dt)
        self.opacity.step(dt)

    @property
    def is_settled(self) -> bool:
        return (
            self.width.is_settled
            and self.height.is_settled
            and self.corner_radius.is_settled
            and self.split_gap.is_settled
            and self.split_size.is_settled
            and self.opacity.is_settled
        )
