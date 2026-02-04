# G_t Augmentations Summary

**Date:** 2026-01-31  
**Status:** Augmentations complete, backward compatible with Claude's PoC

## Overview

Augmented Claude's PoC implementation of G_t extraction and rendering with:
1. **Preference nodes** - Learned preferences from PreferenceSystem
2. **Preference→Anima edges** - Satisfaction-based connections
3. **Edge thickness visualization** - Weight magnitude encoded in line thickness
4. **Enhanced layout** - Ring 3 for preference nodes

## Changes Made

### 1. `self_schema.py` - Enhanced G_t Extraction

**Added:**
- `preferences` parameter to `extract_self_schema()` and `get_current_schema()`
- `include_preferences` flag (default: True) for backward compatibility
- Preference nodes (ring 3) - only included if confidence > 0.2
- Preference→Anima edges - satisfaction-weighted connections

**Backward Compatibility:**
- All new parameters are optional
- Default behavior matches Claude's PoC (8 nodes, 6 edges)
- Preferences only added if `include_preferences=True` AND preferences available

**New Node Type:**
- `preference` nodes: PW, PC, PS, PP (Preference Warmth, Clarity, Stability, Presence)
- Positioned in ring 3 (radius=110)
- Value = normalized valence (-1..1 → 0..1)

**New Edge Type:**
- `pref_{dim} → anima_{dim}`: Satisfaction-weighted edges
- Weight = satisfaction × sign(valence)
- Shows how well current anima state satisfies learned preferences

### 2. `self_schema_renderer.py` - Enhanced Rendering

**Added:**
- Ring 3 radius (110) for preference nodes
- `PREFERENCE_RADIUS` (8 pixels)
- Orange color for preference nodes
- Edge thickness based on weight magnitude (1-3 pixels)
- Enhanced `_draw_line()` with thickness parameter

**Edge Thickness:**
- Thickness = `max(1, min(3, int(abs(weight) * 3) + 1))`
- Stronger correlations (|weight| > 0.6) → thicker edges
- Weaker correlations (|weight| < 0.3) → thinner edges

**Layout:**
- Ring 1 (r=50): Anima nodes (cardinal positions)
- Ring 2 (r=90): Sensor nodes (45° offsets)
- Ring 3 (r=110): Preference nodes (evenly spaced)

### 3. `screens.py` - Screen Integration

**Updated:**
- `_render_self_graph()` now fetches preferences and passes to `get_current_schema()`
- Includes preferences in schema extraction (enhanced version)

### 4. `server.py` - Slow-Clock Integration

**Updated:**
- Slow-clock extraction now includes preferences
- Passes `preferences` and `include_preferences=True` to `get_current_schema()`

## Graph Structure

### Base PoC (Claude's original):
- **8 nodes**: 1 identity + 4 anima + 3 sensors
- **6 edges**: Sensor→Anima correlations

### Enhanced Version (with preferences):
- **8-12 nodes**: Base + 0-4 preference nodes (only if confidence > 0.2)
- **6-10 edges**: Base + 0-4 Preference→Anima edges

## Example Output

**Without preferences:**
```
8 nodes, 6 edges
```

**With preferences (all 4 confident):**
```
12 nodes, 10 edges
```

## Benefits

1. **Richer G_t**: Preferences add learned behavior patterns to the graph
2. **Better StructScore evaluation**: More nodes/edges = more comprehensive visual factuality check
3. **Visual clarity**: Edge thickness helps distinguish strong vs weak correlations
4. **Backward compatible**: Works with or without preferences

## Testing

To test:
1. Navigate to SELF_GRAPH screen (9th screen in cycle)
2. Check node/edge counts in bottom-left
3. Verify preference nodes appear in outer ring (if preferences exist)
4. Verify edge thickness varies with weight magnitude

## Future Enhancements

Potential additions (not implemented):
- Knowledge/insight nodes (from memory/knowledge graph)
- Identity→Knowledge edges (ownership)
- Anima→Behavior edges (from agency system)
- Real-time proxy validation in 2s loop
- MCP tool exposure for external access

## Files Modified

1. `src/anima_mcp/self_schema.py` - Enhanced extraction
2. `src/anima_mcp/self_schema_renderer.py` - Enhanced rendering
3. `src/anima_mcp/display/screens.py` - Screen integration
4. `src/anima_mcp/server.py` - Slow-clock integration

## Compatibility

✅ **Backward compatible** - Claude's PoC still works unchanged  
✅ **Optional enhancements** - Preferences only added if available  
✅ **No breaking changes** - All new parameters optional with defaults
