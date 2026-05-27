"""
Pit-Stop Racer Pro - Live Monitoring Dashboard
Shows the Monza circuit with the JetRacer car position and live telemetry.
"""

from src.f1_data import get_race_telemetry, enable_cache, get_circuit_rotation, load_session
from src.run_session import run_arcade_replay, launch_insights_menu
import sys
import logging


def main():
    try:
        # Fixed settings - Italian Grand Prix Race (Monza)
        year = 2024  # 2026 data not available, using 2024
        round_number = 16
        session_type = 'R'
        playback_speed = 1
        visible_hud = True
        ready_file = None
        
        print("=" * 50)
        print("🏎️  PIT-STOP RACER PRO - Live Monitoring")
        print("=" * 50)
        print(f"Loading Monza circuit data...")
        
        session = load_session(year, round_number, session_type)
        print(f"✓ Loaded: {session.event['EventName']}")
        
        enable_cache()
        
        print("Processing telemetry data...")
        race_telemetry = get_race_telemetry(session, session_type=session_type)
        print("✓ Telemetry loaded")
        
        # Get track layout
        fastest_lap = session.laps.pick_fastest()
        example_lap = fastest_lap.get_telemetry()
        
        drivers = session.drivers
        circuit_rotation = get_circuit_rotation(session)
        
        session_info = {
            'event_name': session.event.get('EventName', ''),
            'circuit_name': session.event.get('Location', ''),
            'country': session.event.get('Country', ''),
            'year': year,
            'round': round_number,
            'date': session.event.get('EventDate', '').strftime('%B %d, %Y') if session.event.get('EventDate') else '',
            'total_laps': race_telemetry['total_laps'],
            'circuit_length_m': float(example_lap["Distance"].max()) if example_lap is not None and "Distance" in example_lap else None,
        }
        
        print("Starting monitoring dashboard...")
        
        run_arcade_replay(
            frames=race_telemetry['frames'],
            track_statuses=race_telemetry['track_statuses'],
            example_lap=example_lap,
            drivers=drivers,
            playback_speed=playback_speed,
            driver_colors=race_telemetry['driver_colors'],
            title=f"Pit-Stop Racer Pro - {session.event['EventName']}",
            total_laps=race_telemetry['total_laps'],
            circuit_rotation=circuit_rotation,
            visible_hud=visible_hud,
            ready_file=ready_file,
            session_info=session_info,
            session=session,
            enable_telemetry=True,
            race_control_messages=race_telemetry.get('race_control_messages', [])
        )
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")


if __name__ == "__main__":
    if "--verbose" not in sys.argv:
        logging.getLogger("fastf1").setLevel(logging.CRITICAL)
    
    main()