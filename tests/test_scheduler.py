"""
Tests for server.scheduler() — loop behavior and interval timing.
The infinite loop is broken by raising StopIteration from time.sleep.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


class TestScheduler:
    def test_calls_run_scrape_on_first_iteration(self):
        """run_scrape() is called before the first sleep."""
        run_count = {"n": 0}

        def fake_run():
            run_count["n"] += 1

        def fake_sleep(secs):
            raise StopIteration

        with patch("server.run_scrape", side_effect=fake_run), \
             patch("server.time.sleep", side_effect=fake_sleep):
            try:
                server.scheduler()
            except StopIteration:
                pass

        assert run_count["n"] == 1

    def test_sleeps_for_configured_interval(self):
        """sleep() receives INTERVAL_H * 3600 seconds."""
        sleep_args = []

        def fake_sleep(secs):
            sleep_args.append(secs)
            raise StopIteration

        with patch("server.run_scrape"), \
             patch("server.time.sleep", side_effect=fake_sleep):
            try:
                server.scheduler()
            except StopIteration:
                pass

        assert len(sleep_args) == 1
        assert sleep_args[0] == server.INTERVAL_H * 3600

    def test_loops_multiple_times(self):
        """Each iteration calls run_scrape() then sleeps."""
        run_count = {"n": 0}
        sleep_count = {"n": 0}

        def fake_run():
            run_count["n"] += 1

        def fake_sleep(secs):
            sleep_count["n"] += 1
            if sleep_count["n"] >= 3:
                raise StopIteration

        with patch("server.run_scrape", side_effect=fake_run), \
             patch("server.time.sleep", side_effect=fake_sleep):
            try:
                server.scheduler()
            except StopIteration:
                pass

        assert run_count["n"] == 3
        assert sleep_count["n"] == 3

    def test_run_scrape_called_before_each_sleep(self):
        """Order invariant: run_scrape always precedes time.sleep in each cycle."""
        order = []

        def fake_run():
            order.append("run")

        def fake_sleep(secs):
            order.append("sleep")
            if order.count("sleep") >= 2:
                raise StopIteration

        with patch("server.run_scrape", side_effect=fake_run), \
             patch("server.time.sleep", side_effect=fake_sleep):
            try:
                server.scheduler()
            except StopIteration:
                pass

        # Pattern must be run, sleep, run, sleep, ...
        assert order == ["run", "sleep", "run", "sleep"]
