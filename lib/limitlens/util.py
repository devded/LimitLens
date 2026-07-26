"""Small shared helpers."""

import datetime


def iso_to_epoch(text):
    """ISO-8601 timestamp -> unix seconds, or None."""
    if not text:
        return None
    try:
        moment = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return int(moment.timestamp())


def fmt_reset(seconds_left):
    """Seconds until a limit resets -> compact human string."""
    if seconds_left is None:
        return ''
    seconds_left = int(seconds_left)
    if seconds_left <= 0:
        return 'now'
    days, rest = divmod(seconds_left, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return '%dd %dh' % (days, hours) if hours else '%dd' % days
    if hours:
        return '%dh %dm' % (hours, minutes) if minutes else '%dh' % hours
    return '%dm' % max(minutes, 1)


def severity(percent):
    if percent >= 90:
        return 'critical'
    if percent >= 75:
        return 'warning'
    return 'normal'
