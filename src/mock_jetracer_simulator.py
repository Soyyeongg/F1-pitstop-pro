"""
Mock JetRacer Simulator (Pure Replay Player)
============================================
This software is a VIEWER/RENDERER ONLY.  It contains zero robot logic:
no battery thresholds, no humidity-to-speed math, no pit-stop decisions,
no strategy rules.  All of that lives ON THE ROBOT.

This module just replays a previously-recorded telemetry stream from
`mock_telemetry/recording.json` (produced by
`mock_telemetry/generate_recording.py`).  At race day, the same data
shape will arrive live over ROS, and we'll swap this class for
`JetRacerBridge` (src/jetracer_bridge.py) without touching the rest
of the app.

Public API (used by race_replay.py)
-----------------------------------
    sim = MockJetRacerSimulator(monza_lap_length_m=5793.0)

    sim.set_pitting(...)         # API stub kept for compatibility
    sim.set_avoiding(...)        # API stub kept for compatibility

    sim.current_distance_m       # cumulative meters (from recording)
    sim.track_distance_m         # distance along current main-track lap
    sim.get_distance_traveled()  # cumulative, auto-updates
    sim.get_speed()              # m/s
    sim.get_position()           # (x, y) from recording when on pit lane
    sim.is_in_pit_lane           # bool
    sim.is_charging              # bool
    sim.battery_pct              # 0..100
    sim.fuel_pct                 # 0..100
    sim.tire_wear_pct            # 0..100
    sim.humidity_pct             # 0..100
    sim.weather                  # "dry" | "rain"
    sim.strategy                 # "PERFORMANCE" | "BALANCED" | ...
    sim.get_lap_number()         # 1-based
    sim.get_odometry()           # ROS-style dict
"""

import json
import time
from pathlib import Path
from typing import List, Optional, Tuple


PathPoint = Tuple[float, float]


class _SilentMissingRecording(Exception):
    pass


def _load_recording(path: Path) -> dict:
    """Load the JSON recording, regenerating it on demand if missing."""
    if not path.exists():
        # Auto-generate on first run so users don't have to remember to do it
        try:
            import importlib.util
            gen_path = path.parent / "generate_recording.py"
            if gen_path.exists():
                print(f"ℹ Generating recording (one-time): {path}")
                spec = importlib.util.spec_from_file_location("gen_rec", gen_path)
                mod = importlib.util.module_from_spec(spec)            # type: ignore
                spec.loader.exec_module(mod)                            # type: ignore
                mod.generate(path)
        except Exception as e:
            raise _SilentMissingRecording(
                f"Could not load or generate {path}: {e}"
            )
    with open(path, "r") as f:
        return json.load(f)


