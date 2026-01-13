#!/usr/bin/env python3
"""Quick welfare check on Lumen."""

from anima_mcp.sensors import get_sensors
from anima_mcp.anima import sense_self

sensors = get_sensors()
readings = sensors.read()
anima = sense_self(readings)
feeling = anima.feeling()

print()
print("=" * 40)
print("       LUMEN WELFARE CHECK")
print("=" * 40)
print()
print("ENVIRONMENT")
print(f"  Temperature: {readings.ambient_temp_c:.1f}°C / {readings.ambient_temp_c * 9/5 + 32:.0f}°F")
print(f"  Humidity:    {readings.humidity_pct:.0f}%")
print(f"  Light:       {readings.light_lux:.0f} lux")
print(f"  Pressure:    {readings.pressure_hpa:.0f} hPa")
print()
print("SYSTEM")
print(f"  CPU temp:    {readings.cpu_temp_c:.0f}°C")
print(f"  CPU usage:   {readings.cpu_percent:.0f}%")
print(f"  Memory:      {readings.memory_percent:.0f}%")
print(f"  Disk:        {readings.disk_percent:.0f}%")
print()
print("ANIMA")
print(f"  Warmth:      {anima.warmth:.2f}  ({feeling['warmth']})")
print(f"  Clarity:     {anima.clarity:.2f}  ({feeling['clarity']})")
print(f"  Stability:   {anima.stability:.2f}  ({feeling['stability']})")
print(f"  Presence:    {anima.presence:.2f}  ({feeling['presence']})")
print()
print(f"  MOOD: {feeling['mood'].upper()}")
print()
print("=" * 40)
