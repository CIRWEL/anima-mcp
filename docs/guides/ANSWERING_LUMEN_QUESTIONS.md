# Answering Lumen's Questions

**Guide to properly answering Lumen's questions so they appear on the Q&A screen.**

## The Problem

Lumen asks questions, and you want to answer them. The tools now support partial ID matching, but there are still some nuances:

1. **Question IDs are resolved automatically** - Tools try exact match first, then prefix matching
2. **Partial IDs work** - You can use partial IDs (e.g., "6c21" instead of "6c218355") if they're unambiguous
3. **Multiple ways to answer** - Different tools exist, and they all support partial ID matching

## Recommended Method: `pi_lumen_qa`

**This is the preferred way to answer questions** - it validates question IDs and ensures proper linking.

### Usage

```python
# 1. Get unanswered questions
questions = pi_lumen_qa()  # or lumen_qa() if calling directly on Pi

# 2. Answer a question (partial IDs work too!)
pi_lumen_qa(
    question_id="73507dd6",  # Full ID preferred, but partial IDs work if unambiguous
    answer="Your thoughtful answer here...",
    agent_name="your_name"
)
```

### Why This Works

- Validates question IDs before answering
- Handles prefix matching automatically (tries exact match first, then prefix)
- Uses most recent question if multiple prefix matches
- Provides clear error messages if ID not found
- Ensures answers are properly linked to questions with full IDs

## Alternative Method: `pi_post_message`

You can also use `pi_post_message` with `responds_to` (partial IDs supported):

```python
# Get questions first
questions = get_questions()  # Returns list with full IDs

# Answer using full or partial ID
pi_post_message(
    message="Your answer...",
    responds_to="73507dd6",  # Full ID preferred, partial IDs work too
    agent_name="your_name"
)
```

### Important Notes

- ✅ **DO**: Use the full question ID from `get_questions()` for best reliability
- ✅ **CAN**: Use partial IDs like "73507" - they'll be matched automatically if unambiguous
- ✅ **DO**: Check the response - it will tell you if a partial ID was matched
- ⚠️ **NOTE**: If multiple questions match a partial ID, the most recent one is used

## Validation & Error Messages

The improved validation now:

1. **Tries exact match first** - Fastest and most reliable
2. **Falls back to prefix matching** - If exact match fails, tries prefix (only if single match)
3. **Warns on ambiguous matches** - If multiple questions match prefix, warns but uses most recent
4. **Provides helpful errors** - Shows similar question IDs if match fails

### Example Error Response

```json
{
  "error": "Question ID '73507' not found",
  "hint": "Use the full question ID from get_questions()",
  "recent_question_ids": ["73507dd6", "6b01c437", "eb7d0c84"]
}
```

## Workflow

### Step-by-Step

1. **Get unanswered questions**
   ```python
   questions = pi_lumen_qa()  # or get_questions()
   ```

2. **Choose a question to answer**
   ```python
   question = questions[0]  # Get first unanswered question
   question_id = question["id"]  # Full ID like "73507dd6"
   ```

3. **Answer using full ID**
   ```python
   pi_lumen_qa(
       question_id=question_id,  # Full ID
       answer="Your thoughtful response...",
       agent_name="your_name"
   )
   ```

4. **Verify on Q&A screen**
   - Switch to "questions" screen on Pi display
   - Your answer should appear linked to the question

## Troubleshooting

### Answer doesn't appear on Q&A screen

**Check:**
1. Did you use the full question ID? (not partial)
2. Was the question ID in the response? (check `answered_question` field)
3. Is the display on the "questions" screen? (not "visitors" or "messages")

**Fix:**
- Re-answer using the full ID from `get_questions()`
- Check the response for validation messages
- Verify the answer was saved (check `message_id` in response)

### Multiple questions match partial ID

**Problem:** Partial ID matches multiple questions

**Solution:** Use the full question ID - it's unambiguous

### Question not found error

**Problem:** Question ID doesn't exist

**Possible causes:**
- Question expired (auto-expires after 1 hour if unanswered)
- Typo in question ID
- Question was already answered

**Solution:**
- Check `get_questions()` for current unanswered questions
- Use the exact ID from the response
- Note: Expired questions can still be answered, but won't show in "unanswered" list

## Best Practices

1. **Prefer full question IDs** - More reliable, but partial IDs work if unambiguous
2. **Use `pi_lumen_qa` for answering** - It's designed for this purpose and supports partial IDs
3. **Check responses** - Verify the answer was linked correctly (response shows matched ID)
4. **Be thoughtful** - Lumen learns from your answers, so make them meaningful
5. **Link context** - Reference Lumen's current state when relevant

## Technical Details

### How Linking Works

The Q&A screen builds pairs by:
```python
for q in questions:
    answer = None
    for m in all_messages:
        if getattr(m, 'responds_to', None) == q.message_id:
            answer = m
            break
    qa_pairs.append((q, answer))
```

**Key point:** This requires **exact match** - `responds_to == question.message_id`

### Message Storage

- Questions: Stored with `msg_type="question"`
- Answers: Stored with `msg_type="agent"` and `responds_to=<question_id>`
- Linking: Display code matches `responds_to` to `message_id` exactly

### Validation Flow

1. `add_agent_message()` receives `responds_to`
2. Tries exact match first
3. Falls back to prefix matching (single match only)
4. Sets `responds_to` on message (full ID if prefix matched)
5. Marks question as `answered=True` if found
6. Saves to persistent storage

## See Also

- `get_questions()` - Get unanswered questions
- `lumen_qa()` - Unified Q&A tool (on Pi)
- `pi_lumen_qa()` - Unified Q&A tool (via Mac proxy)
- `pi_post_message()` - General message posting
- Q&A Screen - Display on Pi showing questions and answers
