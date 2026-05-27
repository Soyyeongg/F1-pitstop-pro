"""
Pit-Stop Racer Pro - Race Replay Window
Monza track with JetRacer car position, dual sidebars, and live telemetry.
"""

import os
import time
import math
import arcade
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from src.f1_data import FPS
from src.ui_components import (
    ControlsPopupComponent,
    SessionInfoComponent,
    build_track_from_example_lap,
    draw_finish_line
)
from src.mock_data_generator import MockDataGenerator
from src.services.stream import TelemetryStreamServer
from src.mock_jetracer_simulator import MockJetRacerSimulator

# Optional scenario loader
try:
    from src.scenario_loader import ScenarioLoader
except ImportError:
    ScenarioLoader = None


SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

# Monza circuit length in meters (real-world reference)
MONZA_LAP_LENGTH_M = 5793.0


class F1RaceReplayWindow(arcade.Window):
    def __init__(self, frames, track_statuses, example_lap, drivers, title,
                 playback_speed=1.0, driver_colors=None, circuit_rotation=0.0,
                 left_ui_margin=320, right_ui_margin=320, total_laps=None, visible_hud=True,
                 session_info=None, session=None, enable_telemetry=False,
                 race_control_messages=None):
        super().__init__(SCREEN_WIDTH, SCREEN_HEIGHT, title, resizable=True)
        self.maximize()

        # Pit lane data
        self.pit_coords_df = None
        try:
            self.pit_coords_df = pd.read_csv('pit_coodrds.csv')
        except Exception:
            pass

        self.telemetry_stream = None

        # Race data
        self.frames = frames
        self.track_statuses = track_statuses
        self.n_frames = len(frames)
        self.driver_colors = driver_colors or {}
        self.frame_index = 0.0
        self.paused = False
        self.total_laps = total_laps

        # Rotation
        self.circuit_rotation = circuit_rotation
        self._rot_rad = float(np.deg2rad(circuit_rotation)) if circuit_rotation else 0.0
        self._cos_rot = float(np.cos(self._rot_rad))
        self._sin_rot = float(np.sin(self._rot_rad))

        self.left_ui_margin = left_ui_margin
        self.right_ui_margin = right_ui_margin

        # Mock data
        self.mock_data = MockDataGenerator()
        self.current_telemetry = self.mock_data.get_telemetry()
        self.last_telemetry_update = time.time()
        
        # Mock JetRacer simulator (replaces F1 position data)
        self.jetracer_sim = MockJetRacerSimulator(monza_lap_length_m=MONZA_LAP_LENGTH_M)
        print("🤖 Mock JetRacer Simulator activated")
        
        # Scenario loader (optional - if scenarios/active.json exists)
        self.scenario = None
        self.scenario_start_time = time.time()
        scenario_path = os.path.join('scenarios', 'active.json')
        if ScenarioLoader is not None and os.path.exists(scenario_path):
            try:
                self.scenario = ScenarioLoader(scenario_path)
                print(f"✓ Scenario mode: '{self.scenario.name}'")
            except Exception as e:
                print(f"⚠ Could not load scenario: {e}")
                self.scenario = None

        # Session info banner
        self.session_info_comp = SessionInfoComponent(visible=visible_hud)
        if session_info:
            self.session_info_comp.set_info(
                event_name=session_info.get('event_name', ''),
                circuit_name=session_info.get('circuit_name', ''),
                country=session_info.get('country', ''),
                year=session_info.get('year'),
                round_num=session_info.get('round'),
                date=session_info.get('date', ''),
                total_laps=total_laps
            )

        # Build track geometry
        (self.plot_x_ref, self.plot_y_ref,
         self.x_inner, self.y_inner,
         self.x_outer, self.y_outer,
         self.x_min, self.x_max,
         self.y_min, self.y_max, self.drs_zones) = build_track_from_example_lap(example_lap)

        # Build dense reference polyline
        ref_points = self._interpolate_points(self.plot_x_ref, self.plot_y_ref, interp_points=4000)
        self._ref_xs = np.array([p[0] for p in ref_points])
        self._ref_ys = np.array([p[1] for p in ref_points])
        self.track_tree = cKDTree(np.column_stack((self._ref_xs, self._ref_ys)))

        # Cumulative distance along track for accurate distance-based positioning
        diffs = np.sqrt(np.diff(self._ref_xs)**2 + np.diff(self._ref_ys)**2)
        self._ref_cumdist_world = np.concatenate(([0.0], np.cumsum(diffs)))
        self._ref_total_world = float(self._ref_cumdist_world[-1])

        self.world_inner_points = self._interpolate_points(self.x_inner, self.y_inner)
        self.world_outer_points = self._interpolate_points(self.x_outer, self.y_outer)
        self.screen_inner_points = []
        self.screen_outer_points = []

        self.world_scale = 1.0
        self.tx = 0
        self.ty = 0

        arcade.set_background_color((8, 8, 12))
        self.update_scaling(self.width, self.height)
        self.race_start_time = 0.0

        # === Event injection state ===
        self.accident_distance = 500  # meters ahead (default 500m)
        self.accident_pending = False
        self.accident_countdown = 0.0
        self.accident_active = False
        self.accident_timer = 0.0
        self.accident_world_pos = None  # (x, y) in world coordinates
        self.accident_anim_phase = 0.0

        # === Race-control / advisory banner state ===
        # The banner shown at the top of the track area for transient messages
        # like "Accident detected" or "Humidity rising → boosting energy".
        self.advisory_message = None        # str or None
        self.advisory_subtitle = None       # str or None
        self.advisory_severity = "info"     # "info" | "warning" | "critical"
        self.advisory_expires_at = 0.0
        self._last_weather_for_advisory = "dry"

        # Clickable button rectangles (left, bottom, right, top, action)
        # Persisted across frames so clicks register reliably even before
        # the next on_draw() rebuilds the list.
        self.click_targets = []
        self._sticky_click_targets = []

    def _interpolate_points(self, xs, ys, interp_points=2000):
        t_old = np.linspace(0, 1, len(xs))
        t_new = np.linspace(0, 1, interp_points)
        return list(zip(np.interp(t_new, t_old, xs), np.interp(t_new, t_old, ys)))

    def update_scaling(self, screen_w, screen_h):
        padding = 0.05
        world_cx = (self.x_min + self.x_max) / 2
        world_cy = (self.y_min + self.y_max) / 2

        def _rotate_about_center(x, y):
            tx = x - world_cx
            ty = y - world_cy
            rx = tx * self._cos_rot - ty * self._sin_rot
            ry = tx * self._sin_rot + ty * self._cos_rot
            return rx + world_cx, ry + world_cy

        rotated_points = [_rotate_about_center(x, y) for x, y in self.world_inner_points]
        rotated_points += [_rotate_about_center(x, y) for x, y in self.world_outer_points]
        xs = [p[0] for p in rotated_points]
        ys = [p[1] for p in rotated_points]
        world_x_min, world_x_max = min(xs), max(xs)
        world_y_min, world_y_max = min(ys), max(ys)
        world_w = max(1.0, world_x_max - world_x_min)
        world_h = max(1.0, world_y_max - world_y_min)

        inner_w = max(1.0, screen_w - self.left_ui_margin - self.right_ui_margin)
        usable_w = inner_w * (1 - 2 * padding)
        usable_h = (screen_h - 80) * (1 - 2 * padding)

        scale_x = usable_w / world_w
        scale_y = usable_h / world_h
        self.world_scale = min(scale_x, scale_y)

        screen_cx = self.left_ui_margin + inner_w / 2
        screen_cy = (screen_h - 80) / 2 + 40
        self.tx = screen_cx - self.world_scale * world_cx
        self.ty = screen_cy - self.world_scale * world_cy

        self.screen_inner_points = [self.world_to_screen(x, y) for x, y in self.world_inner_points]
        self.screen_outer_points = [self.world_to_screen(x, y) for x, y in self.world_outer_points]

    def on_resize(self, width, height):
        super().on_resize(width, height)
        self.update_scaling(width, height)

    def world_to_screen(self, x, y):
        world_cx = (self.x_min + self.x_max) / 2
        world_cy = (self.y_min + self.y_max) / 2
        if self._rot_rad:
            tx = x - world_cx
            ty = y - world_cy
            rx = tx * self._cos_rot - ty * self._sin_rot
            ry = tx * self._sin_rot + ty * self._cos_rot
            x, y = rx + world_cx, ry + world_cy
        sx = self.world_scale * x + self.tx
        sy = self.world_scale * y + self.ty
        return sx, sy

    def get_position_at_distance(self, distance_m):
        """Get world (x, y) at a given distance from start in meters (using Monza scale)."""
        # Convert real-world meters to track-relative ratio (0..1)
        ratio = (distance_m % MONZA_LAP_LENGTH_M) / MONZA_LAP_LENGTH_M
        # Map to internal track length
        target_world_dist = ratio * self._ref_total_world
        # Find closest index
        idx = int(np.searchsorted(self._ref_cumdist_world, target_world_dist))
        idx = min(idx, len(self._ref_xs) - 1)
        return float(self._ref_xs[idx]), float(self._ref_ys[idx])

    def get_car_distance_traveled(self, frame):
        """Get current car's distance traveled in meters (from JetRacer simulator)."""
        # Use the mock JetRacer simulator's distance instead of F1 data
        return self.jetracer_sim.current_distance_m

    def on_draw(self):
        self.clear()
        # Snapshot the previous frame's click targets so mouse presses that
        # arrive between the current draw and the next on_mouse_press still
        # hit something (prevents the "first click is lost" bug).
        if self.click_targets:
            self._sticky_click_targets = list(self.click_targets)
        self.click_targets = []  # Reset clickable areas each frame

        idx = min(int(self.frame_index), self.n_frames - 1)
        frame = self.frames[idx]

        # === Draw track ===
        if self.pit_coords_df is not None:
            pit_pts = [self.world_to_screen(r['X'], r['Y']) for _, r in self.pit_coords_df.iterrows()]
            if len(pit_pts) > 1:
                arcade.draw_line_strip(pit_pts, arcade.color.ORANGE, 4)

        track_color = (140, 140, 150)
        if len(self.screen_inner_points) > 1:
            arcade.draw_line_strip(self.screen_inner_points, track_color, 4)
        if len(self.screen_outer_points) > 1:
            arcade.draw_line_strip(self.screen_outer_points, track_color, 4)

        if self.drs_zones:
            for zone in self.drs_zones:
                start_idx = zone["start"]["index"]
                end_idx = zone["end"]["index"]
                drs_pts = []
                for i in range(start_idx, min(end_idx + 1, len(self.x_outer))):
                    drs_pts.append(self.world_to_screen(self.x_outer.iloc[i], self.y_outer.iloc[i]))
                if len(drs_pts) > 1:
                    arcade.draw_line_strip(drs_pts, (0, 255, 0), 6)

        try:
            draw_finish_line(self)
        except Exception:
            pass

        # Draw car using Mock JetRacer Simulator (NOT F1 data)
        # Sync simulator with current status
        self.jetracer_sim.set_pitting(self.mock_data.status == 'pitting')
        self.jetracer_sim.set_avoiding(self.mock_data.status == 'avoiding')

        # Force a state update so we know which path we're on
        self.jetracer_sim.update()

        # If the simulator is on the PIT LANE, it gives us absolute (x, y).
        # Otherwise we resolve position from track distance against the
        # main-track polyline (this is the only piece of geometry the
        # renderer owns).
        pit_pos = self.jetracer_sim.get_position()
        if pit_pos is not None:
            car_x, car_y = pit_pos
        else:
            car_x, car_y = self.get_position_at_distance(
                self.jetracer_sim.track_distance_m
            )
        sx, sy = self.world_to_screen(car_x, car_y)

        # Color shifts when in pit lane to make it obvious
        if self.jetracer_sim.is_charging:
            color = (255, 200, 0)        # gold while charging
        elif self.jetracer_sim.is_in_pit_lane:
            color = (255, 140, 0)        # orange in pit lane
        else:
            color = (30, 144, 255)       # blue on track
        arcade.draw_circle_filled(sx, sy, 14, (*color, 80))
        arcade.draw_circle_filled(sx, sy, 9, color)
        arcade.draw_circle_outline(sx, sy, 10, arcade.color.WHITE, 2)
        arcade.draw_text("JETRACER", sx + 16, sy + 8, arcade.color.WHITE, 11,
                         anchor_x="left", anchor_y="center", bold=True)

        # Draw accident marker (if any)
        self._draw_accident()

        # Draw pit stop recommendation / status overlay
        self._draw_pit_overlay()

        # Draw the top-of-track advisory banner (race-control style messages)
        self._update_weather_advisory()
        self._draw_advisory_banner()

        # Refresh telemetry from the JetRacer stream every 0.5 s.
        # All these values come straight from the robot (or the recording
        # in mock mode) — we never compute them here.
        if time.time() - self.last_telemetry_update >= 0.5:
            sim = self.jetracer_sim
            sim.update()

            # Map mode → driving status text shown in the UI
            if sim.is_charging:
                status = 'pitting'
            elif sim.is_in_pit_lane:
                status = 'pitting'
            elif getattr(sim, 'weather', 'dry') == 'rain':
                status = 'rain'
            else:
                status = 'racing'

            self.current_telemetry = {
                'speed':     round(sim.get_speed(), 2),
                'fuel':      round(getattr(sim, 'fuel_pct', 100.0), 1),
                'battery':   round(getattr(sim, 'battery_pct', 100.0), 1),
                'tire_wear': round(getattr(sim, 'tire_wear_pct', 0.0), 1),
                'humidity':  round(getattr(sim, 'humidity_pct', 45.0), 0),
                'weather':   getattr(sim, 'weather', 'dry'),
                'strategy':  getattr(sim, 'strategy', 'BALANCED'),
                'status':    status,
            }
            # Keep mock_data.status loosely in sync so the legacy buttons
            # (weather toggle / accident injection) still show the right state.
            self.mock_data.status = status
            self.mock_data.weather = self.current_telemetry['weather']

            self.last_telemetry_update = time.time()
            self.race_start_time += 0.5

        # Update countdown
        if self.accident_pending:
            self.accident_countdown -= 1.0 / 60.0
            if self.accident_countdown <= 0:
                self._trigger_accident_now(frame)

        if self.accident_active:
            self.accident_timer -= 1.0 / 60.0
            self.accident_anim_phase += 0.15
            if self.accident_timer <= 0:
                self.accident_active = False

        # Draw sidebars
        self._draw_left_sidebar(frame)
        self._draw_right_sidebar()

        # Draw fancy session info banner (top center)
        self._draw_top_banner()

    def _draw_top_banner(self):
        """Draw a stylish top banner with race info."""
        # Banner area (between left and right sidebars)
        banner_left = self.left_ui_margin + 20
        banner_right = self.width - self.right_ui_margin - 20
        banner_top = self.height - 10
        banner_h = 110  # Increased height to fit 3 lines comfortably
        banner_bottom = banner_top - banner_h
        cx = (banner_left + banner_right) / 2
        cy = (banner_top + banner_bottom) / 2
        
        # Italian flag stripes (left edge)
        stripe_w = 10
        arcade.draw_rect_filled(arcade.XYWH(banner_left + stripe_w/2, cy, stripe_w, banner_h), (0, 146, 70))
        arcade.draw_rect_filled(arcade.XYWH(banner_left + stripe_w + stripe_w/2, cy, stripe_w, banner_h), (255, 255, 255))
        arcade.draw_rect_filled(arcade.XYWH(banner_left + 2*stripe_w + stripe_w/2, cy, stripe_w, banner_h), (206, 43, 55))
        
        # Main background panel
        panel_left = banner_left + 3 * stripe_w + 6
        panel_right = banner_right - 3 * stripe_w - 6
        arcade.draw_rect_filled(arcade.XYWH((panel_left + panel_right)/2, cy, panel_right - panel_left, banner_h), (15, 15, 22))
        arcade.draw_rect_outline(arcade.XYWH((panel_left + panel_right)/2, cy, panel_right - panel_left, banner_h), (60, 60, 80), 1)
        
        # Italian flag stripes (right edge)
        arcade.draw_rect_filled(arcade.XYWH(banner_right - 2*stripe_w - stripe_w/2, cy, stripe_w, banner_h), (0, 146, 70))
        arcade.draw_rect_filled(arcade.XYWH(banner_right - stripe_w - stripe_w/2, cy, stripe_w, banner_h), (255, 255, 255))
        arcade.draw_rect_filled(arcade.XYWH(banner_right - stripe_w/2, cy, stripe_w, banner_h), (206, 43, 55))
        
        # Decorative red accent line on top
        arcade.draw_line(panel_left, banner_top - 2, panel_right, banner_top - 2, (225, 6, 0), 3)
        # Decorative red accent line on bottom
        arcade.draw_line(panel_left, banner_bottom + 2, panel_right, banner_bottom + 2, (225, 6, 0), 2)
        
        # === TEXT ROWS (with proper spacing) ===
        # Row 1: Main Title (centered, 28pt)
        arcade.draw_text("ITALIAN GRAND PRIX", cx, banner_top - 28, (255, 255, 255), 26, bold=True,
                         anchor_x="center", anchor_y="center")
        
        # Row 2: Circuit name (Italian red, 13pt)
        arcade.draw_text("AUTODROMO NAZIONALE MONZA", cx, banner_top - 60, (225, 6, 0), 13, bold=True,
                         anchor_x="center", anchor_y="center")
        
        # Row 3: Race details (muted, 11pt)
        info_text = f"2026  •  ROUND 16  •  {MONZA_LAP_LENGTH_M:.0f}m PER LAP"
        arcade.draw_text(info_text, cx, banner_top - 88, (170, 170, 190), 11, bold=True,
                         anchor_x="center", anchor_y="center")

    def _draw_card(self, x, y, w, h, bg=(26, 26, 36), border=(60, 60, 80)):
        cx = x + w / 2
        cy = y - h / 2
        arcade.draw_rect_filled(arcade.XYWH(cx, cy, w, h), bg)
        arcade.draw_rect_outline(arcade.XYWH(cx, cy, w, h), border, 1)

    def _draw_progress_bar(self, x, y, w, h, value, color, bg=(40, 40, 50)):
        arcade.draw_rect_filled(arcade.XYWH(x + w/2, y - h/2, w, h), bg)
        fill_w = max(0, min(w, w * (value / 100.0)))
        if fill_w > 0:
            arcade.draw_rect_filled(arcade.XYWH(x + fill_w/2, y - h/2, fill_w, h), color)

    def _draw_speed_gauge(self, cx, cy, r, speed, max_speed=2.5):
        """Draw a circular speed gauge."""
        # Background arc (270 degrees from 225 to -45)
        # Use multiple line segments to draw arc
        start_angle = 225
        end_angle = -45
        total_arc = start_angle - end_angle  # 270 degrees
        
        # Background arc
        bg_pts = []
        for a in range(int(end_angle), int(start_angle) + 1, 3):
            rad = math.radians(a)
            bg_pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
        if len(bg_pts) > 1:
            arcade.draw_line_strip(bg_pts, (50, 50, 60), 8)

        # Speed arc (filled portion)
        ratio = min(1.0, speed / max_speed)
        if ratio > 0.7:
            color = (255, 70, 70)
        elif ratio > 0.4:
            color = (255, 170, 0)
        else:
            color = (0, 220, 110)
        
        fill_end_angle = start_angle - (ratio * total_arc)
        fill_pts = []
        for a in range(int(fill_end_angle), int(start_angle) + 1, 3):
            rad = math.radians(a)
            fill_pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
        if len(fill_pts) > 1:
            arcade.draw_line_strip(fill_pts, color, 8)

        # Tick marks
        for i in range(11):
            tick_angle = start_angle - (i / 10) * total_arc
            rad = math.radians(tick_angle)
            x1 = cx + (r - 4) * math.cos(rad)
            y1 = cy + (r - 4) * math.sin(rad)
            x2 = cx + (r + 4) * math.cos(rad)
            y2 = cy + (r + 4) * math.sin(rad)
            arcade.draw_line(x1, y1, x2, y2, (180, 180, 200), 2 if i % 5 == 0 else 1)

        # Center value
        arcade.draw_text(f"{speed:.2f}", cx, cy + 8, color, 36, bold=True,
                         anchor_x="center", anchor_y="center")
        arcade.draw_text("m/s", cx, cy - 22, (180, 180, 200), 12,
                         anchor_x="center", anchor_y="center")

    def _draw_left_sidebar(self, frame):
        data = self.current_telemetry
        ACCENT = (225, 6, 0); BG = (15, 15, 22); CARD = (26, 26, 36)
        BORDER = (60, 60, 80); WHITE = (255, 255, 255); MUTED = (130, 130, 150)
        GREEN = (0, 220, 110); ORANGE = (255, 170, 0); BLUE = (0, 160, 255); RED = (255, 70, 70)

        sx_left = 10; sx_right = self.left_ui_margin - 10
        sw = sx_right - sx_left
        s_top = self.height - 15; s_bottom = 15

        arcade.draw_rect_filled(arcade.XYWH((sx_left + sx_right) / 2, (s_top + s_bottom) / 2,
                                             sw, s_top - s_bottom), BG)
        arcade.draw_rect_filled(arcade.XYWH(sx_right - 2, (s_top + s_bottom) / 2, 4, s_top - s_bottom), ACCENT)

        cx = sx_left + 16
        cw = sw - 32
        y = s_top - 16

        # Header
        arcade.draw_text("🏎  PIT-STOP RACER", cx, y, ACCENT, 16, bold=True, anchor_y="top")
        arcade.draw_text("PERFORMANCE MONITOR", cx, y - 22, MUTED, 9, bold=True, anchor_y="top")
        blink = int(time.time() * 2) % 2 == 0
        live_c = GREEN if blink else (0, 90, 50)
        arcade.draw_circle_filled(cx + cw - 50, y - 8, 4, live_c)
        arcade.draw_text("LIVE", cx + cw - 40, y - 12, live_c, 11, bold=True, anchor_y="top")
        y -= 50

        # SPEED GAUGE
        gauge_h = 220
        self._draw_card(cx, y, cw, gauge_h, CARD, BORDER)
        arcade.draw_text("SPEED", cx + 12, y - 10, MUTED, 10, bold=True, anchor_y="top")
        gauge_cx = cx + cw / 2
        gauge_cy = y - gauge_h / 2 - 10
        self._draw_speed_gauge(gauge_cx, gauge_cy, 75, data['speed'], 2.5)
        y -= gauge_h + 12

        # STATUS
        card_h = 70
        self._draw_card(cx, y, cw, card_h, CARD, BORDER)
        arcade.draw_text("DRIVING STATUS", cx + 12, y - 10, MUTED, 10, bold=True, anchor_y="top")
        status_map = {
            'racing':   ('🏁  RACING',   GREEN),
            'pitting':  ('🔧  PITTING',  ORANGE),
            'avoiding': ('⚠  AVOIDING', RED),
            'rain':     ('🌧  RAIN MODE', BLUE),
        }
        s_text, s_color = status_map.get(data['status'], ('UNKNOWN', WHITE))
        arcade.draw_text(s_text, cx + 12, y - 32, s_color, 20, bold=True, anchor_y="top")
        y -= card_h + 12

        # STRATEGY
        card_h = 95
        self._draw_card(cx, y, cw, card_h, CARD, BORDER)
        arcade.draw_text("STRATEGY", cx + 12, y - 10, MUTED, 10, bold=True, anchor_y="top")
        strat_colors = {'PERFORMANCE': RED, 'BALANCED': ORANGE, 'SUSTAINABILITY': GREEN, 'RELIABILITY': BLUE}
        sc = strat_colors.get(data['strategy'], WHITE)
        arcade.draw_text(data['strategy'], cx + 12, y - 32, sc, 18, bold=True, anchor_y="top")
        if data['fuel'] < 20 or data['tire_wear'] > 80 or data['battery'] < 20:
            arcade.draw_text("⚠ PIT STOP REQUIRED", cx + 12, y - 60, RED, 11, bold=True, anchor_y="top")
        else:
            arcade.draw_text("✓ Continue racing", cx + 12, y - 60, GREEN, 11, anchor_y="top")
        # Lap/time
        minutes = int(self.race_start_time // 60)
        secs = int(self.race_start_time % 60)
        arcade.draw_text(f"⏱  {minutes:02d}:{secs:02d}", cx + 12, y - 78, MUTED, 11, anchor_y="top")
        y -= card_h + 12

        # Distance traveled
        card_h = 60
        self._draw_card(cx, y, cw, card_h, CARD, BORDER)
        arcade.draw_text("DISTANCE TRAVELED", cx + 12, y - 10, MUTED, 10, bold=True, anchor_y="top")
        dist = self.get_car_distance_traveled(frame)
        arcade.draw_text(f"{dist:.0f} m", cx + 12, y - 32, ORANGE, 20, bold=True, anchor_y="top")
        arcade.draw_text(f"of {MONZA_LAP_LENGTH_M:.0f}m lap", cx + cw - 12, y - 38,
                         MUTED, 10, anchor_x="right", anchor_y="top")

    def _draw_right_sidebar(self):
        data = self.current_telemetry
        ACCENT = (225, 6, 0); BG = (15, 15, 22); CARD = (26, 26, 36)
        BORDER = (60, 60, 80); WHITE = (255, 255, 255); MUTED = (130, 130, 150)
        SECONDARY = (180, 180, 200)
        GREEN = (0, 220, 110); ORANGE = (255, 170, 0); BLUE = (0, 160, 255); RED = (255, 70, 70)

        sx_left = self.width - self.right_ui_margin + 10
        sx_right = self.width - 10
        sw = sx_right - sx_left
        s_top = self.height - 15; s_bottom = 15

        arcade.draw_rect_filled(arcade.XYWH((sx_left + sx_right) / 2, (s_top + s_bottom) / 2,
                                             sw, s_top - s_bottom), BG)
        arcade.draw_rect_filled(arcade.XYWH(sx_left + 2, (s_top + s_bottom) / 2, 4, s_top - s_bottom), ACCENT)

        cx = sx_left + 16
        cw = sw - 32
        y = s_top - 16

        # ============= DATA SECTION HEADER =============
        arcade.draw_text("📊  TELEMETRY DATA", cx, y, ACCENT, 14, bold=True, anchor_y="top")
        arcade.draw_text("Real-time vehicle metrics", cx, y - 20, MUTED, 9, anchor_y="top")
        y -= 40

        # RESOURCES
        card_h = 165
        self._draw_card(cx, y, cw, card_h, CARD, BORDER)
        arcade.draw_text("RESOURCES", cx + 12, y - 10, MUTED, 10, bold=True, anchor_y="top")

        def draw_row(label, value, row_y, primary, inverse=False):
            if inverse:
                color = RED if value > 70 else (ORANGE if value > 40 else GREEN)
            else:
                color = RED if value < 20 else (ORANGE if value < 50 else primary)
            arcade.draw_text(label, cx + 12, row_y, WHITE, 12, bold=True, anchor_y="top")
            arcade.draw_text(f"{value:.0f}%", cx + cw - 12, row_y, color, 13, bold=True,
                             anchor_x="right", anchor_y="top")
            self._draw_progress_bar(cx + 12, row_y - 18, cw - 24, 6, value, color)

        draw_row("⛽  Fuel",     data['fuel'],      y - 30,  ORANGE, inverse=False)
        draw_row("🔋  Battery",  data['battery'],   y - 75,  GREEN,  inverse=False)
        draw_row("🛞  Tire Wear", data['tire_wear'], y - 120, RED,    inverse=True)
        y -= card_h + 12

        # WEATHER & ENVIRONMENT (Display only) - Increased height
        card_h = 110
        weather_bg = (30, 35, 50) if data['weather'] == 'rain' else (40, 35, 25)
        self._draw_card(cx, y, cw, card_h, weather_bg, BORDER)
        arcade.draw_text("WEATHER & ENVIRONMENT", cx + 12, y - 12, MUTED, 10, bold=True, anchor_y="top")
        if data['weather'] == 'rain':
            arcade.draw_text("🌧  RAIN", cx + 12, y - 36, BLUE, 22, bold=True, anchor_y="top")
        else:
            arcade.draw_text("☀  DRY", cx + 12, y - 36, ORANGE, 22, bold=True, anchor_y="top")
        # Humidity display
        humidity = data.get('humidity', 45)
        humidity_color = BLUE if humidity > 70 else (ORANGE if humidity > 50 else GREEN)
        arcade.draw_text("💧  Humidity", cx + 12, y - 72, WHITE, 11, bold=True, anchor_y="top")
        arcade.draw_text(f"{humidity:.0f}%", cx + cw - 12, y - 72, humidity_color, 12, bold=True,
                         anchor_x="right", anchor_y="top")
        self._draw_progress_bar(cx + 12, y - 92, cw - 24, 5, humidity, humidity_color)
        y -= card_h + 30  # Larger gap before EVENT INJECTION section

        # ============= CONTROL SECTION HEADER (offset down) =============
        # Visual divider
        arcade.draw_line(cx, y + 4, cx + cw, y + 4, ACCENT, 2)
        y -= 12
        arcade.draw_text("🎮  EVENT INJECTION", cx, y, ACCENT, 14, bold=True, anchor_y="top")
        arcade.draw_text("Click to trigger scenarios", cx, y - 20, MUTED, 9, anchor_y="top")
        y -= 42

        # WEATHER TOGGLE BUTTON - Increased height for text
        card_h = 80
        weather_btn_bg = (40, 30, 60) if data['weather'] == 'rain' else (60, 45, 25)
        self._draw_card(cx, y, cw, card_h, weather_btn_bg, BORDER)
        arcade.draw_text("WEATHER MODE", cx + 12, y - 12, MUTED, 9, bold=True, anchor_y="top")
        arcade.draw_text("(Click to toggle)", cx + cw - 12, y - 12, MUTED, 9, anchor_x="right", anchor_y="top")
        if data['weather'] == 'rain':
            arcade.draw_text("🌧  RAIN MODE", cx + 12, y - 36, BLUE, 14, bold=True, anchor_y="top")
            arcade.draw_text("Click for DRY", cx + 12, y - 58, SECONDARY, 11, anchor_y="top")
        else:
            arcade.draw_text("☀  DRY MODE", cx + 12, y - 36, ORANGE, 14, bold=True, anchor_y="top")
            arcade.draw_text("Click for RAIN", cx + 12, y - 58, SECONDARY, 11, anchor_y="top")
        # Make whole card clickable
        self.click_targets.append((cx, y - card_h, cx + cw, y, "toggle_weather"))
        y -= card_h + 12

        # ACCIDENT TRIGGER - Increased height
        card_h = 165
        self._draw_card(cx, y, cw, card_h, CARD, BORDER)
        arcade.draw_text("⚠ ACCIDENT INJECTION", cx + 12, y - 12, RED, 11, bold=True, anchor_y="top")
        arcade.draw_text("Distance ahead:", cx + 12, y - 34, SECONDARY, 11, anchor_y="top")
        # Distance value display
        dist_str = f"{self.accident_distance} m"
        arcade.draw_text(dist_str, cx + cw / 2, y - 64, RED, 24, bold=True,
                         anchor_x="center", anchor_y="top")
        # +/- buttons
        btn_y_top = y - 60
        btn_y_bot = y - 92
        # Minus button
        minus_l, minus_r = cx + 12, cx + 52
        arcade.draw_rect_filled(arcade.XYWH((minus_l + minus_r)/2, (btn_y_top + btn_y_bot)/2, 40, 32), (60, 60, 80))
        arcade.draw_rect_outline(arcade.XYWH((minus_l + minus_r)/2, (btn_y_top + btn_y_bot)/2, 40, 32), BORDER, 1)
        arcade.draw_text("−", (minus_l + minus_r)/2, (btn_y_top + btn_y_bot)/2, WHITE, 22,
                         anchor_x="center", anchor_y="center", bold=True)
        self.click_targets.append((minus_l, btn_y_bot, minus_r, btn_y_top, "decrease_distance"))
        # Plus button
        plus_l, plus_r = cx + cw - 52, cx + cw - 12
        arcade.draw_rect_filled(arcade.XYWH((plus_l + plus_r)/2, (btn_y_top + btn_y_bot)/2, 40, 32), (60, 60, 80))
        arcade.draw_rect_outline(arcade.XYWH((plus_l + plus_r)/2, (btn_y_top + btn_y_bot)/2, 40, 32), BORDER, 1)
        arcade.draw_text("+", (plus_l + plus_r)/2, (btn_y_top + btn_y_bot)/2, WHITE, 22,
                         anchor_x="center", anchor_y="center", bold=True)
        self.click_targets.append((plus_l, btn_y_bot, plus_r, btn_y_top, "increase_distance"))
        # Trigger button
        trig_top = y - 100
        trig_bot = y - card_h + 14
        is_pending = self.accident_pending
        btn_color = (120, 30, 30) if is_pending else RED
        arcade.draw_rect_filled(arcade.XYWH(cx + cw/2, (trig_top + trig_bot)/2, cw - 24, trig_top - trig_bot), btn_color)
        btn_label = f"PENDING ({self.accident_countdown:.1f}s)" if is_pending else "🚨 TRIGGER ACCIDENT"
        arcade.draw_text(btn_label, cx + cw/2, (trig_top + trig_bot)/2, WHITE, 13, bold=True,
                         anchor_x="center", anchor_y="center")
        if not is_pending:
            self.click_targets.append((cx + 12, trig_bot, cx + cw - 12, trig_top, "trigger_accident"))
        y -= card_h + 12

        # EXIT HINT - Simple info card
        card_h = 50
        self._draw_card(cx, y, cw, card_h, CARD, BORDER)
        arcade.draw_text("[ESC]  Exit Application", cx + cw / 2, y - 25, SECONDARY, 12,
                         bold=True, anchor_x="center", anchor_y="center")

    def _draw_pit_overlay(self):
        """Draw pit stop recommendation banner and pit-in countdown."""
        data = self.current_telemetry
        is_pitting = data.get('status') == 'pitting'
        
        # Get pit recommendation info from mock_data
        pit_recommended = getattr(self.mock_data, 'pit_recommended', False)
        pit_reason = getattr(self.mock_data, 'pit_reason', '')
        pit_in_progress = getattr(self.mock_data, 'pit_in_progress', False)
        pit_timer = getattr(self.mock_data, 'pit_timer', 0.0)
        
        # Calculate banner position (between top banner and track)
        banner_left = self.left_ui_margin + 20
        banner_right = self.width - self.right_ui_margin - 20
        banner_w = banner_right - banner_left
        cx = (banner_left + banner_right) / 2
        # Position right below the title banner
        banner_y_top = self.height - 130  # Below 110px title banner
        
        # === PIT RECOMMENDED ALERT ===
        if pit_recommended and not pit_in_progress:
            # Pulsing yellow alert
            pulse = 0.5 + 0.5 * math.sin(time.time() * 3)
            alpha = int(180 + pulse * 60)
            
            alert_h = 50
            alert_y = banner_y_top
            alert_cy = alert_y - alert_h / 2
            
            # Background with pulse
            arcade.draw_rect_filled(arcade.XYWH(cx, alert_cy, banner_w, alert_h), (60, 50, 0, alpha))
            arcade.draw_rect_outline(arcade.XYWH(cx, alert_cy, banner_w, alert_h), (255, 200, 0), 2)
            
            # Warning text
            arcade.draw_text(f"⚠  PIT STOP RECOMMENDED NEXT LAP  ⚠", cx, alert_y - 15,
                             (255, 220, 0), 14, bold=True, anchor_x="center", anchor_y="top")
            arcade.draw_text(f"REASON: {pit_reason}", cx, alert_y - 35,
                             (255, 255, 255), 11, bold=True, anchor_x="center", anchor_y="top")
        
        # === PIT IN PROGRESS - COUNTDOWN ===
        if pit_in_progress:
            countdown_h = 90
            countdown_y = banner_y_top
            countdown_cy = countdown_y - countdown_h / 2
            
            # Pulsing green/orange background
            pulse = 0.5 + 0.5 * math.sin(time.time() * 4)
            
            # Background
            arcade.draw_rect_filled(arcade.XYWH(cx, countdown_cy, banner_w, countdown_h), (10, 40, 20, 230))
            arcade.draw_rect_outline(arcade.XYWH(cx, countdown_cy, banner_w, countdown_h), (255, 170, 0), 3)
            
            # Title
            arcade.draw_text("🔧  PIT STOP IN PROGRESS  🔧", cx, countdown_y - 12,
                             (255, 170, 0), 16, bold=True, anchor_x="center", anchor_y="top")
            
            # Big countdown
            time_remaining = max(0.0, pit_timer)
            arcade.draw_text(f"{time_remaining:.1f}s", cx, countdown_y - 35,
                             (0, 255, 100), 28, bold=True, anchor_x="center", anchor_y="top")
            
            # Status messages
            arcade.draw_text("Refueling • Changing tires • Charging battery",
                             cx, countdown_y - 75, (200, 200, 200), 11,
                             anchor_x="center", anchor_y="top")

    def _draw_accident(self):
        """Draw accident marker on the track."""
        if not (self.accident_active or self.accident_pending) or self.accident_world_pos is None:
            return
        sx, sy = self.world_to_screen(*self.accident_world_pos)

        if self.accident_pending:
            pulse = 0.5 + 0.5 * math.sin(time.time() * 6)
            r = 22 + pulse * 8
            arcade.draw_circle_outline(sx, sy, r, (255, 200, 0), 3)
            arcade.draw_circle_filled(sx, sy, 16, (255, 200, 0, 80))
            countdown_text = f"{self.accident_countdown:.1f}s"
            arcade.draw_text(countdown_text, sx, sy, arcade.color.WHITE, 14,
                             anchor_x="center", anchor_y="center", bold=True)
            arcade.draw_text("⚠ INCOMING", sx, sy + 38, (255, 200, 0), 11,
                             anchor_x="center", anchor_y="center", bold=True)
        elif self.accident_active:
            num_rings = 5
            for i in range(num_rings):
                phase = (self.accident_anim_phase + i * 0.5) % 3.0
                r = 12 + phase * 18
                alpha = max(0, int(220 - phase * 70))
                color = (255, 80, 30, alpha)
                arcade.draw_circle_outline(sx, sy, r, color, 3)
            core_r = 14 + 5 * math.sin(self.accident_anim_phase * 2)
            arcade.draw_circle_filled(sx, sy, core_r, (255, 100, 0))
            arcade.draw_circle_filled(sx, sy, core_r * 0.5, (255, 220, 0))
            arcade.draw_text("💥 ACCIDENT", sx, sy + 38, (255, 80, 30), 13,
                             anchor_x="center", anchor_y="center", bold=True)

    def _trigger_accident_now(self, frame):
        self.accident_pending = False
        self.accident_active = True
        self.accident_timer = 6.0
        self.accident_anim_phase = 0.0
        self.mock_data.trigger_accident(distance=self.accident_distance)
        # Race-control advisory shown across the top of the track
        self._set_advisory(
            severity="critical",
            title=f"⚠  COLLISION DETECTED  •  {self.accident_distance} m AHEAD",
            subtitle="Initiating emergency speed reduction to prevent secondary impact",
            duration_s=6.0,
        )
        print(f"💥 ACCIDENT triggered at {self.accident_distance}m ahead!")

    def _detect_track_direction(self):
        """Detect if car moves in the same direction as track index increases.
        Returns +1 if car moves forward (track index increases) or -1 if reversed."""
        # Use a few frames apart to determine the direction
        cur_idx = int(self.frame_index)
        next_idx = min(cur_idx + 30, self.n_frames - 1)  # ~1.2 sec ahead
        if next_idx <= cur_idx:
            return 1
        
        cur_frame = self.frames[cur_idx]
        next_frame = self.frames[next_idx]
        
        cur_pos = cur_frame["drivers"].get('VER')
        next_pos = next_frame["drivers"].get('VER')
        if not cur_pos or not next_pos:
            return 1
        
        # Get track index at current and next position
        _, cur_track_idx = self.track_tree.query([cur_pos["x"], cur_pos["y"]])
        _, next_track_idx = self.track_tree.query([next_pos["x"], next_pos["y"]])
        
        diff = int(next_track_idx) - int(cur_track_idx)
        # Handle wraparound (e.g., crossing start/finish line)
        n = len(self._ref_xs)
        if diff > n / 2:
            diff -= n
        elif diff < -n / 2:
            diff += n
        
        return 1 if diff >= 0 else -1

    def schedule_accident(self):
        """Schedule an accident X meters ahead of car's current position (in direction of travel).

        The accident is *armed* immediately and detonates 3 seconds later, so
        the dashboard has time to show an inbound-impact warning to the user.
        """
        idx = min(int(self.frame_index), self.n_frames - 1)
        frame = self.frames[idx]
        car_dist = self.get_car_distance_traveled(frame)

        # Detect car's direction of travel
        direction = self._detect_track_direction()
        target_dist = car_dist + (self.accident_distance * direction)
        # Wrap around lap
        target_dist = target_dist % MONZA_LAP_LENGTH_M

        self.accident_world_pos = self.get_position_at_distance(target_dist)
        self.accident_pending = True
        self.accident_countdown = 3.0
        # Warning-level advisory while we wait for the 3-second fuse
        self._set_advisory(
            severity="warning",
            title=f"⚠  HAZARD INCOMING  •  IMPACT IN {self.accident_countdown:.0f}s",
            subtitle=f"Predicted collision point {self.accident_distance} m ahead — bracing systems armed",
            duration_s=3.5,
        )
        print(f"⏱ Accident scheduled at {target_dist:.0f}m "
              f"(direction: {'forward' if direction > 0 else 'backward'}) — "
              f"detonates in {self.accident_countdown:.1f}s")

    def on_update(self, delta_time: float):
        if self.paused:
            return
        self.frame_index += delta_time * FPS * 1.0
        if self.frame_index >= self.n_frames:
            self.frame_index = 0.0

    def on_mouse_press(self, x, y, button, modifiers):
        # Try the freshly-drawn targets first; if a click arrives before the
        # very first on_draw has populated them, fall back to the snapshot
        # from the previous frame. This makes the first click reliable.
        targets = self.click_targets or self._sticky_click_targets
        for left, bottom, right, top, action in targets:
            if left <= x <= right and bottom <= y <= top:
                self._handle_click_action(action)
                return

    def _handle_click_action(self, action):
        if action == "toggle_weather":
            current = self.mock_data.weather
            if current == 'rain':
                self.mock_data.rain_active = False
                self.mock_data.weather = 'dry'
                if self.mock_data.status == 'rain':
                    self.mock_data.status = 'racing'
                print("☀ Weather → DRY")
            else:
                self.mock_data.trigger_rain(delay=0)
                self.mock_data.rain_active = True
                self.mock_data.rain_pending = False
                self.mock_data.weather = 'rain'
                self.mock_data.rain_timer = 60
                print("🌧 Weather → RAIN")
        elif action == "decrease_distance":
            self.accident_distance = max(10, self.accident_distance - 50)
        elif action == "increase_distance":
            self.accident_distance = min(int(MONZA_LAP_LENGTH_M), self.accident_distance + 50)
        elif action == "trigger_accident":
            if not self.accident_pending and not self.accident_active:
                self.schedule_accident()

    def on_key_press(self, symbol, modifiers):
        # Only ESC is allowed - JetRacer can't be paused/reset by software
        # The car runs autonomously based on real-time sensor data
        if symbol == arcade.key.ESCAPE:
            arcade.close_window()

    # =====================================================================
    # Race-control advisory banner
    # =====================================================================
    def _set_advisory(self, *, severity: str, title: str, subtitle: str,
                      duration_s: float = 5.0):
        """Show a transient race-control message at the top of the track."""
        self.advisory_severity = severity
        self.advisory_message = title
        self.advisory_subtitle = subtitle
        self.advisory_expires_at = time.time() + float(duration_s)

    def _update_weather_advisory(self):
        """Watch the weather field from the JetRacer stream and surface a
        race-control message whenever it transitions dry ↔ rain.

        This logic is purely *observational* — the dashboard never decides
        the weather. We just react to whatever the robot publishes.
        """
        current_weather = self.current_telemetry.get('weather', 'dry')
        if current_weather != self._last_weather_for_advisory:
            if current_weather == 'rain':
                # Humidity climbed past the threshold on the robot
                self._set_advisory(
                    severity="warning",
                    title="🌧  RAIN MODE ENGAGED  •  HUMIDITY THRESHOLD CROSSED",
                    subtitle="Boosting energy output to maintain target speed under reduced grip",
                    duration_s=6.0,
                )
            else:
                self._set_advisory(
                    severity="info",
                    title="☀  CONDITIONS CLEARED  •  RETURNING TO DRY-WEATHER PROFILE",
                    subtitle="Energy output normalised — performance envelope fully restored",
                    duration_s=4.5,
                )
            self._last_weather_for_advisory = current_weather

    def _draw_advisory_banner(self):
        """Draw the active advisory message across the top of the track area."""
        if not self.advisory_message:
            return
        if time.time() >= self.advisory_expires_at:
            self.advisory_message = None
            self.advisory_subtitle = None
            return

        # Visual style by severity
        if self.advisory_severity == "critical":
            bg, border, accent = (50, 6, 6, 235), (255, 60, 60), (255, 90, 90)
        elif self.advisory_severity == "warning":
            bg, border, accent = (50, 38, 6, 235), (255, 180, 0), (255, 210, 80)
        else:  # "info"
            bg, border, accent = (8, 28, 50, 235), (60, 170, 255), (140, 210, 255)

        # Layout — sits just below the title banner, between the two sidebars
        banner_left = self.left_ui_margin + 20
        banner_right = self.width - self.right_ui_margin - 20
        banner_w = banner_right - banner_left
        cx = (banner_left + banner_right) / 2
        # The title banner is 110 px tall starting at height-10. Place this
        # advisory immediately under it, with a small visual gap.
        top_of_banner = self.height - 130
        banner_h = 78
        banner_cy = top_of_banner - banner_h / 2

        # Pulsing alpha so it grabs the eye
        pulse = 0.5 + 0.5 * math.sin(time.time() * 4.0)
        glow_alpha = int(70 + 50 * pulse)

        # Outer glow rectangle
        arcade.draw_rect_filled(
            arcade.XYWH(cx, banner_cy, banner_w + 12, banner_h + 12),
            (*border, glow_alpha),
        )
        # Solid background
        arcade.draw_rect_filled(arcade.XYWH(cx, banner_cy, banner_w, banner_h), bg)
        arcade.draw_rect_outline(arcade.XYWH(cx, banner_cy, banner_w, banner_h), border, 2)

        # Left accent bar
        arcade.draw_rect_filled(
            arcade.XYWH(banner_left + 4, banner_cy, 6, banner_h - 6),
            accent,
        )

        # Title (ALL CAPS, big, bold)
        arcade.draw_text(
            self.advisory_message,
            cx, top_of_banner - 22,
            arcade.color.WHITE, 16, bold=True,
            anchor_x="center", anchor_y="center",
        )
        # Subtitle (descriptive sentence)
        if self.advisory_subtitle:
            arcade.draw_text(
                self.advisory_subtitle,
                cx, top_of_banner - 50,
                accent, 12,
                anchor_x="center", anchor_y="center",
            )

        # Time-remaining bar across the bottom of the banner
        remaining = max(0.0, self.advisory_expires_at - time.time())
        # Compute total duration from when it was set (best-effort fallback)
        total = max(1.0, remaining)
        ratio = remaining / total
        bar_w = (banner_w - 16) * ratio
        if bar_w > 0:
            arcade.draw_rect_filled(
                arcade.XYWH(banner_left + 8 + bar_w / 2,
                            banner_cy - banner_h / 2 + 4,
                            bar_w, 3),
                accent,
            )

    def close(self):
        if hasattr(self, 'telemetry_stream') and self.telemetry_stream:
            self.telemetry_stream.stop()
        super().close()
