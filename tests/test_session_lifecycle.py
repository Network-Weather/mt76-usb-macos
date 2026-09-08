# SPDX-License-Identifier: BSD-3-Clause-Clear
from scripts.session_lifecycle import accepted


def test_native_lifecycle_requires_cleanup_and_balanced_accounting():
    summary = {
        "exit_code": 130,
        "register_alive_after": True,
        "state": 2,
        "frames_received": 12,
        "frames_delivered": 10,
        "frames_dropped": 2,
    }
    assert accepted(summary, 130, 130)
    assert not accepted(summary, -15, 130)
    assert not accepted({**summary, "state": 3}, 130, 130)
    assert not accepted({**summary, "frames_received": 13}, 130, 130)
    assert not accepted({**summary, "usb_errors": 1}, 130, 130)
    assert not accepted({**summary, "register_alive_after": False}, 130, 130)


def test_python_lifecycle_shape():
    summary = {
        "exit_code": 0,
        "register_alive_after": True,
        "session": {
            "state": "closed",
            "frame_depth": 0,
            "counts": {"frames_received": 5, "frames_delivered": 5},
        },
    }
    assert accepted(summary, 0, 0)
    assert not accepted({}, 0, 0)
