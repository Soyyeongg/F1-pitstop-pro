import fastf1
import pandas as pd

# 1. 몬자 서킷 데이터 불러오기 (최신 세션 기준)
# 'Italy'가 바로 몬자(Monza) 서킷입니다.
session = fastf1.get_session(2024, 'Italy', 'R')
session.load(telemetry=True)

# 2. 가장 빠른 랩 하나를 기준으로 전체 경로(Shape) 추출
fastest_lap = session.laps.pick_fastest()
telemetry = fastest_lap.get_telemetry()

# 3. 우리가 필요한 건 오직 X, Y 좌표!
# 이 값들이 모여서 몬자 지도의 '선'이 됩니다.
monza_coords = telemetry[['X', 'Y']]

# 4. CSV 파일로 저장 (엑셀에서 열어서 비율 계산하기 좋음)
monza_coords.to_csv('monza_circuit_map.csv', index=False)

# 5. 화면에 전체 크기 출력 (이게 여러분의 트랙 설계 사이즈가 됩니다)
width = monza_coords['X'].max() - monza_coords['X'].min()
height = monza_coords['Y'].max() - monza_coords['Y'].min()

print(f"--- 몬자 서킷 좌표 분석 결과 ---")
print(f"가로(X) 데이터 범위: {width}")
print(f"세로(Y) 데이터 범위: {height}")
print(f"가로 대비 세로 비율: 1 : {height/width:.2f}")
print(f"결과가 'monza_circuit_map.csv'로 저장되었습니다.")