import fcntl
from contextlib import contextmanager

from meetinglog.config import Settings


@contextmanager
def inference_lock(settings: Settings, *, exclusive=False, blocking=True):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (settings.data_dir / "inference.lock").open("a") as lock:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock, operation | (0 if blocking else fcntl.LOCK_NB))
        yield


def worker_running(settings: Settings) -> bool:
    try:
        with (settings.data_dir / "worker.lock").open("r") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
    except FileNotFoundError:
        pass
    return False