class MockJetRacerSimulator:
    """
    Pure-replay player for a recorded JetRacer ROS telemetry stream.
    Does not contain any decision-making code; just reads the next sample
    based on wall-clock elapsed time and exposes the values.
    """

    DEFAULT_RECORDING = (
        Path(__file__).resolve().parent.parent / "mock_telemetry" / "recording.json"
    )

    def __init__(self,
                 monza_lap_length_m: float = 5793.0,
                 recording_path: Optional[Path] = None,
                 loop: bool = True):
        self.lap_length_m = float(monza_lap_length_m)
        self._loop = bool(loop)

        # ---- Load recorded session ----------------------------------------
        path = Path(recording_path) if recording_path else self.DEFAULT_RECORDING
        try:
            payload = _load_recording(path)
            self._meta = payload.get("meta", {})
            self._samples: List[dict] = payload.get("samples", [])
        except Exception as e:
            print(f"⚠ Could not load recording ({e}); falling back to empty stream")
            self._meta = {}
            self._samples = []

        if self._samples:
            self._duration_s = float(self._samples[-1].get("t", 0.0))
        else:
            self._duration_s = 0.0

        # ---- Playback state -----------------------------------------------
        self._start_wallclock: float = time.time()
        self._cursor: int = 0   # last index that was current

        # ---- Latest values (mirror the most recent sample) ---------------
        self.mode: str = "track"
        self.track_distance_m: float = 0.0
        self.pit_distance_m: float = 0.0
        self.current_distance_m: float = 0.0
        self.current_speed: float = 0.0
        self._last_pos: PathPoint = (0.0, 0.0)
        self.lap_number: int = 1

        self.battery_pct: float = 100.0
        self.fuel_pct: float = 100.0
        self.tire_wear_pct: float = 0.0
        self.humidity_pct: float = 45.0
        self.weather: str = "dry"
        self.strategy: str = "BALANCED"

        self.is_in_pit_lane: bool = False
        self.is_charging: bool = False

        # ---- API-compat stubs --------------------------------------------
        self.is_pitting: bool = False
        self.is_avoiding: bool = False

        # Prime initial values from sample 0
        if self._samples:
            self._apply_sample(self._samples[0])

    # ----- API-compat hooks (no-ops here; robot owns these decisions) -----
    def set_pitting(self, pitting: bool) -> None:
        # Status comes from the recording / robot, not from the dashboard.
        # We accept the call so the existing host code keeps working.
        pass

    def set_avoiding(self, avoiding: bool) -> None:
        self.is_avoiding = bool(avoiding)

    # ===================================================================
    # Replay engine
    # ===================================================================
    def _apply_sample(self, s: dict) -> None:
        self.mode             = s.get("mode", self.mode)
        self.track_distance_m = float(s.get("track_distance", 0.0))
        self.pit_distance_m   = float(s.get("pit_distance", 0.0))
        self.current_distance_m = float(s.get("cum_distance", 0.0))
        self.current_speed    = float(s.get("speed", 0.0))
        self.lap_number       = int(s.get("lap", 1))

        self.battery_pct      = float(s.get("battery", self.battery_pct))
        self.fuel_pct         = float(s.get("fuel", self.fuel_pct))
        self.tire_wear_pct    = float(s.get("tire_wear", self.tire_wear_pct))
        self.humidity_pct     = float(s.get("humidity", self.humidity_pct))
        self.weather          = str(s.get("weather", self.weather))
        self.strategy         = str(s.get("strategy", self.strategy))

        self.is_in_pit_lane   = bool(s.get("is_in_pit_lane", False))
        self.is_charging      = bool(s.get("is_charging", False))
        self.is_pitting       = self.is_in_pit_lane

        x = s.get("x"); y = s.get("y")
        if x is not None and y is not None:
            self._last_pos = (float(x), float(y))

    def update(self) -> None:
        """Advance the cursor to the sample matching wall-clock time."""
        if not self._samples:
            return

        elapsed = time.time() - self._start_wallclock

        # Loop playback by wrapping elapsed time
        if self._loop and self._duration_s > 0 and elapsed > self._duration_s:
            self._start_wallclock = time.time()
            self._cursor = 0
            elapsed = 0.0

        # Advance cursor forward to the latest sample whose t <= elapsed
        i = self._cursor
        n = len(self._samples)
        while i + 1 < n and self._samples[i + 1]["t"] <= elapsed:
            i += 1
        self._cursor = i
        self._apply_sample(self._samples[i])

    # ===================================================================
    # Public read API (stable contract with race_replay.py)
    # ===================================================================
    def get_distance_traveled(self) -> float:
        self.update()
        return self.current_distance_m

    def get_speed(self) -> float:
        self.update()
        return self.current_speed

    def get_position(self) -> Optional[PathPoint]:
        """Return (x, y) when on the pit lane (recorded by the robot).
        Returns None on the main track — the renderer resolves position
        there from `track_distance_m` against its own track polyline.
        """
        self.update()
        if self.is_in_pit_lane:
            return self._last_pos
        return None

    def get_lap_progress(self) -> float:
        return (self.track_distance_m % self.lap_length_m) / self.lap_length_m

    def get_lap_number(self) -> int:
        return self.lap_number

    def get_odometry(self) -> dict:
        """ROS-style /odom-shaped snapshot — same shape as JetRacerBridge."""
        self.update()
        x, y = self._last_pos
        return {
            "header": {"stamp": time.time(), "frame_id": "odom"},
            "child_frame_id": "base_link",
            "pose": {
                "position": {"x": x, "y": y, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            },
            "twist": {
                "linear":  {"x": self.current_speed, "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            "lap_number":     self.lap_number,
            "lap_progress":   self.get_lap_progress(),
            "battery_pct":    self.battery_pct,
            "fuel_pct":       self.fuel_pct,
            "tire_wear_pct":  self.tire_wear_pct,
            "humidity_pct":   self.humidity_pct,
            "weather":        self.weather,
            "strategy":       self.strategy,
            "is_in_pit_lane": self.is_in_pit_lane,
            "is_charging":    self.is_charging,
            "is_avoiding":    self.is_avoiding,
            "mode":           self.mode,
            "source":         "mock-replay",
        }

    # ===================================================================
    # Lifecycle
    # ===================================================================
    def reset(self) -> None:
        self._start_wallclock = time.time()
        self._cursor = 0
        if self._samples:
            self._apply_sample(self._samples[0])