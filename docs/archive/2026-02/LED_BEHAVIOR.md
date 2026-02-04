# LED Behavior Guide

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## When LEDs Go Off

### Normal Behavior

LEDs should **never** go completely off during normal operation. The system enforces minimum brightness levels:

- **Minimum brightness**: 0.1 (10%) - enforced in breathing animation
- **Auto-brightness minimum**: 0.15 (15%) - when auto-brightness is enabled
- **Base brightness**: 0.3 (30%) - default minimum

### When LEDs Turn Off (Abnormal)

LEDs can turn off completely in these scenarios:

1. **Hardware Error**:
   - I2C communication failure
   - Hardware disconnect
   - Power issue
   - **Result**: LEDs marked as unavailable (`_dots = None`)

2. **Explicit Clear**:
   - `clear()` method called
   - Usually only during initialization or shutdown
   - **Result**: All LEDs set to `(0, 0, 0)`

3. **Service Restart**:
   - During service restart, LEDs may briefly turn off
   - Should come back on when service starts

4. **Hardware Initialization Failure**:
   - If LED hardware can't be initialized
   - **Result**: LEDs unavailable, no updates sent

---

## LED State Meanings

### Individual LED Colors

- **LED 0 (left)**: Warmth - red/orange when warm, dim when cold
- **LED 1 (center)**: Clarity - bright white when clear, dim when unclear
- **LED 2 (right)**: Stability - green when stable, dim when unstable

### Brightness Levels

- **High brightness**: Good state (warm, clear, stable, present)
- **Low brightness**: Poor state (cold, unclear, unstable, depleted)
- **Pulsing**: Warning signal (low clarity or stability)
- **Pulse effect**: Brief brightness boost on state change

### All LEDs Off

If **all LEDs go off** during normal operation, this indicates:

1. **Hardware problem**: Check I2C connection, power
2. **Service crash**: Check service logs
3. **Initialization failure**: LEDs couldn't be initialized

**Action**: Check logs for LED errors, verify hardware connection.

---

## Debugging LED Issues

### Check LED Status

```python
from anima_mcp.display.leds import get_led_display
leds = get_led_display()
print(f"LEDs available: {leds.is_available()}")
print(f"Base brightness: {leds._base_brightness}")
```

### Check Logs

```bash
journalctl --user -u anima | grep -i "led"
```

Look for:
- `[LEDs] Error setting LEDs` - Hardware error
- `[LEDs] Cleared` - Explicit clear called
- `[LEDs] Hardware library not available` - Missing dependencies

---

## LED Brightness Logic

1. **Base brightness**: Starts at 0.3 (30%)
2. **Auto-brightness**: Adjusts based on ambient light (0.15-0.5 range)
3. **Pulsing**: Multiplies brightness when clarity/stability low
4. **State-change pulse**: Brief brightness boost on significant state change
5. **Breathing**: Subtle animation (0.1-0.5 range)

**Minimum enforced**: 0.1 (10%) - LEDs should never go completely dark during normal operation.

---

## Troubleshooting

### LEDs Off When They Should Be On

1. Check hardware connection
2. Check service status: `systemctl --user status anima`
3. Check logs for errors
4. Verify I2C is enabled: `i2cdetect -y 1`
5. Check if broker is running (may affect LED access)

### LEDs Flickering

- Normal: Breathing animation, pulsing effects
- Abnormal: Hardware issue, I2C communication problems

### LEDs Not Responding to State

- Check if LEDs are being updated: Look for `[LEDs]` log messages
- Verify anima state is being computed correctly
- Check if LED display is initialized
