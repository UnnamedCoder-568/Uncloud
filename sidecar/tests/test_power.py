from uncloud_engine import config, power


def test_wake_lock_uses_absolute_mac_binary_and_releases(monkeypatch):
    calls = []

    class Process:
        def poll(self):
            return None

        def terminate(self):
            calls.append('terminate')

        def wait(self, timeout=None):
            return 0

    def spawn(args, **_kwargs):
        calls.append(args)
        return Process()

    monkeypatch.setattr(config.settings, '_data', {**config.settings._data, 'keep_awake': True})
    monkeypatch.setattr(power.sys, 'platform', 'darwin')
    monkeypatch.setattr(power.subprocess, 'Popen', spawn)
    power._holders = 0
    power._proc = None
    with power.keep_awake('image edit'):
        assert power.is_held()
        assert calls[0][:3] == ['/usr/bin/caffeinate', '-ims', '-w']
    assert not power.is_held()
    assert calls[-1] == 'terminate'


def test_failed_wake_lock_is_not_reported_as_active(monkeypatch):
    monkeypatch.setattr(config.settings, '_data', {**config.settings._data, 'keep_awake': True})
    monkeypatch.setattr(power, '_begin', lambda: False)
    power._holders = 0
    power._proc = None
    with power.keep_awake('image edit'):
        assert not power.is_held()


def test_session_lock_stays_active_outside_jobs_and_releases(monkeypatch):
    calls = []

    class Process:
        def poll(self):
            return None

        def terminate(self):
            calls.append('terminate')

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(config.settings, '_data', {**config.settings._data, 'keep_awake': True})
    monkeypatch.setattr(power.sys, 'platform', 'darwin')
    monkeypatch.setattr(power.subprocess, 'Popen', lambda *args, **kwargs: Process())
    power._holders = 0
    power._proc = None
    power._session_lock = None
    assert power.set_session_awake(True)
    assert power.set_session_awake(True)
    assert power._holders == 1
    with power.keep_awake('image edit'):
        assert power._holders == 2
    assert power.is_held()
    assert not power.set_session_awake(False)
    assert calls == ['terminate']


def test_switch_off_cancels_jobs_without_releasing_future_session(monkeypatch):
    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(config.settings, '_data', {**config.settings._data, 'keep_awake': True})
    monkeypatch.setattr(power.sys, 'platform', 'darwin')
    monkeypatch.setattr(power.subprocess, 'Popen', lambda *args, **kwargs: Process())
    power.set_session_awake(False)
    old_job = power.keep_awake('old job')
    old_job.__enter__()
    power.set_session_awake(False)
    assert not power.is_held()
    assert power.set_session_awake(True)
    old_job.__exit__()
    assert power.is_held()
    assert power._holders == 1
    power.set_session_awake(False)


def test_windows_assertion_released_on_same_thread(monkeypatch):
    import ctypes
    import threading
    from types import SimpleNamespace

    calls = []

    def execution_state(flags):
        calls.append((threading.get_ident(), flags))
        return 1

    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=SimpleNamespace(
        SetThreadExecutionState=execution_state)), raising=False)
    monkeypatch.setattr(config.settings, '_data', {**config.settings._data, 'keep_awake': True})
    monkeypatch.setattr(power.sys, 'platform', 'win32')
    power.set_session_awake(False)
    assert power.set_session_awake(True)
    assert power.is_held()
    power.set_session_awake(False)
    assert not power.is_held()
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0] != threading.get_ident()
    assert calls[1][1] == power._ES_CONTINUOUS
