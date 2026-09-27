from datetime import UTC, datetime, timedelta

from app.recorder.lifecycle import Action, RecordingState, decide
from app.util import upload_backoff_s

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def d(is_live, rec=None, stream_id="s1", skip=None):
    return decide(
        is_live=is_live,
        stream_id=stream_id,
        skip_stream_id=skip,
        recording=rec,
        now=NOW,
        offline_polls_to_end=2,
        grace_period_s=600,
    )


def rec(status, offline=0, ending_since=None, running=True):
    return RecordingState(status, offline, ending_since, running)


def test_goes_live_starts_recording():
    assert d(True) == Action.START
    assert d(False) == Action.NOTHING


def test_manually_stopped_broadcast_is_not_restarted():
    assert d(True, skip="s1") == Action.NOTHING
    assert d(True, stream_id="s2", skip="s1") == Action.START


def test_recording_while_live():
    assert d(True, rec("recording")) == Action.NOTHING
    assert d(True, rec("recording", running=False)) == Action.RESTART_PIPELINE


def test_one_offline_poll_is_not_enough():
    assert d(False, rec("recording", offline=0)) == Action.COUNT_OFFLINE
    assert d(False, rec("recording", offline=1)) == Action.BEGIN_ENDING


def test_grace_period():
    assert d(True, rec("ending", ending_since=NOW - timedelta(minutes=3))) == Action.RESUME
    assert d(False, rec("ending", ending_since=NOW - timedelta(minutes=3))) == Action.NOTHING
    assert d(False, rec("ending", ending_since=NOW - timedelta(minutes=10))) == Action.FINALIZE


def test_finished_recording_does_not_block_a_new_one():
    assert d(True, rec("finalizing")) == Action.START
    assert d(True, rec("completed")) == Action.START


def test_upload_backoff():
    assert [upload_backoff_s(n) for n in (1, 2, 3)] == [10, 20, 40]
    assert upload_backoff_s(30) == 3600
