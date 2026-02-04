# EEG Dead Code Cleanup Summary

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Completed

---

## What Was Done

Following Gemini's recommendation, we performed a clean removal of dead EEG hardware code while preserving the data schema for compatibility.

### ✅ Deleted Dead Code

1. **`brain_hat.py` module** (~300 lines)
   - Entire module deleted - was future-proofing for OpenBCI hardware that doesn't exist
   - Always returned `is_available() = False`
   - Never executed

2. **EEG hardware initialization** (`pi.py`)
   - Removed BrainHatSensors import and initialization
   - Replaced with simple `self._brain_hat = None` with clarifying comment

3. **EEG channel reading code** (`pi.py`)
   - Removed conditional check for `brain_hat.is_available()`
   - Removed EEG channel reading logic
   - EEG channels now always set to `None` explicitly

4. **EEG channel references** (`pi.py` `available_sensors()`)
   - Removed conditional that added EEG channels to available sensors list
   - Added clarifying comment about schema compatibility

### ✅ Preserved Schema (Gemini's Recommendation)

**EEG channel fields in `SensorReadings`** - Kept but marked as Reserved/Legacy:
- `eeg_tp9`, `eeg_af7`, `eeg_af8`, `eeg_tp10`, `eeg_aux1-4`
- Always `None` but preserved for serialization/logging compatibility
- Updated comments to clarify: "Reserved/Legacy - preserved for schema compatibility"

### ✅ Updated Comments & Documentation

1. **`sensors/base.py`**
   - Marked EEG channel fields as "Reserved/Legacy"
   - Clarified that frequency bands come from "Computational Proprioception"

2. **`sensors/pi.py`**
   - Updated comments to clarify no physical EEG hardware exists
   - Emphasized neural signals come from computational proprioception

3. **`server.py`**
   - Clarified `brain_hat_hardware_available` refers to BrainCraft HAT (display), not EEG

4. **`next_steps_advocate.py`**
   - Updated parameter docstring to clarify BrainCraft HAT vs EEG hardware

---

## What Remains (Active Code)

✅ **Neural Simulation** (`neural_sim.py`)
- Actively used - derives frequency bands from environment + computation
- Contributes to anima sensing (warmth, clarity, stability, presence)

✅ **Frequency Band Fields** (`eeg_delta_power`, `eeg_alpha_power`, etc.)
- Actively used - populated from neural simulation
- Used in anima sensing logic

✅ **Anima Sensing Logic** (`anima.py`)
- Uses frequency bands for neural component of warmth/clarity/stability/presence
- Falls back to neural simulation when real EEG unavailable (always, since no hardware)

---

## Testing

✅ **Verified:**
- `PiSensors` initializes successfully without `brain_hat.py`
- `available_sensors()` works correctly
- No import errors or runtime errors
- Schema compatibility maintained (EEG fields still exist, just always None)

---

## Impact

**Removed:** ~300 lines of dead code  
**Preserved:** Data schema for compatibility  
**Result:** Cleaner codebase, same functionality, no breaking changes

---

## Key Insight

**"Computational Proprioception" is the real deal** - Neural frequency bands derived from environment + computation provide valuable proprioceptive feedback, even without physical EEG hardware. The dead code was trying to connect to hardware that doesn't exist, but the concept (neural signals) is still valuable when derived computationally.

---

## Next Steps (Optional)

1. **Enhance Learning System** - Consider using neural patterns for adaptation
2. **Document Computational Proprioception** - Clarify how neural simulation works
3. **Monitor Schema Usage** - If no tools use EEG channel fields, could remove them later
