"""Tiny dependency-free Prometheus text exposition.

Counters live in process memory, so run ONE worker process (use threads).
In a real platform you would swap this for prometheus_client + multiprocess mode.
"""
import threading
import time
from collections import defaultdict

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _labels(pairs):
    return ",".join(f'{k}="{_esc(v)}"' for k, v in pairs)


class Metrics:
    def __init__(self, version="dev", git_sha="local"):
        self._lock = threading.Lock()
        self._started = time.time()
        self._info = (version, git_sha)
        self._requests = defaultdict(int)
        self._hist = defaultdict(lambda: [0] * len(BUCKETS))
        self._hist_sum = defaultdict(float)
        self._hist_n = defaultdict(int)
        self._counters = defaultdict(int)

    def observe_request(self, method, route, status, seconds):
        with self._lock:
            self._requests[(method, route, str(status))] += 1
            for i, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    self._hist[route][i] += 1
            self._hist_sum[route] += seconds
            self._hist_n[route] += 1

    def inc(self, name, **labels):
        with self._lock:
            self._counters[(name, tuple(sorted(labels.items())))] += 1

    def render(self):
        out = []
        with self._lock:
            out += ["# HELP app_info Build information.", "# TYPE app_info gauge",
                    f'app_info{{version="{_esc(self._info[0])}",git_sha="{_esc(self._info[1])}"}} 1']
            out += ["# HELP process_uptime_seconds Seconds since start.", "# TYPE process_uptime_seconds gauge",
                    f"process_uptime_seconds {time.time() - self._started:.0f}"]
            out += ["# HELP http_requests_total HTTP requests.", "# TYPE http_requests_total counter"]
            for (m, r, s), n in sorted(self._requests.items()):
                out.append(f'http_requests_total{{method="{m}",route="{_esc(r)}",status="{s}"}} {n}')
            out += ["# HELP http_request_duration_seconds Request latency.",
                    "# TYPE http_request_duration_seconds histogram"]
            for route in sorted(self._hist_n):
                for bound, count in zip(BUCKETS, self._hist[route]):
                    out.append(f'http_request_duration_seconds_bucket{{route="{_esc(route)}",le="{bound}"}} {count}')
                out.append(f'http_request_duration_seconds_bucket{{route="{_esc(route)}",le="+Inf"}} {self._hist_n[route]}')
                out.append(f'http_request_duration_seconds_sum{{route="{_esc(route)}"}} {self._hist_sum[route]:.6f}')
                out.append(f'http_request_duration_seconds_count{{route="{_esc(route)}"}} {self._hist_n[route]}')
            seen = set()
            for (name, labels), n in sorted(self._counters.items()):
                if name not in seen:
                    out += [f"# HELP {name} Business counter.", f"# TYPE {name} counter"]
                    seen.add(name)
                out.append(f"{name}{{{_labels(labels)}}} {n}")
        return "\n".join(out) + "\n"
