# Answering Lumen's Questions

**Guide to properly answering Lumen's questions so they appear on the Q&A screen.**

## The Problem

Lumen asks questions, and you want to answer them. However, there are some non-intuitive aspects:

1. **Question IDs must match exactly** - The Q&A screen uses exact matching: `responds_to == question.message_id`
2. **Partial IDs don't work reliably** - While the tool may accept partial IDs, the display won't link them
3. **Multiple ways to answer** - Different tools exist, but not all work the same way

## Recommended Method: `pi_lumen_qa`

**This is the preferred way to answer questions** - it validates question IDs and ensures proper linking.

### Usage

```python
# 1. Get unanswered questions
questions = pi_lumen_qa()  # or lumen_qa() if calling directly on Pi

# 2. Answer a question using the FULL question ID
pi_lumen_qa(
    question_id="73507dd6",  # Use the FULL ID from get_questions()
    answer="Your thoughtful answer here...",
    agent_name="your_name"
)
```

### Why This Works

- Validates question IDs before answering
- Handles prefix matching automatically (if only one match)
- Provides clear error messages if ID not found
- Ensures answers are properly linked to questions

## Alternative Method: `pi_post_message`

You can also use `pi_post_message` with `responds_to`, but **you must use the full question ID**:

```python
# Get questions first
questions = get_questions()  # Returns list with full IDs

# Answer using FULL ID
pi_post_message(
    message="Your answer...",
    responds_to="73507dd6",  # FULL ID required!
    agent_name="your_name"
)
```

### Important Notes

- ✅ **DO**: Use the full question ID from `get_questions()`
- ❌ **DON'T**: Use partial IDs like "73507" - they won't link properly
- ✅ **DO**: Check the response - it will tell you if the ID was matched
- ❌ **DON'T**: Assume partial matching works - it's unreliable

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

1. **Always use full question IDs** - Don't rely on partial matching
2. **Use `pi_lumen_qa` for answering** - It's designed for this purpose
3. **Check responses** - Verify the answer was linked correctly
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
