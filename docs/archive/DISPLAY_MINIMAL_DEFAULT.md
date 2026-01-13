# Minimal Default Display

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Problem

The display was showing a grey screen when:
- The server first starts (before state is available)
- The display is cleared
- No active state is available

This grey screen was distracting and didn't indicate the system was working.

## Solution

Replaced grey screen with a **minimal, non-distracting default**:
- **Subtle dark border** around the edge (2px, dark blue-grey)
- **Black background** (not grey)
- **No text or graphics** - just enough to confirm display is working
- **Automatically shown** when:
  - Display initializes
  - Display is cleared
  - No state available yet

## Changes Made

### 1. Updated Default Screen (`renderer.py`)

Changed `_show_waking_face()` from showing "waking..." text to showing a minimal border:

```python
def _show_waking_face(self):
    """Show minimal default screen - subtle border, non-distracting."""
    # Draws a thin dark border around the edge
    # Just enough to show it's not grey, but not distracting
```

### 2. Added `show_default()` Method

Added abstract method to `DisplayRenderer` interface:
- `PilRenderer.show_default()` - Shows minimal border
- `NoopRenderer.show_default()` - No-op for systems without display

### 3. Updated `clear()` Method

Now shows default instead of blank screen:
```python
def clear(self) -> None:
    """Clear the display - shows minimal default instead of grey."""
    self._show_waking_face()
```

### 4. Updated Display Loop (`server.py`)

Shows default when no state is available:
```python
if _store and _sensors:
    # Show face with current state
    _display.render_face(face_state, name=identity.name)
else:
    # No state yet - show minimal default (not grey)
    _display.show_default()
```

## Visual Design

- **Border color:** `(25, 35, 45)` - Dark blue-grey, minimal but visible
- **Border width:** 2px
- **Background:** Pure black `(0, 0, 0)`
- **No text, no graphics** - Just a subtle border

## Benefits

✅ **Non-distracting** - Minimal visual presence  
✅ **Confirms display works** - Shows it's not grey/blank  
✅ **Takes minimal space** - Just a thin border  
✅ **Always visible** - Shown whenever there's no active state  
✅ **Automatic** - No manual intervention needed

## Testing

The default screen will appear:
1. When the Pi boots and display initializes
2. When the server starts (before first state update)
3. When `clear()` is called
4. When display loop has no state available

---

**The display now always shows something minimal instead of grey!**
