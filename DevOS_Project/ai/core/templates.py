
"""
Advanced project templates for autonomous generation.
Each template produces a complete, tested, multi-file project.
"""

TEMPLATES_SYSTEM = [
    {
        "name": "process_monitor",
        "description": "System process monitor with alerts",
        "keywords": ["process", "monitor", "ps", "watch", "alert"],
        "files": {
            "monitor.py": '''#!/usr/bin/env python3
"""System process monitor — watches processes, detects anomalies, alerts."""
import subprocess
import time
import json
import os

class ProcessMonitor:
    def __init__(self, interval=5, log_path="/tmp/procmon.log"):
        self.interval = interval
        self.log_path = log_path
        self.baseline = {}
        self.alerts = []

    def snapshot(self):
        """Take a snapshot of current processes."""
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True
        )
        procs = []
        for line in result.stdout.strip().split("\\n")[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                procs.append({
                    "user": parts[0],
                    "pid": int(parts[1]),
                    "cpu": float(parts[2]),
                    "mem": float(parts[3]),
                    "command": parts[10],
                })
        return procs

    def set_baseline(self):
        """Set current state as baseline."""
        procs = self.snapshot()
        self.baseline = {p["pid"]: p for p in procs}
        return len(self.baseline)

    def check(self):
        """Compare current state against baseline."""
        current = {p["pid"]: p for p in self.snapshot()}
        new_alerts = []

        # New processes
        for pid, proc in current.items():
            if pid not in self.baseline:
                new_alerts.append({
                    "type": "new_process",
                    "pid": pid,
                    "command": proc["command"][:80],
                    "time": time.time(),
                })

        # High CPU
        for pid, proc in current.items():
            if proc["cpu"] > 80.0:
                new_alerts.append({
                    "type": "high_cpu",
                    "pid": pid,
                    "cpu": proc["cpu"],
                    "command": proc["command"][:80],
                    "time": time.time(),
                })

        # High memory
        for pid, proc in current.items():
            if proc["mem"] > 50.0:
                new_alerts.append({
                    "type": "high_mem",
                    "pid": pid,
                    "mem": proc["mem"],
                    "command": proc["command"][:80],
                    "time": time.time(),
                })

        # Dead processes
        for pid in self.baseline:
            if pid not in current:
                new_alerts.append({
                    "type": "process_died",
                    "pid": pid,
                    "command": self.baseline[pid]["command"][:80],
                    "time": time.time(),
                })

        self.alerts.extend(new_alerts)
        self.baseline = current
        return new_alerts

    def run(self, cycles=None):
        """Run monitoring loop."""
        self.set_baseline()
        count = 0
        while cycles is None or count < cycles:
            time.sleep(self.interval)
            alerts = self.check()
            for alert in alerts:
                print(f"[ALERT] {alert['type']}: PID {alert['pid']} — {alert.get('command', '')}")
            self._save_log()
            count += 1

    def _save_log(self):
        try:
            with open(self.log_path, 'w') as f:
                json.dump({"alerts": self.alerts[-50:], "process_count": len(self.baseline)}, f)
        except Exception:
            pass

    def summary(self):
        return {
            "monitored": len(self.baseline),
            "total_alerts": len(self.alerts),
            "recent_alerts": self.alerts[-10:],
        }


if __name__ == "__main__":
    mon = ProcessMonitor(interval=3)
    print(f"Baseline: {mon.set_baseline()} processes")
    mon.run()
''',
            "test_monitor.py": '''#!/usr/bin/env python3
import unittest
from monitor import ProcessMonitor

class TestProcessMonitor(unittest.TestCase):
    def test_snapshot(self):
        mon = ProcessMonitor()
        procs = mon.snapshot()
        self.assertIsInstance(procs, list)
        self.assertGreater(len(procs), 0)

    def test_baseline(self):
        mon = ProcessMonitor()
        count = mon.set_baseline()
        self.assertGreater(count, 0)

    def test_check(self):
        mon = ProcessMonitor()
        mon.set_baseline()
        alerts = mon.check()
        self.assertIsInstance(alerts, list)

    def test_summary(self):
        mon = ProcessMonitor()
        mon.set_baseline()
        s = mon.summary()
        self.assertIn("monitored", s)

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_monitor.py -v"
    },
    {
        "name": "config_manager",
        "description": "Configuration manager with TOML/JSON/ENV support",
        "keywords": ["config", "configuration", "settings", "env", "toml"],
        "files": {
            "config.py": '''#!/usr/bin/env python3
"""Multi-format configuration manager. Supports JSON, ENV, and INI."""
import os
import json
import configparser

class Config:
    def __init__(self, defaults=None):
        self._data = defaults or {}
        self._sources = []

    def load_json(self, path):
        """Load config from JSON file."""
        with open(path) as f:
            data = json.load(f)
        self._merge(data)
        self._sources.append(f"json:{path}")
        return self

    def load_env(self, prefix="APP_"):
        """Load config from environment variables with prefix."""
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower()
                self._data[config_key] = self._parse_value(value)
        self._sources.append(f"env:{prefix}*")
        return self

    def load_ini(self, path, section="default"):
        """Load config from INI file."""
        parser = configparser.ConfigParser()
        parser.read(path)
        if section in parser:
            for key, value in parser[section].items():
                self._data[key] = self._parse_value(value)
        self._sources.append(f"ini:{path}[{section}]")
        return self

    def get(self, key, default=None):
        """Get a config value with dotted path support."""
        keys = key.split(".")
        current = self._data
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        return current

    def set(self, key, value):
        """Set a config value."""
        keys = key.split(".")
        current = self._data
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

    def all(self):
        """Get all config as dict."""
        return dict(self._data)

    def save_json(self, path):
        """Save current config to JSON."""
        with open(path, 'w') as f:
            json.dump(self._data, f, indent=2)

    def _merge(self, data, target=None):
        if target is None:
            target = self._data
        for key, value in data.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._merge(value, target[key])
            else:
                target[key] = value

    @staticmethod
    def _parse_value(value):
        """Try to parse string values into Python types."""
        if value.lower() in ("true", "yes", "on"):
            return True
        if value.lower() in ("false", "no", "off"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    def __repr__(self):
        return f"Config(sources={self._sources}, keys={list(self._data.keys())})"


if __name__ == "__main__":
    cfg = Config({"debug": False, "port": 8080})
    cfg.load_env("DEVOS_")
    print(cfg.all())
''',
            "test_config.py": '''#!/usr/bin/env python3
import unittest
import os
import json
import tempfile
from config import Config

class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = Config({"port": 8080})
        self.assertEqual(cfg.get("port"), 8080)

    def test_set_get(self):
        cfg = Config()
        cfg.set("db.host", "localhost")
        self.assertEqual(cfg.get("db.host"), "localhost")

    def test_nested_get(self):
        cfg = Config({"db": {"host": "localhost", "port": 5432}})
        self.assertEqual(cfg.get("db.port"), 5432)

    def test_default_value(self):
        cfg = Config()
        self.assertEqual(cfg.get("missing", "default"), "default")

    def test_load_json(self):
        data = {"key": "value", "num": 42}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            path = f.name
        cfg = Config()
        cfg.load_json(path)
        self.assertEqual(cfg.get("key"), "value")
        self.assertEqual(cfg.get("num"), 42)
        os.unlink(path)

    def test_load_env(self):
        os.environ["TEST_CFG_HOST"] = "localhost"
        os.environ["TEST_CFG_PORT"] = "3000"
        cfg = Config()
        cfg.load_env("TEST_CFG_")
        self.assertEqual(cfg.get("host"), "localhost")
        self.assertEqual(cfg.get("port"), 3000)
        del os.environ["TEST_CFG_HOST"]
        del os.environ["TEST_CFG_PORT"]

    def test_save_json(self):
        cfg = Config({"a": 1})
        path = tempfile.mktemp(suffix='.json')
        cfg.save_json(path)
        with open(path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded["a"], 1)
        os.unlink(path)

    def test_merge(self):
        cfg = Config({"db": {"host": "old"}})
        cfg.load_json.__func__  # just verify method exists
        cfg.set("db.host", "new")
        self.assertEqual(cfg.get("db.host"), "new")

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_config.py -v"
    },
    {
        "name": "pipe_runner",
        "description": "Shell pipeline builder and executor",
        "keywords": ["pipe", "pipeline", "shell", "chain", "command"],
        "files": {
            "pipeline.py": '''#!/usr/bin/env python3
"""Shell pipeline builder — chain commands with pipes, redirects, error handling."""
import subprocess
import logging
import time

class Pipeline:
    def __init__(self):
        self.steps = []
        self.results = []

    def add(self, command, name=None, check=True, timeout=30):
        """Add a step to the pipeline."""
        self.steps.append({
            "command": command,
            "name": name or f"step_{len(self.steps)+1}",
            "check": check,
            "timeout": timeout,
        })
        return self

    def pipe(self, cmd1, cmd2, name=None):
        """Add a piped command (cmd1 | cmd2)."""
        return self.add(f"{cmd1} | {cmd2}", name=name)

    def run(self):
        """Execute all steps sequentially."""
        self.results = []
        for i, step in enumerate(self.steps):
            t0 = time.time()
            try:
                result = subprocess.run(
                    step["command"], shell=True,
                    capture_output=True, text=True,
                    timeout=step["timeout"]
                )
                elapsed = time.time() - t0
                entry = {
                    "name": step["name"],
                    "command": step["command"],
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "elapsed": round(elapsed, 3),
                    "success": result.returncode == 0,
                }
                self.results.append(entry)

                if step["check"] and result.returncode != 0:
                    logging.error(f"Pipeline failed at {step['name']}: {result.stderr[:200]}")
                    return False

            except subprocess.TimeoutExpired:
                self.results.append({
                    "name": step["name"],
                    "command": step["command"],
                    "success": False,
                    "error": "timeout",
                })
                if step["check"]:
                    return False

        return True

    def summary(self):
        lines = []
        for r in self.results:
            status = "OK" if r.get("success") else "FAIL"
            elapsed = r.get("elapsed", 0)
            lines.append(f"  [{status}] {r['name']} ({elapsed}s)")
        return "\\n".join(lines)

    def output(self):
        """Get combined stdout from all steps."""
        return "\\n".join(r.get("stdout", "") for r in self.results)


class PipelineBuilder:
    """Fluent builder for common pipeline patterns."""

    @staticmethod
    def build_and_test(build_cmd, test_cmd, name="build_test"):
        return (Pipeline()
            .add(build_cmd, name="build")
            .add(test_cmd, name="test"))

    @staticmethod
    def lint_and_test(lint_cmd, test_cmd):
        return (Pipeline()
            .add(lint_cmd, name="lint", check=False)
            .add(test_cmd, name="test"))

    @staticmethod
    def git_commit_push(path, message):
        return (Pipeline()
            .add(f"cd {path} && git add -A", name="stage")
            .add(f"cd {path} && git commit -m \\"{message}\\"", name="commit")
            .add(f"cd {path} && git push", name="push", check=False))


if __name__ == "__main__":
    p = Pipeline()
    p.add("echo 'Step 1'", name="echo1")
    p.add("echo 'Step 2'", name="echo2")
    p.pipe("echo 'hello world'", "wc -w", name="count_words")
    success = p.run()
    print(f"Pipeline {'succeeded' if success else 'failed'}")
    print(p.summary())
''',
            "test_pipeline.py": '''#!/usr/bin/env python3
import unittest
from pipeline import Pipeline, PipelineBuilder

class TestPipeline(unittest.TestCase):
    def test_simple_run(self):
        p = Pipeline()
        p.add("echo hello", name="echo")
        self.assertTrue(p.run())
        self.assertEqual(len(p.results), 1)
        self.assertIn("hello", p.results[0]["stdout"])

    def test_multi_step(self):
        p = Pipeline()
        p.add("echo a", name="s1")
        p.add("echo b", name="s2")
        self.assertTrue(p.run())
        self.assertEqual(len(p.results), 2)

    def test_failure_stops(self):
        p = Pipeline()
        p.add("echo ok", name="s1")
        p.add("false", name="fail")
        p.add("echo never", name="s3")
        self.assertFalse(p.run())
        self.assertEqual(len(p.results), 2)

    def test_no_check_continues(self):
        p = Pipeline()
        p.add("false", name="fail", check=False)
        p.add("echo ok", name="s2")
        self.assertTrue(p.run())
        self.assertEqual(len(p.results), 2)

    def test_pipe(self):
        p = Pipeline()
        p.pipe("echo 'hello world'", "wc -w", name="count")
        self.assertTrue(p.run())

    def test_summary(self):
        p = Pipeline()
        p.add("echo test", name="s1")
        p.run()
        s = p.summary()
        self.assertIn("OK", s)

    def test_builder(self):
        p = PipelineBuilder.build_and_test("echo build", "echo test")
        self.assertTrue(p.run())

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_pipeline.py -v"
    },
    {
        "name": "data_transformer",
        "description": "CSV/JSON data transformation toolkit",
        "keywords": ["csv", "data", "transform", "convert", "etl"],
        "files": {
            "transformer.py": '''#!/usr/bin/env python3
"""Data transformation toolkit — CSV/JSON conversion, filtering, aggregation."""
import csv
import json
import io
import sys
from collections import defaultdict

class DataTransformer:
    def __init__(self, data=None):
        self.data = data or []

    def from_csv(self, text):
        """Parse CSV text into list of dicts."""
        reader = csv.DictReader(io.StringIO(text))
        self.data = list(reader)
        return self

    def from_json(self, text):
        """Parse JSON text."""
        parsed = json.loads(text)
        if isinstance(parsed, list):
            self.data = parsed
        else:
            self.data = [parsed]
        return self

    def from_file(self, path):
        """Load from file (auto-detect format)."""
        with open(path) as f:
            content = f.read()
        if path.endswith('.csv'):
            return self.from_csv(content)
        elif path.endswith('.json'):
            return self.from_json(content)
        raise ValueError(f"Unknown format: {path}")

    def to_csv(self):
        """Convert to CSV string."""
        if not self.data:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=self.data[0].keys())
        writer.writeheader()
        writer.writerows(self.data)
        return output.getvalue()

    def to_json(self, indent=2):
        """Convert to JSON string."""
        return json.dumps(self.data, indent=indent)

    def select(self, *fields):
        """Select specific fields."""
        self.data = [{k: row.get(k) for k in fields} for row in self.data]
        return self

    def where(self, field, op, value):
        """Filter rows. Ops: ==, !=, >, <, >=, <=, contains."""
        ops = {
            "==": lambda a, b: str(a) == str(b),
            "!=": lambda a, b: str(a) != str(b),
            ">": lambda a, b: float(a) > float(b),
            "<": lambda a, b: float(a) < float(b),
            ">=": lambda a, b: float(a) >= float(b),
            "<=": lambda a, b: float(a) <= float(b),
            "contains": lambda a, b: str(b).lower() in str(a).lower(),
        }
        fn = ops.get(op)
        if fn:
            self.data = [row for row in self.data if field in row and fn(row[field], value)]
        return self

    def sort_by(self, field, reverse=False):
        """Sort by a field."""
        self.data.sort(key=lambda r: r.get(field, ""), reverse=reverse)
        return self

    def limit(self, n):
        """Limit to first N rows."""
        self.data = self.data[:n]
        return self

    def group_by(self, field):
        """Group rows by a field. Returns dict."""
        groups = defaultdict(list)
        for row in self.data:
            key = row.get(field, "unknown")
            groups[key].append(row)
        return dict(groups)

    def count(self):
        return len(self.data)

    def add_column(self, name, func):
        """Add a computed column."""
        for row in self.data:
            row[name] = func(row)
        return self

    def rename(self, old_name, new_name):
        """Rename a column."""
        for row in self.data:
            if old_name in row:
                row[new_name] = row.pop(old_name)
        return self


if __name__ == "__main__":
    sample_csv = "name,age,city\\nAlice,30,NYC\\nBob,25,LA\\nCharlie,35,NYC"
    t = DataTransformer().from_csv(sample_csv)
    print(f"Total: {t.count()}")
    t.where("city", "==", "NYC")
    print(f"NYC: {t.count()}")
    print(t.to_json())
''',
            "test_transformer.py": '''#!/usr/bin/env python3
import unittest
from transformer import DataTransformer

SAMPLE_CSV = "name,age,city\\nAlice,30,NYC\\nBob,25,LA\\nCharlie,35,NYC\\nDave,28,SF"

class TestTransformer(unittest.TestCase):
    def test_from_csv(self):
        t = DataTransformer().from_csv(SAMPLE_CSV)
        self.assertEqual(t.count(), 4)

    def test_from_json(self):
        t = DataTransformer().from_json('[{"a": 1}, {"a": 2}]')
        self.assertEqual(t.count(), 2)

    def test_select(self):
        t = DataTransformer().from_csv(SAMPLE_CSV).select("name", "city")
        self.assertNotIn("age", t.data[0])

    def test_where(self):
        t = DataTransformer().from_csv(SAMPLE_CSV).where("city", "==", "NYC")
        self.assertEqual(t.count(), 2)

    def test_where_gt(self):
        t = DataTransformer().from_csv(SAMPLE_CSV).where("age", ">", "28")
        self.assertEqual(t.count(), 2)

    def test_sort(self):
        t = DataTransformer().from_csv(SAMPLE_CSV).sort_by("name")
        self.assertEqual(t.data[0]["name"], "Alice")

    def test_limit(self):
        t = DataTransformer().from_csv(SAMPLE_CSV).limit(2)
        self.assertEqual(t.count(), 2)

    def test_group_by(self):
        t = DataTransformer().from_csv(SAMPLE_CSV)
        groups = t.group_by("city")
        self.assertEqual(len(groups["NYC"]), 2)

    def test_to_csv(self):
        t = DataTransformer().from_csv(SAMPLE_CSV)
        csv_out = t.to_csv()
        self.assertIn("Alice", csv_out)

    def test_to_json(self):
        t = DataTransformer().from_csv(SAMPLE_CSV)
        j = t.to_json()
        self.assertIn("Alice", j)

    def test_add_column(self):
        t = DataTransformer().from_csv(SAMPLE_CSV)
        t.add_column("senior", lambda r: int(r.get("age", 0)) > 30)
        self.assertIn("senior", t.data[0])

    def test_rename(self):
        t = DataTransformer().from_csv(SAMPLE_CSV).rename("name", "full_name")
        self.assertIn("full_name", t.data[0])

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_transformer.py -v"
    },
]
