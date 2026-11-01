"""Own one engine process group until its worker's lifetime pipe closes.

The guard keeps a shared inference lock until the engine has been reaped.
A replacement worker takes the exclusive lock before recovering jobs.
"""

import fcntl
import os
import select
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def main():
    control = int(sys.argv[1])
    lock_path = Path(sys.argv[2])
    workspace = Path(sys.argv[3])
    command = sys.argv[4:]
    exclusive = command[0] == "--exclusive"
    if exclusive:
        command = command[1:]
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def parent_gone(wait=0):
        ready, _, _ = select.select([control], [], [], wait)
        return bool(ready) and not os.read(control, 1)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if stopping or parent_gone(0.05):
                    return 1
        if stopping or parent_gone():
            return 1
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            engine = subprocess.Popen(command, start_new_session=True)
        except BaseException:
            shutil.rmtree(workspace, ignore_errors=True)
            os.close(control)
            raise
        try:
            while engine.poll() is None:
                if stopping or parent_gone(0.05):
                    return 1
            return max(0, engine.returncode) if engine.returncode >= 0 else 1
        finally:
            try:
                try:
                    os.killpg(engine.pid, signal.SIGTERM)
                    engine.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
                except ProcessLookupError:
                    pass
                # A finished engine can still have live CLI descendants in its group.
                try:
                    os.killpg(engine.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                engine.wait()
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
                os.close(control)


if __name__ == "__main__":
    raise SystemExit(main())
