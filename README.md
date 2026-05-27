# Pit-Stop Racer Pro 🏎️

A real-time **dashboard / viewer** for a JetRacer ROS robot that drives an F1-style track at Monza. The on-screen visuals show the car's position, speed, battery, fuel, tire wear, weather, strategy and pit-stop status — **streamed live from the robot**.

> **Architectural rule:** This software is a *renderer* only. All decision-making (when to pit, how fast to drive in the rain, which strategy to pick, etc.) lives **on the robot**. The dashboard never decides anything; it just draws what the robot publishes.

---

## Table of contents

1. [How the data flows](#how-the-data-flows)
2. [What the robot must publish](#what-the-robot-must-publish)
3. [Mock vs real — switching with one line](#mock-vs-real--switching-with-one-line)
4. [What lives on the JetRacer (firmware side)](#what-lives-on-the-jetracer-firmware-side)
5. [Mock recording (development)](#mock-recording-development)
6. [Building the real-world track](#building-the-real-world-track)
7. [Running](#running)
8. [Project layout](#project-layout)

---

## How the data flows

```
┌────────────────────────────────────────────────────────────────┐
│                  Pit-Stop Racer Pro (this app)                 │
│                                                                │
│   reads odometry / battery / fuel / tire / weather / strategy  │
│   draws Monza track + JetRacer dot + sidebars + banners        │
│   ❌ contains zero robot logic                                  │
└────────────────────────────────────────────────────────────────┘
                              ▲
                              │  same data shape
                              │
        ┌─────────────────────┴──────────────────────┐
        │                                            │
        ▼ DEV mode (no robot)                        ▼ RACE day (real robot)
┌─────────────────────────────┐         ┌─────────────────────────────────┐
│ MockJetRacerSimulator       │         │ JetRacerBridge                  │
│ (pure replay player)        │         │ (rclpy ROS2 subscriber)         │
│                             │         │                                 │
│ Replays a recorded JSON     │         │ Subscribes to                   │
│ stream at real time.        │         │   /jetracer/odom                │
│                             │         │   /jetracer/battery             │
│ Source file:                │         │   /jetracer/imu                 │
│  mock_telemetry/            │         │   /jetracer/telemetry  …        │
│  recording.json             │         │                                 │
└─────────────────────────────┘         └─────────────────────────────────┘
```

Both classes expose the **same Python interface** (`get_odometry()`, `get_position()`, `is_in_pit_lane`, `battery_pct`, `fuel_pct`, …) so the dashboard cannot tell which one it is talking to.

---

## What the robot must publish

The dashboard expects the JetRacer (or the recording, in dev mode) to provide a stream of values once per ~50 ms. Conceptually each "tick" is a single ROS publish that bundles together:

| Field            | Type   | Range / values                                     | Notes                                              |
|------------------|--------|----------------------------------------------------|----------------------------------------------------|
| `mode`           | str    | `"track"` \| `"pit_lane"` \| `"pit_stop"`           | Robot's own driving state                           |
| `pose.position.x`| float  | world coords (only meaningful on pit lane)         | meters in track frame                               |
| `pose.position.y`| float  | world coords (only meaningful on pit lane)         | meters in track frame                               |
| `track_distance` | float  | 0 .. 5793 m around current main-track lap           | mode == "track"                                    |
| `pit_distance`   | float  | 0 .. pit-lane polyline length                      | mode == "pit_lane" / "pit_stop"                     |
| `cum_distance`   | float  | total meters since session start                    |                                                    |
| `speed`          | float  | m/s (`twist.linear.x` in ROS Odometry)              |                                                    |
| `battery_pct`    | float  | 0..100                                              | from BMS or BatteryState voltage                    |
| `fuel_pct`       | float  | 0..100                                              | virtual / scenario-defined                          |
| `tire_wear_pct`  | float  | 0..100                                              | virtual / scenario-defined                          |
| `humidity_pct`   | float  | 0..100                                              | DHT-22 / SHT-31 / similar onboard sensor            |
| `weather`        | str    | `"dry"` \| `"rain"`                                  | derived by robot from humidity sensor               |
| `strategy`       | str    | `"PERFORMANCE"`/`"BALANCED"`/`"SUSTAINABILITY"`/`"RELIABILITY"` | robot's strategy selector output           |
| `lap_number`     | int    | 1-based                                             |                                                    |
| `is_in_pit_lane` | bool   | true when on pit-lane waypoints                     |                                                    |
| `is_charging`    | bool   | true while parked at pit box                        |                                                    |

When `mode == "track"`, position is resolved by the **dashboard** from `track_distance` against the precomputed Monza polyline (the renderer owns the track geometry). When `mode == "pit_lane"` or `"pit_stop"`, the dashboard uses the explicit `(x, y)` from the stream.

---

## Mock vs real — switching with one line

`src/interfaces/race_replay.py`:

```python
# DEV mode (current)
from src.mock_jetracer_simulator import MockJetRacerSimulator
self.jetracer_sim = MockJetRacerSimulator(monza_lap_length_m=MONZA_LAP_LENGTH_M)

# RACE day (real JetRacer robot)
from src.jetracer_bridge import JetRacerBridge
self.jetracer_sim = JetRacerBridge()
self.jetracer_sim.start()   # spins ROS2 subscriber thread
```

`src/jetracer_bridge.py` is already implemented; it uses `rclpy` to subscribe to the standard JetRacer ROS topics in a background thread.

---

## What lives on the JetRacer (firmware side)

The JetRacer ROS AI Kit (Jetson Nano / Orin Nano + IMU + camera + optional lidar + battery monitor) ships with a stock ROS2 stack that publishes `/jetracer/odom`, `/jetracer/battery`, `/jetracer/imu`, `/camera/image_raw`, etc. **Our race-day firmware extends that stack with five custom nodes** that together implement everything the dashboard expects to receive. None of this logic ever runs on the laptop — it all runs on the Jetson.

### Required ROS2 packages on the robot

```
jetracer_ws/
└── src/
    ├── jetracer_drive/             vendor stock — odometry + motor driver
    ├── jetracer_perception/        vendor stock — camera + (optional) lidar
    └── jetracer_race_brain/        ← OUR custom package — 5 nodes
        ├── line_follower_node.py
        ├── lap_tracker_node.py
        ├── consumables_node.py
        ├── strategy_node.py
        ├── pit_decision_node.py
        └── telemetry_pub_node.py
```

### Algorithms — node by node

#### 1. `line_follower_node` — the actual driver
Subscribes to `/camera/image_raw`, outputs `/cmd_vel`. Classic black-line follower.

```
loop @ 30 Hz:
    img        = subscribe(/camera/image_raw)
    roi        = img[bottom 30%]                       # only look at floor in front
    grey       = cv2.cvtColor(roi, BGR2GRAY)
    binary     = cv2.inRange(grey, 0, 60)              # black tape
    contours   = cv2.findContours(binary)
    if no contour: stop and search
    cx, cy     = centroid of largest contour
    error      = cx - (img.width / 2)                  # left/right offset
    steering   = clip(-Kp * error, -1, 1)              # P controller
    throttle   = base_speed * (1 - 0.5 * |steering|)   # slow on tight turns

    # Speed scaling from environment (subscribed below)
    if humidity > 70:  throttle *= 0.7                 # wet ⇒ slower
    if mode == "pit_lane": throttle = 0.25             # pit speed limit
    if mode == "pit_stop": throttle = 0.0              # frozen during stop

    publish(/cmd_vel, Twist(linear.x=throttle, angular.z=steering))
```

This single node already handles 80% of the demo: the robot drives the loop and respects pit-lane / wet-mode speed limits.

#### 2. `lap_tracker_node` — distance & lap counting
Subscribes to `/jetracer/odom`, publishes `/race/lap` (`uint32`) and `/race/track_distance` (`Float32`).

```
state:
    last_position      = (0, 0)
    track_distance     = 0
    cum_distance       = 0
    lap                = 1

on /odom:
    dx, dy = pose.position - last_position
    moved  = sqrt(dx² + dy²)
    cum_distance   += moved
    track_distance += moved

    # Detect start/finish crossing (one of two methods)
    METHOD A — colour line: subscribe /camera/image_raw, look for the
        coloured strip across the lane; rising edge ⇒ lap finished.
    METHOD B — physical loop length: when track_distance ≥ measured loop
        length (stored as parameter) ⇒ lap finished.

    if lap_just_finished:
        lap += 1
        track_distance = 0

    publish(/race/lap, lap)
    publish(/race/track_distance, track_distance)
    last_position = pose.position
```

Method B is simpler to start with (one parameter, no vision); method A is more robust to drift.

#### 3. `consumables_node` — virtual fuel / tires / humidity
This node is what makes a real RC-car feel like an F1 simulation. Most "consumables" are not real sensors — they're **virtual gauges** the robot maintains and publishes.

Subscribes to `/jetracer/odom` (for distance) and an optional `/dht22/raw` (for real humidity if a sensor is wired).
Publishes `/race/consumables` (custom msg or JSON).

```
state:
    fuel       = 100.0
    tire_wear  = 0.0
    humidity   = 45.0     # default if no sensor
    weather    = "dry"

on every odometry tick (Δd = distance moved this tick):
    # ---- virtual consumables (game logic) ----
    fuel       = max(0,   fuel       - 0.0090 * Δd)
    tire_wear  = min(100, tire_wear  + 0.0085 * Δd)

    # ---- real sensor read, if available ----
    if has_DHT22:
        humidity = read_DHT22()
    else:
        humidity = 45 + 5*sin(t) + noise         # gentle drift

    # ---- weather classification ----
    weather = "rain" if humidity > 70 else "dry"

    publish /race/consumables { fuel, tire_wear, humidity, weather }

on /race/pit_complete (from pit_decision_node):
    fuel = 100; tire_wear = 0     # "refuelled & new tires"
```

Real sensor option: an SHT-31 or DHT-22 wired to a Jetson GPIO via I²C costs ~$5 and gives genuine humidity readings — useful if you want to spray water on the track to demo "rain mode".

#### 4. `strategy_node` — pick a strategy label
A pure function of the current state. Subscribes to `/race/consumables`, `/jetracer/battery`, publishes `/race/strategy` (`String`).

```
on every consumables update:
    s = "BALANCED"                                     # default
    if weather == "rain":           s = "RELIABILITY"
    elif battery < 30 or fuel < 30: s = "SUSTAINABILITY"
    elif tire_wear > 60:            s = "RELIABILITY"
    elif fuel > 70 and tire_wear < 30: s = "PERFORMANCE"
    publish /race/strategy s
```

You can later swap this rule-based decision tree for an ML model (random forest, small neural net) without touching anything else — just re-publish on the same topic.

#### 5. `pit_decision_node` — when to enter the pit lane
Subscribes to `/jetracer/battery`, `/race/lap`, `/race/track_distance`. Publishes `/race/mode` (`String`: "track" / "pit_lane" / "pit_stop") and `/race/pit_complete` (`Empty`).

```
state:
    mode              = "track"
    pit_phase_started = 0
    has_stopped_this_pit = False

on every tick:
    if mode == "track":
        # Decision: low battery and crossing start/finish ⇒ enter pit
        if battery < 25 and just_crossed_start_finish:
            mode = "pit_lane"
            line_follower_topic = "/pit_lane_track"   # switch to pit branch line
            has_stopped_this_pit = False

    elif mode == "pit_lane":
        # Robot is following the pit branch tape. When it sees the
        # AprilTag / coloured square at the pit box, stop.
        if vision.sees("pit_box_marker") and not has_stopped_this_pit:
            mode = "pit_stop"
            pit_phase_started = now()
        elif vision.sees("pit_lane_exit_marker"):
            mode = "track"                  # rejoined main loop

    elif mode == "pit_stop":
        # Park for 5 s → publish "pit complete" so consumables_node refills
        if now() - pit_phase_started >= 5.0:
            publish /race/pit_complete
            mode = "pit_lane"
            has_stopped_this_pit = True

    publish /race/mode mode
```

The 5-second "charge" is wall-clock — there is no actual electrical charging happening in 5 s on a LiPo. It's a *gameplay* timer that triggers `pit_complete`, which makes the consumables node refill the virtual gauges. The dashboard sees that as battery jumping back to 100 %.

#### 6. `telemetry_pub_node` — bundle everything for the dashboard
This is the only node the dashboard actually subscribes to. It collects every `/race/*` and `/jetracer/*` topic into one combined message at ~20 Hz.

```
@ 20 Hz timer:
    msg = {
        "header": {"stamp": now()},
        "mode":           latest /race/mode,
        "lap_number":     latest /race/lap,
        "track_distance": latest /race/track_distance,
        "pit_distance":   latest /race/pit_distance,
        "cum_distance":   latest /race/cum_distance,
        "pose":           latest /jetracer/odom.pose,
        "twist":          latest /jetracer/odom.twist,
        "battery_pct":    latest /jetracer/battery.percentage * 100,
        "fuel_pct":       latest /race/consumables.fuel,
        "tire_wear_pct":  latest /race/consumables.tire_wear,
        "humidity_pct":   latest /race/consumables.humidity,
        "weather":        latest /race/consumables.weather,
        "strategy":       latest /race/strategy,
        "is_in_pit_lane": mode in {"pit_lane", "pit_stop"},
        "is_charging":    mode == "pit_stop",
    }
    publish /jetracer/telemetry msg
```

`JetRacerBridge` on the laptop side just subscribes to this single topic and exposes the values to the dashboard. **All robot-side complexity stops here.**

### Topic graph at a glance

```
                                   ┌────────────────────┐
   /camera/image_raw ─────────────▶│ line_follower_node │──▶ /cmd_vel
                                   └─────────┬──────────┘
                                             │ (uses /race/mode + /race/consumables for speed scaling)
                                             ▼
   /jetracer/odom ──┬──────────────▶ lap_tracker_node ────▶ /race/lap
                    │                                       /race/track_distance
                    │
                    └──────────────▶ consumables_node ─────▶ /race/consumables
                                              ▲
                                       (DHT-22 GPIO if wired)
                                              │
                                              ▼
                  ┌────────── strategy_node ◀─┴──── /jetracer/battery
                  │                          ▶ /race/strategy
                  │
                  ▼
          pit_decision_node ◀── /jetracer/battery, /race/lap
                  │              + camera (pit-box marker)
                  └─────────────▶ /race/mode, /race/pit_complete


   ─── all of the above ── telemetry_pub_node ──▶ /jetracer/telemetry
                                  │
                                  ▼
                    [ JetRacerBridge on laptop subscribes here ]
                                  │
                                  ▼
                       [ Dashboard renders it on screen ]
```

### Decision rules in one table (what to flash to the robot)

| Decision                | Rule                                                                          | Lives in node       |
|-------------------------|-------------------------------------------------------------------------------|---------------------|
| Pit-stop entry          | If `battery_pct < 25%` AND just crossed start/finish ⇒ enter pit lane          | `pit_decision_node` |
| Pit-stop charging       | Park at pit box for 5 s ⇒ refill battery / fuel / tires                        | `pit_decision_node` + `consumables_node` |
| Wet-weather speed       | If `humidity > 70%` ⇒ multiply throttle by 0.7                                 | `line_follower_node` |
| Pit-lane speed limit    | If `mode == "pit_lane"` ⇒ throttle = 0.25                                       | `line_follower_node` |
| Strategy selector       | wet→RELIABILITY, low fuel/batt→SUSTAINABILITY, fresh→PERFORMANCE, else BALANCED | `strategy_node`     |
| Lap counting            | track_distance ≥ loop length OR colour-line crossing ⇒ lap += 1                | `lap_tracker_node`  |

### Required Jetson dependencies

```bash
# On the JetRacer (Jetson Nano / Orin Nano running Ubuntu + ROS2 Humble)
sudo apt install ros-humble-cv-bridge ros-humble-image-transport
sudo apt install python3-opencv python3-numpy
pip install adafruit-circuitpython-dht   # only if using a real DHT-22 sensor
```

The five nodes above are <300 lines of Python each — most of the heavy lifting is delegated to `cv2`, `rclpy`, and the stock JetRacer odometry. A capable student team can flash and test all of them in roughly **2–3 weeks**.

### Suggested ROS2 message contract for `/jetracer/telemetry`

Two equally easy choices:

**Option A — single custom message** (`jetracer_msgs/RaceTelemetry`):

```yaml
# jetracer_msgs/msg/RaceTelemetry.msg
std_msgs/Header header
string mode
uint32 lap_number
float32 track_distance
float32 pit_distance
float32 cum_distance
geometry_msgs/Pose pose
geometry_msgs/Twist twist
float32 battery_pct
float32 fuel_pct
float32 tire_wear_pct
float32 humidity_pct
string  weather
string  strategy
bool    is_in_pit_lane
bool    is_charging
```

**Option B — JSON sidecar** (`std_msgs/String` with JSON payload). Easier — no custom-msg compilation, just `json.dumps()` on the robot, `json.loads()` on the laptop. `JetRacerBridge` already supports this.

---

## Mock recording (development)

When the real robot is unavailable, the dashboard reads `mock_telemetry/recording.json`. This file is produced by `mock_telemetry/generate_recording.py`, which is **the only place where simulated robot logic exists**. The dashboard codebase itself is logic-free.

```bash
# (Re)generate the mock recording (rules live in this script only)
python mock_telemetry/generate_recording.py
```

The recording is a JSON document containing `meta` + a list of `samples`. The dashboard's `MockJetRacerSimulator` simply walks the cursor through these samples in real time, copying their values into the same fields a real robot would publish.

If you tweak the rules in `generate_recording.py` (drain rates, pit threshold, weather model, …) you only need to re-run that one script — the dashboard never changes.

---

## Building the real-world track

> **TL;DR** — the dashboard already has `monza_circuit_map.csv` as the on-screen Monza geometry. You just need to build a *miniature, same-shape* tape track on the floor and tell the bridge what scale factor to use. The math is one multiplication.

### How the mapping really works

```
[Real floor — small Monza-shaped tape track]
       ↓
[JetRacer wheel-odometry → /odom: (x_real_m, y_real_m)]
       ↓
[JetRacerBridge applies: x_dashboard = x_real * SCALE_FACTOR]
       ↓
[Dashboard plots the dot on top of monza_circuit_map.csv]
```

Both coordinate systems are plain 2-D Cartesian, so aligning them is a single affine transform:

```python
# src/jetracer_bridge.py — already implemented
x_world = self.track_origin_x + (x_raw * cosθ - y_raw * sinθ) * self.scale_factor
y_world = self.track_origin_y + (x_raw * sinθ + y_raw * cosθ) * self.scale_factor
```

You only have to fill in three numbers: `scale_factor`, `rotation_deg`, and `track_origin_x/y`.

### Step 1 — Lay a miniature Monza on the floor (1–2 hours)

1. Open `monza_circuit_map.csv` and look at the X/Y bounding box of the Monza outline. Suppose it is roughly `Δx ≈ 580` and `Δy ≈ 290` (in FastF1 units — you'll see the actual values when you load the CSV).
2. Decide how big you want the physical track to be (e.g. 5 m × 2.5 m fits on a hallway floor). Scale all the Monza waypoints down by the same factor and print the trajectory.
3. Lay **black gaffer tape on light flooring** following that printed shape — JetRacer's downward-facing camera follows the dark line.
4. Add a parallel branch for the pit lane (using `pit_coodrds.csv` shrunk by the same factor) and mark a **pit box** square at its midpoint.
5. Mark **start/finish** with a coloured tape strip or an AprilTag — anything the robot's vision pipeline can recognise to reset `track_distance` each lap.

You don't need millimetre precision. JetRacer's line follower will track any "Monza-ish" shape because it just chases the centre of the black line in front of the camera.

### Step 2 — Calibrate the scale factor (10 minutes)

1. Place the robot at one corner of your taped track. Read `/odom` and record `(x0, y0)`.
2. Drive the robot to the opposite corner along a known direction. Record `(x1, y1)`.
3. Open `monza_circuit_map.csv` and grab the corresponding two corner coordinates `(X0, Y0)` and `(X1, Y1)`.
4. Compute:

   ```
   scale_factor = (X1 - X0) / (x1 - x0)        # FastF1-units per real metre
   rotation_deg = atan2(Y1-Y0, X1-X0) - atan2(y1-y0, x1-x0)
   track_origin = (X0 - x0*scale, Y0 - y0*scale)
   ```

5. Plug these into the `JetRacerBridge` constructor:

   ```python
   bridge = JetRacerBridge(
       scale_factor   = 116.0,
       rotation_deg   = -32.5,
       track_origin_x = 1240.0,
       track_origin_y = -310.0,
   )
   ```

That's it. From now on the dot on the dashboard tracks the robot in real time.

### Step 3 — Sanity-check on the dashboard

Run `python main.py` (with the `JetRacerBridge` import enabled) and roll the robot by hand around the track. The dot should:

- Stay within the grey Monza outline.
- Follow the same direction of travel as the on-screen lap progresses.
- Land on the pit-lane polyline when you push the robot onto the physical pit-lane tape.

If it's mirrored or rotated, tweak `rotation_deg`. If it drifts after a few laps, that's wheel-odometry drift — see the next section.

### Step 4 — Fixing odometry drift (optional, for long sessions)

Wheel encoders accumulate small errors over time (~10 cm per lap). For a short demo it's fine. For longer runs, either:

- Reset `/odom` to `(0, 0)` whenever the robot crosses the start/finish line marker.
- Or add ceiling-mounted AprilTags + `apriltag_ros` to get an absolute pose every ~1 s.

Both options are stock ROS2 packages — no custom code on the dashboard side.

### Files involved

| File                          | Role                                                                  |
|-------------------------------|-----------------------------------------------------------------------|
| `monza_circuit_map.csv`       | The on-screen Monza outline (already in repo)                          |
| `pit_coodrds.csv`             | The on-screen pit-lane polyline (already in repo)                      |
| `src/jetracer_bridge.py`      | The single place where `scale_factor` / `rotation_deg` get applied     |
| Your physical floor tape      | The thing the JetRacer actually drives on                              |

If you ever swap to a non-Monza track, replace the two CSVs with your own polylines and re-run the calibration. **No other code changes needed.**

---

## Running

```bash
# Install (first time)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Launch the dashboard (mock mode — uses recording.json)
python main.py
```

Press **ESC** to exit. The mock recording is auto-generated on first run if `mock_telemetry/recording.json` is missing.

For race day:

```bash
# On the JetRacer
ros2 launch jetracer_race_brain race.launch.py

# On the laptop running the dashboard (same network)
python main.py            # after switching the import to JetRacerBridge
```

---

## Project layout

```
F1-pitstop-pro/
├── main.py                              entry point
├── pit_coodrds.csv                      pit-lane waypoints (X,Y)
├── monza_circuit_map.csv                Monza track geometry
├── mock_telemetry/
│   ├── generate_recording.py            (dev only) bakes a JSON session
│   └── recording.json                   the recorded telemetry stream
└── src/
    ├── interfaces/race_replay.py        the actual dashboard window
    ├── mock_jetracer_simulator.py       pure replay player (no logic)
    ├── jetracer_bridge.py               rclpy ROS subscriber (race-day source)
    ├── mock_data_generator.py           legacy stand-in (kept for compat)
    └── ui_components.py / ui/…          arcade widgets
```

---

## Credits / notes

- Track geometry comes from FastF1's example-lap export at Monza.
- Pit-lane CSV (`pit_coodrds.csv`) is a manually authored polyline of 28 waypoints around the pit-box.
- The Italian-flag banner, pulsing pit-stop overlays and emoji-heavy sidebars are inspired by F1's TV graphics.
- JetRacer ROS AI Kit references: <https://www.waveshare.com/jetracer-ros-ai-kit.htm>
