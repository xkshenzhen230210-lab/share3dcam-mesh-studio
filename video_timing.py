"""Shared timeline retiming for preview and exported camera animation."""
import math

from video import validate_keyframes


def _number(value, message):
    try:
        if isinstance(value, bool): raise ValueError
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if not math.isfinite(number): raise ValueError(message)
    return number


def _duration(value):
    message = '时长须大于 0 且不超过 1800 秒 / Duration must be above 0 and at most 1800 seconds'
    seconds = _number(value, message)
    if not 0 < seconds <= 1800: raise ValueError(message)
    return seconds


def _rescale(normalized, seconds):
    base_duration = normalized[-1]['time']
    for key in normalized: key['time'] = (key['time'] / base_duration) * seconds
    normalized[0]['time'] = 0.0
    normalized[-1]['time'] = seconds
    if any(a['time'] >= b['time'] for a, b in zip(normalized, normalized[1:])):
        raise ValueError('时长过短，无法区分关键帧时间 / Duration is too short to distinguish keyframe times')
    return normalized


def rescale_duration(keys, seconds):
    """Return independent validated cameras with proportional times ending at seconds."""
    seconds = _duration(seconds)
    return _rescale(validate_keyframes(keys), seconds)


def playback_keyframes(keys, speed=1):
    """Apply speed to a base timeline; both preview and export consume this result."""
    message = '速度须在 0.25–4 倍之间 / Speed must be between 0.25× and 4×'
    speed = _number(speed, message)
    if not .25 <= speed <= 4: raise ValueError(message)
    normalized = validate_keyframes(keys)
    return _rescale(normalized, _duration(normalized[-1]['time'] / speed))
