class AnalysisCancelled(Exception):
    """Raised when the user asks an in-progress analysis to stop."""


def report_progress(callback, is_cancelled, completed, total, item):
    """Publish a progress step and stop before starting more work when cancelled."""
    keep_going = True
    if callback is not None:
        keep_going = callback(completed, total, item)
    if keep_going is False or (is_cancelled is not None and is_cancelled()):
        raise AnalysisCancelled()
