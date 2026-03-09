"""
Display Screens - Messages screen mixin.

Renders messages, questions, visitors screens and handles scroll/expand interactions.
"""

import sys
import time
from typing import Optional, Dict, Any

from .design import COLORS


class MessagesMixin:
    """Mixin for message-group screens (messages, questions, visitors) and interaction methods."""

    def _render_messages(self):
        """Render message board - Lumen's voice and observations. Interactive scrolling and expansion."""
        try:
            from ..messages import get_recent_messages, MESSAGE_TYPE_USER, MESSAGE_TYPE_OBSERVATION, MESSAGE_TYPE_AGENT, MESSAGE_TYPE_QUESTION

            # Get messages for cache check and rendering
            all_messages = get_recent_messages(50)
            scroll_idx = self._state.message_scroll_index
            expanded_id = self._state.message_expanded_id

            # Check image cache - text rendering is expensive (~500ms)
            cache_hash = self._get_messages_cache_hash(all_messages, scroll_idx, expanded_id)
            if self._messages_cache_image is not None and self._messages_cache_hash == cache_hash:
                # Cache hit - use cached image directly (saves ~500ms)
                if hasattr(self._display, '_image'):
                    self._display._image = self._messages_cache_image.copy()
                if hasattr(self._display, '_show'):
                    self._display._show()
                return

            # Cache miss - log why (for debugging slow renders)
            if self._messages_cache_image is None:
                print("[Messages] Cache miss: no cached image", file=sys.stderr, flush=True)
            else:
                print(f"[Messages] Cache miss: hash changed", file=sys.stderr, flush=True)

            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))
            else:
                # Text fallback
                messages = get_recent_messages(6)
                lines = ["MESSAGES", ""]
                for msg in messages:
                    if msg.msg_type == MESSAGE_TYPE_OBSERVATION:
                        prefix = "\u25b8 "
                        text = msg.text
                    elif msg.msg_type == MESSAGE_TYPE_AGENT:
                        prefix = "\u25c6 "
                        author = getattr(msg, 'author', 'agent')
                        text = f"{author}: {msg.text}"
                    else:
                        prefix = "\u25cf "
                        text = f"you: {msg.text}"
                    lines.append(f"{prefix}{text[:20]}")
                self._display.render_text("\n".join(lines), (10, 10))
                return

            # Color definitions - BOLD and HIGH CONTRAST for readability
            CYAN = (0, 255, 255)        # Pure cyan for title
            AMBER = (255, 200, 60)      # Brighter amber for agent messages
            LIME = (100, 255, 100)      # Vivid lime for user messages
            VIOLET = (200, 150, 255)    # Brighter violet for Lumen prefixes
            SOFT_GOLD = (255, 245, 150) # Brighter gold for Lumen's observations
            CORAL = (255, 150, 130)     # Brighter coral for feelings
            PEACH = (255, 220, 180)     # Brighter peach for reflections
            SKY = (140, 220, 255)       # Brighter sky blue for questions
            SAGE = (160, 255, 160)      # Brighter sage green for growth
            MUTED = (160, 180, 200)     # Brighter muted for timestamps
            DARK_BG = (12, 16, 24)      # Deeper background for contrast
            SELECTED_BG = (30, 50, 80)  # Selection highlight
            BORDER = (100, 180, 220)    # Bold border

            # Use cached fonts (loading from disk is slow)
            # Larger fonts for readability - user reported text was hard to read
            fonts = self._get_fonts()
            font = fonts['medium']  # 13px for general text (was 11px)
            font_small = fonts['small']  # 11px for message text (was 9px micro - too small!)
            font_title = fonts['default']  # 14px title (was 12px)

            y_offset = 6

            # Minimal title
            draw.text((10, y_offset), "messages", fill=CYAN, font=font_title)
            y_offset += 18

            # all_messages already fetched at start for cache check
            if not all_messages:
                # Empty state - centered, honest
                draw.text((60, 100), "nothing yet", fill=MUTED, font=font)
                draw.text((70, 118), "be patient", fill=MUTED, font=font_small)
            else:
                # Clamp scroll index (scroll_idx already from cache check)
                scroll_idx = max(0, min(scroll_idx, len(all_messages) - 1))
                self._state.message_scroll_index = scroll_idx

                # Check if any message is expanded
                has_expanded = self._state.message_expanded_id is not None

                # Show fewer messages when one is expanded to make room for more lines
                if has_expanded:
                    # When expanded, show only the selected message (full focus)
                    start_idx = scroll_idx
                    end_idx = scroll_idx + 1
                    visible_messages = all_messages[start_idx:end_idx]
                    selected_in_visible = 0
                else:
                    # Normal view: 5 visible (tighter spacing)
                    start_idx = max(0, scroll_idx - 2)
                    end_idx = min(len(all_messages), start_idx + 5)
                    visible_messages = all_messages[start_idx:end_idx]
                    selected_in_visible = scroll_idx - start_idx

                max_y = 210
                msg_padding = 4
                content_width = 200  # Width for text wrapping

                for i, msg in enumerate(visible_messages):
                    if y_offset > max_y:
                        break

                    is_selected = (i == selected_in_visible)
                    is_expanded = (self._state.message_expanded_id == msg.message_id)
                    answer_msg = None  # For Q&A threading

                    # Style by message type - vibrant colors for visibility
                    if msg.msg_type == MESSAGE_TYPE_USER:
                        prefix = "\u25cf"
                        text_color = LIME        # Bright lime for user
                        prefix_color = LIME
                        display_text = msg.text
                        author_text = "you"
                    elif msg.msg_type == MESSAGE_TYPE_AGENT:
                        prefix = "\u25c6"
                        text_color = AMBER       # Warm amber for agents
                        prefix_color = AMBER
                        author = getattr(msg, 'author', 'agent')
                        # Truncate long author names
                        author_text = author[:12] if len(author) > 12 else author
                        display_text = msg.text
                    elif msg.msg_type == MESSAGE_TYPE_QUESTION:
                        # Lumen's questions - reaching out for understanding
                        prefix = "?"
                        prefix_color = CYAN      # Bright cyan for questions
                        text_color = CYAN        # Questions stand out
                        display_text = msg.text
                        # Show if answered
                        answered = getattr(msg, 'answered', False)
                        author_text = "answered" if answered else "wondering"
                        # Find the answer if it exists (for threading)
                        answer_msg = None
                        if answered:
                            for m in all_messages:
                                if getattr(m, 'responds_to', None) == msg.message_id:
                                    answer_msg = m
                                    break
                    else:  # MESSAGE_TYPE_OBSERVATION (Lumen)
                        prefix = "\u25b8"
                        prefix_color = VIOLET    # Soft violet prefix
                        display_text = msg.text
                        author_text = None  # Lumen's own words, no author needed
                        # Color Lumen's observations by mood/content (using pre-compiled sets)
                        text_words = set(display_text.lower().split())
                        if text_words & self._FEELING_WORDS:
                            text_color = CORAL      # Warm coral for feelings
                        elif text_words & self._CURIOSITY_WORDS:
                            text_color = SKY        # Sky blue for curiosity
                        elif text_words & self._GROWTH_WORDS:
                            text_color = SAGE       # Sage green for growth
                        elif text_words & self._CALM_WORDS:
                            text_color = PEACH      # Soft peach for calm
                        else:
                            text_color = SOFT_GOLD  # Default warm gold

                    # Only wrap text when expanded (optimization: _wrap_text is slow)
                    line_height = 14
                    msg_padding = 4
                    if is_expanded:
                        wrapped_lines = self._wrap_text(display_text, font_small, content_width)
                        # Calculate how many lines can fit on screen
                        # Use y_offset + padding + author line height as starting point
                        start_y = y_offset + msg_padding + (12 if author_text else 0)
                        available_height = max_y - start_y
                        max_visible_lines = max(1, available_height // line_height)
                        # Use text scroll offset for this expanded message
                        text_scroll = self._state.message_text_scroll
                        max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.message_text_scroll = text_scroll
                        num_lines = min(len(wrapped_lines), max_visible_lines)
                    else:
                        wrapped_lines = None  # Don't wrap - just truncate
                        num_lines = 1
                        text_scroll = 0

                    msg_height = (num_lines * line_height) + (msg_padding * 2) + (12 if author_text else 0)

                    # Draw message container
                    if is_selected:
                        draw.rectangle([6, y_offset, 234, y_offset + msg_height],
                                      fill=SELECTED_BG, outline=BORDER, width=1)
                    else:
                        draw.rectangle([6, y_offset, 234, y_offset + msg_height],
                                      fill=DARK_BG)

                    inner_y = y_offset + msg_padding

                    # Author line (timestamp only in expanded view)
                    if author_text:
                        draw.text((12, inner_y), f"{prefix} {author_text}", fill=prefix_color, font=font_small)
                        if is_expanded:
                            age = msg.age_str()
                            draw.text((200, inner_y), age, fill=MUTED, font=font_small)
                        inner_y += 12

                    # Message text
                    if is_expanded and wrapped_lines:
                        # Show multiple wrapped lines with scrolling support
                        available_height = max_y - inner_y
                        max_visible_lines = max(1, available_height // line_height)
                        text_scroll = self._state.message_text_scroll
                        max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.message_text_scroll = text_scroll

                        # Show visible lines starting from scroll offset
                        visible_lines = wrapped_lines[text_scroll:text_scroll + max_visible_lines]
                        for line in visible_lines:
                            if inner_y > max_y:
                                break
                            draw.text((12, inner_y), line, fill=text_color, font=font_small)
                            inner_y += line_height

                        # Show scroll indicators if there's more content
                        if len(wrapped_lines) > max_visible_lines:
                            if text_scroll > 0:
                                draw.text((220, inner_y - max_visible_lines * line_height + 2), "\u25b2", fill=MUTED, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, inner_y - line_height), "\u25bc", fill=MUTED, font=font_small)
                            # Show scroll position indicator
                            scroll_info = f"{text_scroll + 1}-{min(text_scroll + max_visible_lines, len(wrapped_lines))}/{len(wrapped_lines)}"
                            draw.text((140, max_y - 10), scroll_info, fill=MUTED, font=font_small)
                    else:
                        # Single line, truncated directly (no _wrap_text call - faster)
                        first_line = display_text[:34] + "..." if len(display_text) > 34 else display_text
                        # For Lumen's observations, show prefix inline
                        if not author_text:
                            draw.text((12, inner_y), f"{prefix} {first_line}", fill=text_color, font=font_small)
                        else:
                            draw.text((12, inner_y), first_line, fill=text_color, font=font_small)
                        inner_y += line_height

                    y_offset += msg_height + 3  # Gap between messages

                    # Q&A Threading: Show answer inline after question
                    if msg.msg_type == MESSAGE_TYPE_QUESTION and answer_msg is not None:
                        if y_offset < max_y - 30:  # Room for answer
                            # Draw connector line
                            draw.line([(18, y_offset - 2), (18, y_offset + 8)], fill=AMBER, width=1)
                            draw.line([(18, y_offset + 8), (24, y_offset + 8)], fill=AMBER, width=1)

                            # Answer text (indented)
                            ans_author = getattr(answer_msg, 'author', 'agent')[:8]
                            ans_text = answer_msg.text[:35] + "..." if len(answer_msg.text) > 35 else answer_msg.text
                            draw.text((26, y_offset + 2), f"\u21b3 {ans_author}:", fill=AMBER, font=font_small)
                            draw.text((26, y_offset + 14), ans_text, fill=(220, 200, 160), font=font_small)
                            y_offset += 30
                        answer_msg = None  # Reset for next message

                # Scroll indicator - visual bar on right edge
                if len(all_messages) > 5:
                    bar_height = 180
                    bar_top = 30
                    thumb_size = max(20, bar_height // len(all_messages) * 5)
                    thumb_pos = bar_top + int((scroll_idx / max(1, len(all_messages) - 1)) * (bar_height - thumb_size))

                    # Track
                    draw.rectangle([234, bar_top, 238, bar_top + bar_height], fill=DARK_BG)
                    # Thumb
                    draw.rectangle([234, thumb_pos, 238, thumb_pos + thumb_size], fill=MUTED)

                # Bottom status (y=218 to avoid dot overlap)
                draw.text((10, 218), f"{scroll_idx + 1}/{len(all_messages)}", fill=MUTED, font=font_small)
                hint = "\u25bc expand" if not self._state.message_expanded_id else "\u25bc collapse"
                draw.text((100, 218), hint, fill=MUTED, font=font_small)

            # Status bar + screen indicator
            self._draw_status_bar(draw)


            # Cache the rendered image for fast subsequent renders
            self._messages_cache_image = image.copy()
            self._messages_cache_hash = cache_hash

            # Update display
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()

        except Exception as e:
            import traceback
            print(f"[Messages Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            self._display.render_text("MESSAGES\n\nError", (10, 10))

    def _render_questions(self):
        """Render Questions screen - Lumen's questions and answers."""
        # Use the proper Q&A renderer instead of filtered messages
        try:
            self._render_qa_content()
        except Exception as e:
            import traceback
            print(f"[Questions Screen] Error in _render_qa_content: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            # Fallback: show error message
            try:
                self._display.render_text("Q&A\n\nError\nrendering", (10, 10))
            except Exception:
                pass

    def _render_visitors(self):
        """Render Visitors screen - messages from agents and humans."""
        # Note: "user" is the actual msg_type for human messages (not "human")
        self._render_filtered_messages("visitors", ["agent", "user"], include_answers=False)

    def _render_filtered_messages(self, title: str, filter_types: list, include_answers: bool):
        """Render a filtered message screen."""
        try:
            from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT, MESSAGE_TYPE_QUESTION

            # Cache: check message state + scroll before expensive rendering
            board = get_board()
            board._load()
            all_messages = board._messages
            scroll_idx = getattr(self._state, 'message_scroll_index', 0)
            expanded_id = getattr(self._state, 'message_expanded_id', None)
            msg_ids = "|".join(f"{m.message_id}" for m in all_messages[-15:]) if all_messages else ""
            cache_key = f"{title}|{msg_ids}|{scroll_idx}|{expanded_id or ''}"
            if self._check_screen_cache(title, cache_key):
                return

            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))
            else:
                self._display.render_text(f"{title.upper()}\n\nNo display", (10, 10))
                return

            # Colors
            CYAN = (80, 220, 255)
            AMBER = (255, 180, 60)
            GREEN = (100, 220, 140)
            MUTED = (140, 160, 180)
            SOFT_WHITE = (220, 220, 230)

            fonts = self._get_fonts()
            font = fonts['medium']
            font_small = fonts['small']
            font_title = fonts['default']

            # Filter by type - map string types to message type constants
            type_map = {
                "question": MESSAGE_TYPE_QUESTION,
                "agent": MESSAGE_TYPE_AGENT,
                "user": MESSAGE_TYPE_USER
            }
            filter_type_constants = [type_map.get(t, t) for t in filter_types]

            # Filter by type
            # If include_answers, also include agent messages with responds_to (those are answers to questions)
            if include_answers:
                filtered = [m for m in all_messages
                           if m.msg_type in filter_type_constants
                           or (m.msg_type == MESSAGE_TYPE_AGENT and getattr(m, 'responds_to', None))]
            else:
                filtered = [m for m in all_messages if m.msg_type in filter_type_constants]
            filtered = list(reversed(filtered))  # Newest first

            y_offset = 6

            # Title with count
            draw.text((10, y_offset), f"{title} ({len(filtered)})", fill=CYAN, font=font_title)
            y_offset += 22

            # Determine mode for later use
            from .screens import ScreenMode
            mode = ScreenMode.QUESTIONS if "question" in filter_types else ScreenMode.VISITORS

            if not filtered:
                draw.text((60, 100), f"no {title} yet", fill=MUTED, font=font)
            else:
                # Show messages with scroll support
                # Use message_scroll_index for visitors screen too
                scroll_idx = getattr(self._state, 'message_scroll_index', 0)
                scroll_idx = max(0, min(scroll_idx, len(filtered) - 1))
                self._state.message_scroll_index = scroll_idx

                # Check if any message is expanded
                expanded_id = getattr(self._state, 'message_expanded_id', None)
                has_expanded = expanded_id is not None

                # Calculate visible window - selected message should always be visible
                if has_expanded:
                    # When expanded, only show the expanded message
                    visible_count = 1
                    start_idx = scroll_idx
                else:
                    # Normal view: show 4 messages with selected in view
                    visible_count = 4
                    # Keep selected message visible by centering it when possible
                    start_idx = max(0, min(scroll_idx, len(filtered) - visible_count))

                for i, msg in enumerate(filtered[start_idx:start_idx + visible_count]):
                    # Message at scroll_idx is selected
                    is_selected = (start_idx + i == scroll_idx)
                    is_expanded = (expanded_id == msg.message_id)

                    # Type indicator color
                    if msg.msg_type == MESSAGE_TYPE_QUESTION:
                        type_color = CYAN
                    elif msg.msg_type == MESSAGE_TYPE_AGENT and getattr(msg, 'responds_to', None):
                        # Agent message that answers a question
                        type_color = AMBER
                    elif msg.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]:
                        type_color = GREEN
                    else:
                        type_color = MUTED

                    # Author/type
                    author = getattr(msg, 'author', msg.msg_type)

                    if is_expanded:
                        # EXPANDED VIEW for selected message - show full text with scrolling
                        max_y = 210
                        content_width = 200
                        wrapped_lines = self._wrap_text(msg.text, font_small, content_width)

                        # Calculate how many lines can fit
                        available_height = max_y - y_offset - 20  # Leave room for author/timestamp
                        max_visible_lines = max(1, available_height // 12)

                        # Use text scroll offset
                        text_scroll = getattr(self._state, 'message_text_scroll', 0)
                        max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.message_text_scroll = text_scroll

                        # Calculate box height
                        visible_lines = min(len(wrapped_lines), max_visible_lines)
                        box_height = 18 + visible_lines * 12 + 8

                        # Background
                        draw.rectangle([5, y_offset - 2, 235, y_offset + box_height], fill=(35, 55, 85))

                        # Author + timestamp (expanded view has room)
                        draw.text((10, y_offset), f"{author}:", fill=type_color, font=font_small)
                        if hasattr(msg, 'timestamp'):
                            from datetime import datetime
                            if isinstance(msg.timestamp, (int, float)):
                                ts = datetime.fromtimestamp(msg.timestamp).strftime("%H:%M")
                            else:
                                ts = str(msg.timestamp)[11:16]
                            draw.text((180, y_offset), ts, fill=MUTED, font=font_small)

                        y_offset += 14

                        # Show visible lines with scroll
                        visible_lines_list = wrapped_lines[text_scroll:text_scroll + max_visible_lines]
                        for line in visible_lines_list:
                            if y_offset > max_y - 10:
                                break
                            draw.text((10, y_offset), line, fill=SOFT_WHITE, font=font_small)
                            y_offset += 12

                        # Show scroll indicators if there's more content
                        if len(wrapped_lines) > max_visible_lines:
                            if text_scroll > 0:
                                draw.text((220, y_offset - max_visible_lines * 12 + 2), "\u25b2", fill=MUTED, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, y_offset - 12), "\u25bc", fill=MUTED, font=font_small)
                            # Show scroll position
                            scroll_info = f"{text_scroll + 1}-{min(text_scroll + max_visible_lines, len(wrapped_lines))}/{len(wrapped_lines)}"
                            draw.text((140, max_y - 10), scroll_info, fill=MUTED, font=font_small)

                        y_offset += 8
                    elif is_selected:
                        # SELECTED but not expanded - show preview with highlight
                        # Selection background
                        draw.rectangle([5, y_offset - 2, 235, y_offset + 32], fill=(30, 50, 80), outline=(80, 140, 200), width=1)

                        draw.text((10, y_offset), f"{author}:", fill=type_color, font=font_small)
                        y_offset += 14

                        # Truncated text preview
                        text = msg.text[:50] + "..." if len(msg.text) > 50 else msg.text
                        draw.text((10, y_offset), text, fill=(220, 220, 230), font=font_small)
                        y_offset += 22
                    else:
                        # COMPACT VIEW for non-selected messages
                        draw.text((10, y_offset), f"{author}:", fill=type_color, font=font_small)
                        y_offset += 12

                        # Truncated text
                        text = msg.text[:50] + "..." if len(msg.text) > 50 else msg.text
                        draw.text((10, y_offset), text, fill=MUTED, font=font_small)
                        y_offset += 18

                # Scroll indicator
                if len(filtered) > visible_count:
                    draw.text((200, 220), f"{scroll_idx + 1}/{len(filtered)}", fill=MUTED, font=font_small)

                # Expansion hint - show appropriate action
                expanded_id = getattr(self._state, 'message_expanded_id', None)
                hint = "\u25bc expand" if not expanded_id else "\u25bc collapse"
                draw.text((100, 220), hint, fill=MUTED, font=font_small)

            # Status bar + screen indicator
            self._draw_status_bar(draw)


            # Always update display - ensure image is set and shown
            self._store_screen_cache(title, cache_key, image)
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()
            elif hasattr(self._display, 'render_image'):
                self._display.render_image(image)
            else:
                print(f"[ScreenRenderer] Display has no _show or render_image method for {title}", file=sys.stderr, flush=True)

        except Exception as e:
            import traceback
            print(f"[ScreenRenderer] Error rendering {title}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            try:
                self._display.render_text(f"{title.upper()}\n\nError", (10, 10))
            except Exception as e2:
                print(f"[ScreenRenderer] Even error fallback failed for {title}: {e2}", file=sys.stderr, flush=True)
                try:
                    self._display.show_default()
                except Exception:
                    pass

    def _render_qa_content(self):
        """Render Q&A screen - Lumen's questions and agent answers with full threading."""
        try:
            from ..messages import get_board, MESSAGE_TYPE_QUESTION, MESSAGE_TYPE_AGENT

            # Cache: check question state + scroll before expensive text wrapping
            board = get_board()
            board._load()
            all_messages = board._messages
            msg_ids = "|".join(f"{m.message_id}" for m in all_messages[-15:]) if all_messages else ""
            qa_cache_key = f"qa|{msg_ids}|{self._state.qa_scroll_index}|{self._state.qa_expanded}|{self._state.qa_full_view}|{self._state.qa_focus}|{self._state.qa_text_scroll}"
            if self._check_screen_cache("qa", qa_cache_key):
                return

            if not hasattr(self._display, '_create_canvas'):
                self._display.render_text("Q&A\n\nNo display", (10, 10))
                return

            image, draw = self._display._create_canvas((0, 0, 0))
            if image is None or draw is None:
                print("[QA Screen] Failed to create canvas", file=sys.stderr, flush=True)
                self._display.render_text("Q&A\n\nCanvas error", (10, 10))
                return

            # Colors
            CYAN = (80, 220, 255)       # Questions
            AMBER = (255, 180, 60)      # Answers
            MUTED = (140, 160, 180)     # Meta text
            DARK_BG = (15, 20, 30)
            SELECTED_BG = (35, 55, 85)
            FOCUSED_BG = (50, 75, 110)  # Brighter when focused
            FOCUSED_BORDER = (120, 180, 255)  # Bright cyan border when focused
            BORDER = (80, 140, 180)
            SOFT_WHITE = (220, 220, 230)

            fonts = self._get_fonts()
            font = fonts['medium']
            font_small = fonts['small']
            font_title = fonts['default']

            # Build Q&A pairs
            questions = [m for m in all_messages if m.msg_type == MESSAGE_TYPE_QUESTION]
            qa_pairs = []
            for q in questions:
                # Find answer
                answer = None
                for m in all_messages:
                    if getattr(m, 'responds_to', None) == q.message_id:
                        answer = m
                        break
                qa_pairs.append((q, answer))

            # Reverse to show newest first
            qa_pairs = list(reversed(qa_pairs))

            y_offset = 6

            # Title with count - separate waiting (active) from expired
            # q.answered=True means expired, a is None means no actual response
            waiting = sum(1 for q, a in qa_pairs if a is None and not q.answered)
            expired = sum(1 for q, a in qa_pairs if a is None and q.answered)
            if waiting and expired:
                title = f"questions ({waiting} waiting, {expired} expired)"
            elif waiting:
                title = f"questions ({waiting} waiting)"
            elif expired:
                title = f"questions ({expired} expired)"
            else:
                title = "questions"
            draw.text((10, y_offset), title, fill=CYAN, font=font_title)
            y_offset += 20

            if not qa_pairs:
                draw.text((60, 100), "no questions yet", fill=MUTED, font=font)
                draw.text((50, 118), "lumen is still learning", fill=MUTED, font=font_small)
            else:
                # Clamp scroll index
                scroll_idx = max(0, min(self._state.qa_scroll_index, len(qa_pairs) - 1))
                self._state.qa_scroll_index = scroll_idx

                is_expanded = self._state.qa_expanded
                is_full_view = self._state.qa_full_view
                max_y = 205

                if is_full_view:
                    # FULL VIEW: Answer takes entire screen for maximum readability
                    q, answer = qa_pairs[scroll_idx]
                    text_scroll = self._state.qa_text_scroll

                    if answer:
                        # Compact question header (2 lines max)
                        draw.rectangle([6, y_offset, 234, y_offset + 20], fill=DARK_BG, outline=BORDER)
                        draw.text((12, y_offset + 4), "Q:", fill=CYAN, font=font_small)
                        q_preview = q.text[:50] + "..." if len(q.text) > 50 else q.text
                        draw.text((26, y_offset + 4), q_preview, fill=MUTED, font=font_small)
                        y_offset += 22

                        # Full-screen answer area with better highlighting
                        a_lines = self._wrap_text(answer.text, font_small, 220)
                        a_max_lines = 15  # Increased to show more lines
                        max_scroll = max(0, len(a_lines) - a_max_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.qa_text_scroll = text_scroll

                        # Answer header with brighter background
                        author = getattr(answer, 'author', 'agent')
                        draw.rectangle([6, y_offset, 234, y_offset + 185], fill=FOCUSED_BG, outline=FOCUSED_BORDER, width=2)
                        draw.text((12, y_offset + 4), f"\u21b3 {author} responds:", fill=AMBER, font=font_small)
                        draw.text((160, y_offset + 4), f"{len(a_lines)} lines", fill=MUTED, font=font_small)

                        # Show answer lines with scroll
                        a_y = y_offset + 20
                        for line in a_lines[text_scroll:text_scroll + a_max_lines]:
                            if a_y > y_offset + 180:
                                break
                            draw.text((12, a_y), line, fill=SOFT_WHITE, font=font_small)
                            a_y += 12

                        # Scroll indicators - more visible
                        if len(a_lines) > a_max_lines:
                            if text_scroll > 0:
                                draw.text((220, y_offset + 20), "\u25b2", fill=AMBER, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, y_offset + 180), "\u25bc", fill=AMBER, font=font_small)
                            # Progress indicator
                            progress = f"{text_scroll + 1}-{min(text_scroll + a_max_lines, len(a_lines))}/{len(a_lines)}"
                            draw.text((140, y_offset + 4), progress, fill=MUTED, font=font_small)
                    else:
                        # No answer - can't use full view
                        draw.rectangle([6, y_offset, 234, y_offset + 100], fill=DARK_BG, outline=BORDER)
                        draw.text((60, y_offset + 40), "no answer yet", fill=MUTED, font=font)
                        draw.text((40, y_offset + 60), "press to go back", fill=MUTED, font=font_small)

                elif is_expanded:
                    # EXPANDED VIEW: Show single Q&A pair with text scrolling
                    q, answer = qa_pairs[scroll_idx]
                    focus = self._state.qa_focus
                    text_scroll = self._state.qa_text_scroll

                    # Wrap text for both Q and A
                    q_lines = self._wrap_text(q.text, font_small, 210)
                    a_lines = self._wrap_text(answer.text, font_small, 210) if answer else []

                    # Calculate scroll limits based on focus
                    if focus == "question":
                        q_max_lines = 5  # Show 5 lines when question focused
                        max_scroll = max(0, len(q_lines) - q_max_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.qa_text_scroll = text_scroll
                    elif answer:
                        # Answer focused - show more lines and allow full scroll
                        a_max_lines = 12  # Increased from 10 to show more
                        max_scroll = max(0, len(a_lines) - a_max_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.qa_text_scroll = text_scroll
                    else:
                        # Answer focused but no answer yet - reset scroll
                        self._state.qa_text_scroll = 0

                    # Question section - taller when focused with better highlighting
                    q_height = 80 if focus == "question" else 45
                    q_bg = FOCUSED_BG if focus == "question" else DARK_BG
                    q_border = FOCUSED_BORDER if focus == "question" else None
                    q_border_width = 2 if focus == "question" else 0
                    draw.rectangle([6, y_offset, 234, y_offset + q_height], fill=q_bg, outline=q_border, width=q_border_width)

                    # Focus indicator
                    if focus == "question":
                        draw.text((8, y_offset + 2), "\u25b6", fill=CYAN, font=font_small)  # Arrow indicator

                    draw.text((12, y_offset + 4), "? lumen asks:", fill=CYAN, font=font_small)
                    if is_expanded:
                        draw.text((180, y_offset + 4), q.age_str(), fill=MUTED, font=font_small)

                    # Show question lines (with scroll when focused)
                    q_start = text_scroll if focus == "question" else 0
                    q_display_lines = q_max_lines if focus == "question" else 2
                    q_y = y_offset + 18
                    for line in q_lines[q_start:q_start + q_display_lines]:
                        if q_y > y_offset + q_height - 5:
                            break
                        draw.text((12, q_y), line, fill=SOFT_WHITE, font=font_small)
                        q_y += 13

                    # Scroll indicator for question
                    if focus == "question" and len(q_lines) > q_max_lines:
                        if text_scroll > 0:
                            draw.text((220, y_offset + 18), "\u25b2", fill=CYAN, font=font_small)
                        if text_scroll < max_scroll:
                            draw.text((220, y_offset + q_height - 16), "\u25bc", fill=CYAN, font=font_small)
                        # Show scroll position
                        scroll_info = f"{text_scroll + 1}-{min(text_scroll + q_max_lines, len(q_lines))}/{len(q_lines)}"
                        draw.text((140, y_offset + q_height - 12), scroll_info, fill=MUTED, font=font_small)

                    y_offset += q_height + 5

                    # Answer section - taller when focused with better highlighting
                    a_height = 155 if focus == "answer" else 60  # Increased height when focused
                    if answer:
                        a_bg = FOCUSED_BG if focus == "answer" else DARK_BG
                        a_border = FOCUSED_BORDER if focus == "answer" else None
                        a_border_width = 2 if focus == "answer" else 0
                        draw.rectangle([6, y_offset, 234, y_offset + a_height], fill=a_bg, outline=a_border, width=a_border_width)

                        # Focus indicator
                        if focus == "answer":
                            draw.text((8, y_offset + 2), "\u25b6", fill=AMBER, font=font_small)  # Arrow indicator

                        author = getattr(answer, 'author', 'agent')
                        draw.text((12, y_offset + 4), f"\u21b3 {author} responds:", fill=AMBER, font=font_small)
                        if is_expanded:
                            draw.text((180, y_offset + 4), answer.age_str(), fill=MUTED, font=font_small)

                        # Show answer lines (with scroll when focused)
                        a_start = text_scroll if focus == "answer" else 0
                        a_display_lines = a_max_lines if focus == "answer" else 3
                        a_y = y_offset + 18
                        for line in a_lines[a_start:a_start + a_display_lines]:
                            if a_y > y_offset + a_height - 5:
                                break
                            draw.text((12, a_y), line, fill=SOFT_WHITE, font=font_small)
                            a_y += 13

                        # Scroll indicator for answer - more visible
                        if focus == "answer" and len(a_lines) > a_max_lines:
                            if text_scroll > 0:
                                draw.text((220, y_offset + 18), "\u25b2", fill=AMBER, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, y_offset + a_height - 16), "\u25bc", fill=AMBER, font=font_small)
                            # Show scroll position
                            scroll_info = f"{text_scroll + 1}-{min(text_scroll + a_max_lines, len(a_lines))}/{len(a_lines)}"
                            draw.text((140, y_offset + a_height - 12), scroll_info, fill=MUTED, font=font_small)
                    else:
                        # No answer yet - show waiting message with proper highlighting
                        a_bg = FOCUSED_BG if focus == "answer" else DARK_BG
                        a_border = FOCUSED_BORDER if focus == "answer" else BORDER
                        a_border_width = 2 if focus == "answer" else 1
                        draw.rectangle([6, y_offset, 234, y_offset + 40], fill=a_bg, outline=a_border, width=a_border_width)
                        if focus == "answer":
                            draw.text((8, y_offset + 2), "\u25b6", fill=AMBER, font=font_small)  # Arrow indicator
                        draw.text((12, y_offset + 12), "waiting for an answer...", fill=MUTED, font=font_small)
                        if focus == "answer":
                            draw.text((12, y_offset + 26), "\u25c0\u25b6 to focus question", fill=MUTED, font=font_small)

                else:
                    # Collapsed list view - show multiple Q&A pairs (5 visible)
                    start_idx = max(0, scroll_idx - 2)
                    end_idx = min(len(qa_pairs), start_idx + 5)
                    visible_pairs = qa_pairs[start_idx:end_idx]

                    for i, (q, answer) in enumerate(visible_pairs):
                        if y_offset > max_y:
                            break

                        is_selected = (start_idx + i == scroll_idx)
                        bg = SELECTED_BG if is_selected else DARK_BG

                        # Q&A pair container - compact
                        pair_height = 36
                        draw.rectangle([6, y_offset, 234, y_offset + pair_height], fill=bg, outline=BORDER if is_selected else None)

                        # Question preview
                        q_text = q.text[:32] + "..." if len(q.text) > 32 else q.text
                        status = "\u2713" if answer else "?"
                        draw.text((12, y_offset + 3), f"{status} {q_text}", fill=CYAN, font=font_small)
                        draw.text((200, y_offset + 3), q.age_str(), fill=MUTED, font=font_small)

                        # Answer preview (if exists)
                        if answer:
                            author = getattr(answer, 'author', 'agent')[:6]
                            a_text = answer.text[:30] + "..." if len(answer.text) > 30 else answer.text
                            draw.text((20, y_offset + 18), f"\u21b3 {author}: {a_text}", fill=AMBER, font=font_small)
                        else:
                            draw.text((20, y_offset + 18), "\u21b3 (waiting...)", fill=MUTED, font=font_small)

                        y_offset += pair_height + 2

                # Scroll indicator
                if len(qa_pairs) > 5:
                    bar_height = 160
                    bar_top = 30
                    thumb_size = max(20, bar_height // len(qa_pairs) * 5)
                    thumb_pos = bar_top + int((scroll_idx / max(1, len(qa_pairs) - 1)) * (bar_height - thumb_size))
                    draw.rectangle([236, bar_top, 238, bar_top + bar_height], fill=DARK_BG)
                    draw.rectangle([236, thumb_pos, 238, thumb_pos + thumb_size], fill=MUTED)

                # Status bar (y=218 to avoid dot overlap)
                draw.text((10, 218), f"{scroll_idx + 1}/{len(qa_pairs)}", fill=MUTED, font=font_small)
                if is_full_view:
                    hint = "\u25b2\u25bc scroll text  press:back"
                elif is_expanded:
                    focus = self._state.qa_focus
                    if focus == "answer":
                        hint = "\u25b2\u25bc scroll  \u25c0\u25b6 Q  press:full"
                    else:
                        hint = "\u25b2\u25bc scroll  \u25c0\u25b6 A  press:expand"
                else:
                    hint = "press:expand  \u25b2\u25bc:select"
                draw.text((80, 218), hint, fill=MUTED, font=font_small)

            # Status bar + screen indicator
            self._draw_status_bar(draw)


            # Always update display - ensure image is set and shown
            self._store_screen_cache("qa", qa_cache_key, image)
            if hasattr(self._display, '_image'):
                self._display._image = image
            else:
                print("[QA Screen] Display has no _image attribute", file=sys.stderr, flush=True)

            if hasattr(self._display, '_show'):
                self._display._show()
            elif hasattr(self._display, 'render_image'):
                self._display.render_image(image)
            else:
                print("[QA Screen] Display has no _show or render_image method", file=sys.stderr, flush=True)

        except Exception as e:
            import traceback
            print(f"[QA Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            try:
                self._display.render_text("Q&A\n\nError", (10, 10))
            except Exception as e2:
                print(f"[QA Screen] Even error fallback failed: {e2}", file=sys.stderr, flush=True)
                try:
                    self._display.show_default()
                except Exception:
                    pass

    def qa_scroll_up(self):
        """Scroll up in Q&A screen - scroll text when expanded/full, change Q&A when collapsed."""
        from .screens import ScreenMode
        if self._state.mode != ScreenMode.QUESTIONS:
            return
        if self._state.qa_full_view or self._state.qa_expanded:
            # Scroll within text
            self._state.qa_text_scroll = max(0, self._state.qa_text_scroll - 1)
            self._state.last_user_action_time = time.time()
        else:
            # Change Q&A pair
            self._state.qa_scroll_index = max(0, self._state.qa_scroll_index - 1)
            self._state.last_user_action_time = time.time()

    def qa_scroll_down(self):
        """Scroll down in Q&A screen - scroll text when expanded/full, change Q&A when collapsed."""
        from .screens import ScreenMode
        if self._state.mode != ScreenMode.QUESTIONS:
            return
        if self._state.qa_full_view or self._state.qa_expanded:
            # Scroll within text (limit will be enforced in render)
            # Don't increment beyond reasonable limit here - render will clamp it
            self._state.qa_text_scroll += 1
            self._state.last_user_action_time = time.time()
        else:
            # Change Q&A pair
            from ..messages import get_board, MESSAGE_TYPE_QUESTION
            board = get_board()
            board._load()
            num_questions = sum(1 for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION)
            self._state.qa_scroll_index = min(num_questions - 1, self._state.qa_scroll_index + 1)
            self._state.last_user_action_time = time.time()

    def qa_toggle_expand(self):
        """Toggle Q&A expansion: collapsed -> expanded -> full_view (when answer focused) -> collapsed."""
        from .screens import ScreenMode
        if self._state.mode != ScreenMode.QUESTIONS:
            return

        if self._state.qa_full_view:
            # Full view -> back to expanded
            self._state.qa_full_view = False
            self._state.qa_text_scroll = 0
        elif self._state.qa_expanded:
            if self._state.qa_focus == "answer":
                # Expanded with answer focused -> full view
                self._state.qa_full_view = True
                self._state.qa_text_scroll = 0
            else:
                # Expanded with question focused -> collapse
                self._state.qa_expanded = False
                self._state.qa_focus = "question"
                self._state.qa_text_scroll = 0
        else:
            # Collapsed -> expanded
            self._state.qa_expanded = True
            self._state.qa_focus = "question"
            self._state.qa_text_scroll = 0

    def qa_focus_next(self):
        """Switch focus between question and answer in expanded view."""
        from .screens import ScreenMode
        if self._state.mode != ScreenMode.QUESTIONS:
            return
        if self._state.qa_full_view:
            # In full view, pressing left/right exits to expanded
            self._state.qa_full_view = False
            self._state.qa_focus = "answer"  # Keep focus on answer when exiting full view
            self._state.qa_text_scroll = 0
            self._state.last_user_action_time = time.time()
            return
        if not self._state.qa_expanded:
            # In collapsed view, LEFT/RIGHT does nothing (use button to expand)
            # This prevents accidentally getting trapped in expanded mode
            return
        # Toggle focus between question and answer
        self._state.qa_focus = "answer" if self._state.qa_focus == "question" else "question"
        self._state.qa_text_scroll = 0  # Reset text scroll when changing focus
        self._state.last_user_action_time = time.time()

    def message_scroll_up(self):
        """Scroll up in message board - scroll text when expanded, change message when collapsed."""
        from .screens import ScreenMode
        if self._state.mode not in (ScreenMode.MESSAGES, ScreenMode.VISITORS):
            return

        try:
            # Get messages based on mode
            if self._state.mode == ScreenMode.MESSAGES:
                from ..messages import get_recent_messages
                messages = get_recent_messages(50)
            else:  # VISITORS
                from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT
                board = get_board()
                board._load()
                all_messages = board._messages
                messages = [m for m in all_messages if m.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]]
                messages = list(reversed(messages))  # Newest first

            if not messages:
                return

            # If a message is expanded, scroll within its text
            if self._state.message_expanded_id is not None:
                if self._state.message_text_scroll > 0:
                    self._state.message_text_scroll -= 1
                    self._state.last_user_action_time = time.time()
                    return

            # Otherwise, change selected message
            current_idx = self._state.message_scroll_index
            if current_idx < 0:
                current_idx = 0
            if current_idx >= len(messages):
                current_idx = len(messages) - 1

            # Scroll up (decrease index)
            new_idx = max(0, current_idx - 1)
            self._state.message_scroll_index = new_idx
            self._state.last_user_action_time = time.time()

            # Clear expansion and text scroll when scrolling (new message selected)
            self._state.message_expanded_id = None
            self._state.message_text_scroll = 0
        except Exception:
            pass

    def message_scroll_down(self):
        """Scroll down in message board - scroll text when expanded, change message when collapsed."""
        from .screens import ScreenMode
        if self._state.mode not in (ScreenMode.MESSAGES, ScreenMode.VISITORS):
            return

        try:
            # Get messages based on mode
            if self._state.mode == ScreenMode.MESSAGES:
                from ..messages import get_recent_messages
                messages = get_recent_messages(50)
            else:  # VISITORS
                from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT
                board = get_board()
                board._load()
                all_messages = board._messages
                messages = [m for m in all_messages if m.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]]
                messages = list(reversed(messages))  # Newest first

            if not messages:
                return

            # If a message is expanded, scroll within its text
            if self._state.message_expanded_id is not None:
                # Calculate max scroll (will be clamped in render, but check here too)
                scroll_idx = self._state.message_scroll_index
                if scroll_idx < len(messages):
                    selected_msg = messages[scroll_idx]
                    display_text = selected_msg.text
                    wrapped_lines = self._wrap_text(display_text, self._get_fonts()['small'], 200)
                    available_height = 210 - 30  # Approximate available space
                    max_visible_lines = max(1, available_height // 14)
                    max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                    if self._state.message_text_scroll < max_scroll:
                        self._state.message_text_scroll += 1
                        self._state.last_user_action_time = time.time()
                        return

            # Otherwise, change selected message
            current_idx = self._state.message_scroll_index
            if current_idx < 0:
                current_idx = 0
            if current_idx >= len(messages):
                current_idx = len(messages) - 1

            # Scroll down (increase index)
            max_idx = len(messages) - 1
            new_idx = min(max_idx, current_idx + 1)
            self._state.message_scroll_index = new_idx
            self._state.last_user_action_time = time.time()

            # Clear expansion and text scroll when scrolling (new message selected)
            self._state.message_expanded_id = None
            self._state.message_text_scroll = 0
        except Exception:
            pass

    def message_toggle_expand(self):
        """Toggle expansion of currently selected message."""
        from .screens import ScreenMode
        if self._state.mode not in (ScreenMode.MESSAGES, ScreenMode.VISITORS):
            return

        try:
            if self._state.mode == ScreenMode.MESSAGES:
                from ..messages import get_recent_messages
                messages = get_recent_messages(50)
            else:  # VISITORS
                from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT
                board = get_board()
                board._load()
                all_messages = board._messages
                # Filter to agent and user messages
                messages = [m for m in all_messages if m.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]]
                messages = list(reversed(messages))  # Newest first

            if not messages:
                return

            scroll_idx = self._state.message_scroll_index
            if scroll_idx < 0 or scroll_idx >= len(messages):
                return

            selected_msg = messages[scroll_idx]

            # Simple toggle: expand or collapse
            if self._state.message_expanded_id == selected_msg.message_id:
                # Collapse
                self._state.message_expanded_id = None
                self._state.message_text_scroll = 0
            else:
                # Expand
                self._state.message_expanded_id = selected_msg.message_id
                self._state.message_text_scroll = 0

            self._state.last_user_action_time = time.time()
        except Exception:
            pass
