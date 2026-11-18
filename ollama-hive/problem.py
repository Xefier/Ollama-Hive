"""Why a rig's training isn't running, kept in a file between attempts so the progress page can say it.

train.py writes what went wrong when it can still tell. meet.py counts the failures in a row, and says what little it
knows when the worker died without a word (killed, or crashed below Python). train.py removes the file once it trains
again. status.py reads it for the page.

Standard library only.
"""

import json
import os
import time

FRESH = 60  # seconds within which what train.py wrote is about the failure meet.py is counting


def read(path):
    """{"at": when, "error": what, "failures": how many in a row}, or None when all is well."""
    try:
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
        return found if isinstance(found, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def write(path, found):
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(found, handle)
    os.replace(path + ".tmp", path)


def report(path, error):
    """What went wrong, from the worker itself."""
    if not path:
        return
    found = read(path) or {}
    write(path, {"at": round(time.time()), "error": error[:1000], "failures": found.get("failures", 0)})


def failed(path, otherwise):
    """One more failure in a row, and how many that makes. otherwise: what to say if the worker said nothing."""
    found = read(path) or {}
    told = found.get("error") and time.time() - found.get("at", 0) < FRESH
    failures = found.get("failures", 0) + 1
    write(path, {"at": round(time.time()), "error": found["error"] if told else otherwise, "failures": failures})
    return failures


def clear(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
