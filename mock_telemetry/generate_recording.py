"""
Mock Telemetry Recording Generator
===================================
This script is a ONE-TIME UTILITY to produce `recording.json` — a captured
data stream that pretends to be what a real JetRacer ROS robot would emit
during one race session.

The actual race-day software (the dashboard) does NOT contain any of the
robot's decision logic.  All the rules below — battery thresholds,
humidity → speed mapping, pit-stop decisions, strategy selection — will
live ON THE ROBOT itself when we connect the real hardware.

This file just bakes one example session into JSON so we have realistic
data to render while the robot is being built.

Run with:
    python mock_telemetry/generate_recording.py

Output:
    mock_telemetry/recording.json
"""

import json
import math
import os
import random
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Robot's onboard rules (LIVE ONLY HERE — they will be re-implemented in C++/
# Python on the JetRacer itself).  Once the real robot exists, this script
# is no longer needed; the dashboard will just subscribe to ROS topics.
# ---------------------------------------------------------------------------
LAP_LENGTH_M           = 5793.0
TICK_HZ                = 20            # robot publishes at 20 Hz
NUM_LAPS               = 5
PIT_LANE_CSV           = "pit_coodrds.csv"

# Robot's own decision thresholds (mirrors what we'll flash to the JetRacer)
BATTERY_PIT_THRESHOLD  = 25.0          # %
PIT_STOP_DURATION_S    = 5.0
BATTERY_DRAIN_PER_M    = 0.0146        # %/m
BATTERY_RECHARGE_PER_S = (100.0 / PIT_STOP_DURATION_S)

# Robot's speed model
# (Note: pit_coodrds.csv coordinates aren't real metres — its polyline is
# ~6295 "units" long. We treat 1 unit = 1 m here for simplicity. To keep
# the pit-lane traversal short on screen we just use a higher value.)
DRY_CRUISE_SPEED       = 70.0          # units/s
WET_CRUISE_SPEED       = 50.0          # units/s when humidity > 70 %
PIT_LANE_SPEED         = 350.0         # units/s  → ~18 s through full pit lane

# Resource consumption rates (per metre traveled on the main track)
FUEL_DRAIN_PER_M       = 0.0090
TIRE_WEAR_PER_M        = 0.0085


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _polyline_length(points):
    cum = [0.0]
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        cum.append(cum[-1] + math.hypot(dx, dy))
    return cum, cum[-1] if cum else 0.0


def _interp_along(points, cum, total, d):
    if not points:
        return (0.0, 0.0)
    if d <= 0 or total <= 0:
        return points[0]
    if d >= total:
        return points[-1]
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= d:
            lo = mid
        else:
            hi = mid
    seg = cum[hi] - cum[lo]
    if seg <= 1e-9:
        return points[lo]
    t = (d - cum[lo]) / seg
    return (
        points[lo][0] + t * (points[hi][0] - points[lo][0]),
        points[lo][1] + t * (points[hi][1] - points[lo][1]),
    )


def _strategy_from_state(battery, tire_wear, fuel, humidity):
    """Robot's strategy selector."""
    if humidity > 70:
        return "RELIABILITY"
    if battery < 30 or fuel < 30:
        return "SUSTAINABILITY"
    if tire_wear > 60:
        return "RELIABILITY"
    if fuel > 70 and tire_wear < 30:
        return "PERFORMANCE"
    return "BALANCED"


