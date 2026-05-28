import numpy as np
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt

# 1. 데이터 설정
original_x = [1670.34, 3110.96, 3808.03, 3715.09, 2630.75, 1019.74]
original_y = [2764.07, 1524.83, -24.23, -2471.73, -3633.52, -4191.18]

# 2. 보간법 적용
t = np.arange(len(original_x))
ti = np.linspace(0, len(original_x) - 1, 100)

func_x = interp1d(t, original_x, kind='cubic')
func_y = interp1d(t, original_y, kind='cubic')

smooth_x = func_x(ti)
smooth_y = func_y(ti)

# 3. 좌표 먼저 출력 (plt.show() 이전에 배치)
print("--- Smoothed Coordinates Start ---")
for i, (x, y) in enumerate(zip(smooth_x, smooth_y)):
    print(f"[{i+1}] X: {x:.2f}, Y: {y:.2f}")
print("--- Smoothed Coordinates End ---")

# 4. 시각화
plt.figure(figsize=(8, 10))
plt.plot(original_x, original_y, 'ro', label='Original Points')
plt.plot(smooth_x, smooth_y, 'b-', label='Smooth Path')
plt.legend()
plt.axis('equal')
plt.grid(True)
plt.title("Path Smoothing (Cubic Spline)")
plt.show() # 이 창을 닫아야 프로세스가 완전히 종료됩니다.