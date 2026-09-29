# -*- coding: utf-8 -*-
"""The allowlist of gestures the conversation model may ask Pepper to perform."""

GESTURES = {
    "bow": ("animations/Stand/Gestures/BowShort_1", "a short polite bow"),
    "calm": ("animations/Stand/Gestures/CalmDown_1", "a calming motion"),
    "confused": ("animations/Stand/Emotions/Neutral/Confused_1", "a confused motion"),
    "enthusiastic": ("animations/Stand/Gestures/Enthusiastic_4", "an enthusiastic emphasis"),
    "explain": ("animations/Stand/Gestures/Explain_1", "a gentle explanatory gesture"),
    "give": ("animations/Stand/Gestures/Give_3", "a presenting or offering motion"),
    "hello": ("animations/Stand/Gestures/Hey_1", "a friendly greeting"),
    "me": ("animations/Stand/Gestures/Me_1", "a self-reference gesture"),
    "no": ("animations/Stand/Gestures/No_1", "a clear negative gesture"),
    "roar": ("animations/Stand/Waiting/Monster_1", "a playful monster or dinosaur roar"),
    "shrug": ("animations/Stand/Gestures/IDontKnow_1", "an uncertain shrug"),
    "thinking": ("animations/Stand/Gestures/Thinking_1", "a thoughtful motion"),
    "yes": ("animations/Stand/Gestures/Yes_1", "a clear affirmative gesture"),
    "you": ("animations/Stand/Gestures/You_1", "a gentle listener-reference gesture"),
}


def animation_for(gesture):
    """Animation path for an allowlisted gesture name, or None."""
    entry = GESTURES.get(gesture)
    return entry[0] if entry else None