# ---------------------------------------------------------------------------
# Main session simulation
# ---------------------------------------------------------------------------
def generate(out_path: Path):
    here = Path(__file__).resolve().parent.parent
    pit_csv = here / PIT_LANE_CSV
    if pit_csv.exists():
        df = pd.read_csv(pit_csv)
        pit_points = [(float(r["X"]), float(r["Y"])) for _, r in df.iterrows()]
    else:
        print(f"⚠ pit lane CSV not found at {pit_csv}; using empty path")
        pit_points = []
    pit_cum, pit_total = _polyline_length(pit_points)
    pit_box_dist = pit_total * 0.5 if pit_total else 0.0

    dt = 1.0 / TICK_HZ
    samples = []
    timestamp = 0.0

    # Robot internal state
    mode = "track"          # "track" | "pit_lane" | "pit_stop"
    track_dist = 0.0
    pit_dist = 0.0
    cum_distance = 0.0
    lap = 1

    battery = 100.0
    fuel = 100.0
    tire_wear = 0.0
    humidity = 45.0
    weather = "dry"

    pit_stop_timer = 0.0
    has_stopped_this_pit = False

    # Run a few laps
    while lap <= NUM_LAPS:
        # ----- humidity drift (the robot reads it from its sensor) ---------
        humidity += random.uniform(-0.4, 0.4)
        humidity = max(20.0, min(95.0, humidity))
        # Random chance of weather flip
        if random.random() < 0.0005:
            weather = "rain" if weather == "dry" else "dry"
            humidity = 80.0 if weather == "rain" else 45.0

        # ----- mode-driven physics step ------------------------------------
        if mode == "track":
            target = WET_CRUISE_SPEED if humidity > 70 else DRY_CRUISE_SPEED
            speed = target + 6.0 * math.sin(timestamp * 0.4)
            moved = speed * dt
            track_dist += moved
            cum_distance += moved
            battery   = max(0.0, battery   - BATTERY_DRAIN_PER_M * moved)
            fuel      = max(0.0, fuel      - FUEL_DRAIN_PER_M    * moved)
            tire_wear = min(100.0, tire_wear + TIRE_WEAR_PER_M   * moved)

            x, y = (None, None)  # main-track positions resolved by renderer

            if track_dist >= LAP_LENGTH_M:
                track_dist -= LAP_LENGTH_M
                lap += 1
                if lap > NUM_LAPS:
                    break
                # Robot's decision: low battery → enter pit lane
                if battery < BATTERY_PIT_THRESHOLD and pit_total > 0:
                    mode = "pit_lane"
                    pit_dist = 0.0
                    has_stopped_this_pit = False
                    # Stamp the first pit-lane position so consumers don't
                    # see a None on the transition frame.
                    if pit_points:
                        track_dist = 0.0  # reset for clarity

        elif mode == "pit_lane":
            speed = PIT_LANE_SPEED
            moved = speed * dt
            pit_dist += moved
            cum_distance += moved
            battery = max(0.0, battery - BATTERY_DRAIN_PER_M * 0.3 * moved)
            # Always emit a valid (x, y) when on the pit lane
            x, y = _interp_along(pit_points, pit_cum, pit_total, pit_dist)
            if x is None or y is None:
                # Should never happen given our interp, but be safe
                x, y = pit_points[0] if pit_points else (0.0, 0.0)

            if (not has_stopped_this_pit) and pit_dist >= pit_box_dist:
                mode = "pit_stop"
                pit_stop_timer = 0.0
            elif pit_dist >= pit_total:
                mode = "track"
                track_dist = 0.0
                pit_dist = 0.0

        elif mode == "pit_stop":
            speed = 0.0
            pit_stop_timer += dt
            battery = min(100.0, battery + BATTERY_RECHARGE_PER_S * dt)
            x, y = _interp_along(pit_points, pit_cum, pit_total, pit_box_dist)
            if pit_stop_timer >= PIT_STOP_DURATION_S:
                battery = 100.0
                # Pit stop also tops up the other consumables (robot's logic)
                fuel = 100.0
                tire_wear = 0.0
                has_stopped_this_pit = True
                mode = "pit_lane"

        else:
            speed = 0.0
            x, y = (None, None)

        strategy = _strategy_from_state(battery, tire_wear, fuel, humidity)
        is_in_pit_lane = mode in ("pit_lane", "pit_stop")
        is_charging    = mode == "pit_stop"

        # ----- emit a sample (one ROS publish tick) ------------------------
        samples.append({
            "t":              round(timestamp, 3),
            "mode":           mode,
            "lap":            lap,
            "track_distance": round(track_dist, 2),
            "pit_distance":   round(pit_dist, 2),
            "cum_distance":   round(cum_distance, 2),
            "speed":          round(speed, 3),
            "x":              None if x is None else round(x, 3),
            "y":              None if y is None else round(y, 3),
            "battery":        round(battery, 2),
            "fuel":           round(fuel, 2),
            "tire_wear":      round(tire_wear, 2),
            "humidity":       round(humidity, 1),
            "weather":        weather,
            "strategy":       strategy,
            "is_in_pit_lane": is_in_pit_lane,
            "is_charging":    is_charging,
        })

        timestamp += dt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "lap_length_m": LAP_LENGTH_M,
            "tick_hz":      TICK_HZ,
            "num_laps":     NUM_LAPS,
            "duration_s":   round(timestamp, 2),
            "samples":      len(samples),
            "note": (
                "Recording of one JetRacer session. The robot's onboard logic "
                "(battery threshold, humidity-to-speed mapping, pit decision, "
                "strategy selector) is NOT in the dashboard — it ran on the "
                "robot when this recording was made. The dashboard is just a "
                "viewer that replays this file at real time, and at race day "
                "the same data shape will arrive live over ROS instead."
            ),
        },
        "samples": samples,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"✓ Wrote {len(samples)} samples ({timestamp:.1f} s) → {out_path}")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "recording.json"
    generate(out)
