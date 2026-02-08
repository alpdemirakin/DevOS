
import logging
import random
import time
import json
import os
from tools import (
    run_command, write_file, read_file, git_init, git_commit,
    git_status, run_tests, detect_project_type, list_dir,
    make_dir, TOOL_REGISTRY,
    take_screenshot, launch_browser, click_at, type_text
)
from memory import Memory
from command_parser import CommandParser
from enforce import InputSanitizer
from executor import ExecutionPipeline
from llm import LLMEngine
from network import NetworkManager
from templates import TEMPLATES_SYSTEM


class AutonomousAgent:
    """
    Core autonomous developer agent.
    Two modes of operation:
      1. OPERATOR MODE: Accepts single-line imperative commands from operator
      2. AUTONOMOUS MODE: Self-generates goals and builds projects when idle

    No questions. No chat. Execute or discard.
    """

    MAX_RETRIES = 3
    IDLE_TIMEOUT = 10  # seconds to wait for input before autonomous cycle

    def __init__(self, llm_function=None, mode="hybrid"):
        self.project_root = "/projects"
        self.current_goal = None
        self.completed_goals = []
        self.failed_goals = []
        self.mode = mode  # "operator", "autonomous", "hybrid"

        self.memory = Memory()
        self.parser = CommandParser(self.project_root)
        self.sanitizer = InputSanitizer()
        self.network = NetworkManager()

        # Initialize LLM engine
        self.llm_engine = LLMEngine()
        self.llm = self.llm_engine if self.llm_engine.is_available() else llm_function

        # Initialize execution pipeline
        self.pipeline = ExecutionPipeline(
            llm=self.llm_engine if self.llm_engine.is_available() else None,
            memory=self.memory
        )

        os.makedirs(self.project_root, exist_ok=True)

        if self.llm_engine.is_available():
            logging.info(f"AGENT: LLM loaded: {self.llm_engine.info()}")
        else:
            logging.info("AGENT: No LLM model. Running in template mode.")

    def start_loop(self):
        """Main execution loop."""
        logging.info("AGENT: Starting execution loop...")
        logging.info(f"AGENT: Mode = {self.mode}")
        logging.info(f"AGENT: Memory context:\n{self.memory.get_context_summary()}")

        while True:
            try:
                if self.mode == "operator":
                    self._operator_cycle()
                elif self.mode == "autonomous":
                    self._autonomous_cycle()
                else:
                    # Hybrid: check for operator input, fallback to autonomous
                    self._hybrid_cycle()
            except KeyboardInterrupt:
                logging.info("AGENT: Shutdown signal received.")
                break
            except Exception as e:
                logging.error(f"AGENT: Cycle error: {e}")
                self.memory.record_action("cycle_error", str(e), success=False)
                time.sleep(3)

    # --- Operator Mode ---

    def _operator_cycle(self):
        """Wait for and execute operator commands."""
        try:
            line = input("")  # Black screen, single input line
        except EOFError:
            time.sleep(1)
            return

        line = self.sanitizer.sanitize_input(line)
        if not line:
            return

        self._execute_operator_command(line)

    def _execute_operator_command(self, command):
        """Parse and execute an operator command."""
        logging.info(f"INPUT: {command}")
        self.memory.record_action("operator_input", command)

        plan = self.parser.parse(command)
        if not plan:
            logging.warning("PARSE: No actionable plan generated.")
            return

        logging.info(f"PLAN: intent={plan.get('intent')} actions={len(plan.get('actions', []))}")

        # Execute each action in the plan
        for action in plan.get("actions", []):
            tool_name = action.get("tool")
            args = action.get("args", {})

            if tool_name in TOOL_REGISTRY:
                try:
                    # Safety check for shell commands
                    if tool_name == "run" and not self.sanitizer.is_safe_command(args.get("command", "")):
                        logging.warning(f"BLOCKED: Unsafe command")
                        continue

                    func = TOOL_REGISTRY[tool_name]
                    result = func(**args)
                    logging.info(f"RESULT [{tool_name}]: {str(result)[:300]}")
                    self.memory.record_action(f"tool:{tool_name}", args, success=True)
                except Exception as e:
                    logging.error(f"TOOL ERROR [{tool_name}]: {e}")
                    self.memory.record_action(f"tool:{tool_name}", args, success=False)
            else:
                logging.warning(f"UNKNOWN TOOL: {tool_name}")

        # If plan requires code generation (needs LLM)
        if plan.get("requires_generation"):
            self._handle_generation_task(plan)

    def _handle_generation_task(self, plan):
        """Handle tasks that need code generation."""
        intent = plan.get("intent")
        name = plan.get("name", "generated")
        path = plan.get("path", f"{self.project_root}/{name}")
        description = plan.get("description", plan.get("feature", intent))

        if self.llm:
            # TODO: Use LLM to generate code for the task
            pass
        else:
            # Use template-based generation
            goal = self._find_matching_template(description)
            if goal:
                goal["name"] = name
                self._execute_goal(goal, path)
            else:
                logging.info(f"GENERATE: No template for '{description}', creating skeleton")
                self._create_skeleton_project(name, path, description)

    # --- Hybrid Mode ---

    def _hybrid_cycle(self):
        """Check for operator input with timeout, fallback to autonomous."""
        import select
        import sys

        # Try non-blocking input read
        try:
            # For Linux terminal: use select for non-blocking I/O
            if hasattr(select, 'select'):
                readable, _, _ = select.select([sys.stdin], [], [], self.IDLE_TIMEOUT)
                if readable:
                    line = sys.stdin.readline().strip()
                    if line:
                        line = self.sanitizer.sanitize_input(line)
                        self._execute_operator_command(line)
                        return
        except (OSError, ValueError):
            pass

        # No operator input -> run autonomous cycle
        self._autonomous_cycle()

    # --- Autonomous Mode ---

    def _autonomous_cycle(self):
        """Generate and execute a goal autonomously using the execution pipeline."""
        if not self.current_goal:
            self.current_goal = self._generate_goal()
            logging.info(f"GOAL: {self.current_goal['description']}")

        name = self.current_goal["name"]
        path = f"{self.project_root}/{name}"

        # Register project in memory
        if not os.path.exists(path):
            self.memory.register_project(name, path, self.current_goal["description"])

        # Execute through pipeline (handles setup, codegen, test, repair, commit)
        success, report = self.pipeline.execute_goal(self.current_goal, path)

        # Log pipeline report
        for stage in report.get("stages", []):
            status = stage.get("status", "?")
            sname = stage.get("name", "?")
            detail = stage.get("detail", "")[:100]
            logging.info(f"  [{status.upper()}] {sname}: {detail}")

        if success:
            logging.info(f"COMPLETE: {name}")
            self.completed_goals.append(self.current_goal)
            self.memory.record_success(
                self.current_goal["description"],
                list(self.current_goal.get("files", {}).keys())
            )
            self.memory.update_project(name, test_pass=True)
        else:
            logging.warning(f"FAILED: {name}")
            self.failed_goals.append(self.current_goal)
            self.memory.record_failure(
                self.current_goal["description"],
                list(self.current_goal.get("files", {}).keys()),
                "Pipeline failed"
            )

        self.current_goal = None
        time.sleep(2)

    def _generate_goal(self):
        """Generate the next development goal."""
        if self.llm:
            # TODO: Query LLM for dynamic goal
            pass

        # Avoid repeating completed goals
        completed_names = {g["name"] for g in self.completed_goals}
        failed_names = {g["name"] for g in self.failed_goals}

        available = [
            g for g in PROJECT_TEMPLATES
            if g["name"] not in completed_names and g["name"] not in failed_names
        ]

        if not available:
            # All templates done, reset failed list and try again
            self.failed_goals.clear()
            available = [g for g in PROJECT_TEMPLATES if g["name"] not in completed_names]

        if not available:
            # Try advanced templates
            available = [
                g for g in PROJECT_TEMPLATES_ADVANCED + TEMPLATES_SYSTEM
                if g["name"] not in completed_names and g["name"] not in failed_names
            ]

        if not available:
            # Everything completed, reset and start over
            self.completed_goals.clear()
            self.failed_goals.clear()
            available = PROJECT_TEMPLATES + PROJECT_TEMPLATES_ADVANCED + TEMPLATES_SYSTEM

        return random.choice(available)

    def _find_matching_template(self, description):
        """Find a template that matches a description."""
        desc_lower = description.lower()
        all_templates = PROJECT_TEMPLATES + PROJECT_TEMPLATES_ADVANCED + TEMPLATES_SYSTEM
        for template in all_templates:
            if any(kw in desc_lower for kw in template.get("keywords", [])):
                return dict(template)
        return None

    def _create_skeleton_project(self, name, path, description):
        """Create a minimal skeleton project."""
        make_dir(path)
        git_init(path)
        write_file(f"{path}/main.py", f'#!/usr/bin/env python3\n"""{description}"""\n\ndef main():\n    pass\n\nif __name__ == "__main__":\n    main()\n')
        write_file(f"{path}/README.md", f"# {name}\n\n{description}\n")
        git_commit(path, f"init: {name} skeleton")
        self.memory.register_project(name, path, description)


# ============================================================
# PROJECT TEMPLATES
# Each template is a complete, working mini-project
# ============================================================


PROJECT_TEMPLATES = [
    {
        "name": "gui_automation",
        "description": "Browser automation script using xdotool and scrot",
        "keywords": ["gui", "browser", "automation", "vision"],
        "files": {
            "browser_bot.py": '''#!/usr/bin/env python3
"""GUI Automation Bot - Opens browser, navigates, screenshots."""
import os
import time
import subprocess

def run(cmd):
    subprocess.run(cmd, shell=True)

def main():
    print("Launching Firefox...")
    run("firefox 'http://example.com' &")
    time.sleep(5) # Wait for load

    print("Taking screenshot...")
    run("scrot 'browser_view.png'")
    
    print("Simulating interaction...")
    # Move to centerish and click
    run("xdotool mousemove 500 400 click 1")
    
    print("Done. Check browser_view.png")

if __name__ == "__main__":
    main()
''',
            "README.md": "# GUI Bot\n\nAutomates browser interaction."
        },
        "test_cmd": "python3 browser_bot.py"
    },
    {
        "name": "json_parser",
        "description": "Recursive JSON parser from scratch",
        "keywords": ["json", "parser", "parse"],
        "files": {
            "parser.py": '''#!/usr/bin/env python3
"""Minimal recursive-descent JSON parser."""

class JSONParser:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def parse(self):
        self._skip_ws()
        result = self._parse_value()
        self._skip_ws()
        if self.pos < len(self.text):
            raise ValueError(f"Unexpected char at {self.pos}")
        return result

    def _parse_value(self):
        self._skip_ws()
        ch = self._peek()
        if ch == '"': return self._parse_string()
        if ch == '{': return self._parse_object()
        if ch == '[': return self._parse_array()
        if ch == 't': return self._parse_literal("true", True)
        if ch == 'f': return self._parse_literal("false", False)
        if ch == 'n': return self._parse_literal("null", None)
        if ch in '-0123456789': return self._parse_number()
        raise ValueError(f"Unexpected char '{ch}' at {self.pos}")

    def _parse_string(self):
        self._expect('"')
        result = []
        while self._peek() != '"':
            ch = self._advance()
            if ch == '\\\\':
                esc = self._advance()
                escapes = {'n': '\\n', 't': '\\t', 'r': '\\r', '"': '"', '\\\\': '\\\\'}
                result.append(escapes.get(esc, esc))
            else:
                result.append(ch)
        self._expect('"')
        return ''.join(result)

    def _parse_number(self):
        start = self.pos
        if self._peek() == '-': self._advance()
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self._advance()
        if self.pos < len(self.text) and self.text[self.pos] == '.':
            self._advance()
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self._advance()
            return float(self.text[start:self.pos])
        return int(self.text[start:self.pos])

    def _parse_object(self):
        self._expect('{')
        obj = {}
        self._skip_ws()
        if self._peek() != '}':
            key = self._parse_string()
            self._skip_ws()
            self._expect(':')
            obj[key] = self._parse_value()
            while self._peek() == ',':
                self._advance()
                self._skip_ws()
                key = self._parse_string()
                self._skip_ws()
                self._expect(':')
                obj[key] = self._parse_value()
        self._expect('}')
        return obj

    def _parse_array(self):
        self._expect('[')
        arr = []
        self._skip_ws()
        if self._peek() != ']':
            arr.append(self._parse_value())
            while self._peek() == ',':
                self._advance()
                arr.append(self._parse_value())
        self._expect(']')
        return arr

    def _parse_literal(self, expected, value):
        for ch in expected:
            if self._advance() != ch:
                raise ValueError(f"Expected '{expected}'")
        return value

    def _peek(self):
        self._skip_ws()
        if self.pos >= len(self.text):
            raise ValueError("Unexpected end of input")
        return self.text[self.pos]

    def _advance(self):
        ch = self.text[self.pos]
        self.pos += 1
        return ch

    def _expect(self, ch):
        self._skip_ws()
        if self._advance() != ch:
            raise ValueError(f"Expected '{ch}' at {self.pos-1}")

    def _skip_ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in ' \\t\\n\\r':
            self.pos += 1


def parse_json(text):
    return JSONParser(text).parse()


if __name__ == "__main__":
    test = '{"name": "DevOS", "version": 1, "features": ["autonomous", "offline"]}'
    print(parse_json(test))
''',
            "test_parser.py": '''#!/usr/bin/env python3
import unittest
from parser import parse_json

class TestJSONParser(unittest.TestCase):
    def test_string(self):
        self.assertEqual(parse_json('"hello"'), "hello")

    def test_number_int(self):
        self.assertEqual(parse_json('42'), 42)

    def test_number_float(self):
        self.assertAlmostEqual(parse_json('3.14'), 3.14)

    def test_negative(self):
        self.assertEqual(parse_json('-7'), -7)

    def test_boolean(self):
        self.assertTrue(parse_json('true'))
        self.assertFalse(parse_json('false'))

    def test_null(self):
        self.assertIsNone(parse_json('null'))

    def test_array(self):
        self.assertEqual(parse_json('[1, 2, 3]'), [1, 2, 3])

    def test_object(self):
        result = parse_json('{"a": 1, "b": "two"}')
        self.assertEqual(result, {"a": 1, "b": "two"})

    def test_nested(self):
        result = parse_json('{"data": [1, {"x": true}]}')
        self.assertEqual(result, {"data": [1, {"x": True}]})

    def test_empty_object(self):
        self.assertEqual(parse_json('{}'), {})

    def test_empty_array(self):
        self.assertEqual(parse_json('[]'), [])

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_parser.py -v"
    },
    {
        "name": "http_server",
        "description": "Minimal HTTP server with routing",
        "keywords": ["http", "server", "web", "api"],
        "files": {
            "server.py": '''#!/usr/bin/env python3
"""Minimal HTTP server with routing support."""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

routes = {}

def route(path, method="GET"):
    def decorator(func):
        routes[(method, path)] = func
        return func
    return decorator

@route("/", "GET")
def index(handler):
    return {"message": "DevOS HTTP Server", "status": "running"}

@route("/health", "GET")
def health(handler):
    return {"status": "ok"}

@route("/echo", "POST")
def echo(handler):
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length).decode()
    return {"echo": body}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")

    def _handle(self, method):
        key = (method, self.path)
        if key in routes:
            result = routes[key](self)
            self._send(200, result)
        else:
            self._send(404, {"error": "not found"})

    def _send(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args): pass

if __name__ == "__main__":
    port = 8080
    httpd = HTTPServer(("", port), Handler)
    print(f"Listening on :{port}")
    httpd.serve_forever()
''',
            "test_server.py": '''#!/usr/bin/env python3
import unittest
import threading
import json
import http.client
import time
from server import HTTPServer, Handler

class TestHTTPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 19876
        cls.server = HTTPServer(("", cls.port), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _get(self, path):
        conn = http.client.HTTPConnection("localhost", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        conn.close()
        return resp.status, data

    def test_index(self):
        status, data = self._get("/")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "running")

    def test_health(self):
        status, data = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_not_found(self):
        status, data = self._get("/nope")
        self.assertEqual(status, 404)

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_server.py -v"
    },
    {
        "name": "cli_todo",
        "description": "Command-line TODO list manager with file persistence",
        "keywords": ["todo", "task", "list", "cli"],
        "files": {
            "todo.py": '''#!/usr/bin/env python3
"""CLI TODO Manager with file-based persistence."""
import sys
import json
import os

DB_FILE = os.path.join(os.path.dirname(__file__), "todos.json")

def load():
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return json.load(f)
    return []

def save(todos):
    with open(DB_FILE, 'w') as f:
        json.dump(todos, f, indent=2)

def add(text):
    todos = load()
    todos.append({"id": len(todos)+1, "text": text, "done": False})
    save(todos)
    print(f"Added: {text}")

def done(task_id):
    todos = load()
    for t in todos:
        if t["id"] == task_id:
            t["done"] = True
            save(todos)
            print(f"Done: {t['text']}")
            return
    print(f"Not found: {task_id}")

def remove(task_id):
    todos = load()
    todos = [t for t in todos if t["id"] != task_id]
    save(todos)
    print(f"Removed: {task_id}")

def show():
    todos = load()
    if not todos:
        print("No tasks.")
        return
    for t in todos:
        mark = "x" if t["done"] else " "
        print(f"  [{mark}] {t['id']}: {t['text']}")

def main():
    if len(sys.argv) < 2:
        show()
        return
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) > 2:
        add(" ".join(sys.argv[2:]))
    elif cmd == "done" and len(sys.argv) > 2:
        done(int(sys.argv[2]))
    elif cmd == "rm" and len(sys.argv) > 2:
        remove(int(sys.argv[2]))
    elif cmd == "list":
        show()
    else:
        print(f"Usage: todo.py [add|done|rm|list] [args]")

if __name__ == "__main__":
    main()
''',
            "test_todo.py": '''#!/usr/bin/env python3
import unittest
import os
import json
import sys
sys.path.insert(0, os.path.dirname(__file__))
import todo

class TestTodo(unittest.TestCase):
    def setUp(self):
        todo.DB_FILE = "/tmp/test_todos.json"
        if os.path.exists(todo.DB_FILE):
            os.remove(todo.DB_FILE)

    def tearDown(self):
        if os.path.exists(todo.DB_FILE):
            os.remove(todo.DB_FILE)

    def test_add_and_load(self):
        todo.add("Test task")
        todos = todo.load()
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["text"], "Test task")
        self.assertFalse(todos[0]["done"])

    def test_done(self):
        todo.add("Finish")
        todo.done(1)
        todos = todo.load()
        self.assertTrue(todos[0]["done"])

    def test_remove(self):
        todo.add("Remove me")
        todo.remove(1)
        todos = todo.load()
        self.assertEqual(len(todos), 0)

    def test_multiple(self):
        todo.add("First")
        todo.add("Second")
        todo.add("Third")
        todos = todo.load()
        self.assertEqual(len(todos), 3)

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_todo.py -v"
    },
    {
        "name": "log_analyzer",
        "description": "System log parser and error aggregator",
        "keywords": ["log", "analyzer", "parse", "error"],
        "files": {
            "analyzer.py": '''#!/usr/bin/env python3
"""Log file analyzer - parses logs, extracts errors, generates reports."""
import re
import sys
import json
from collections import Counter

class LogAnalyzer:
    LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"]
    PATTERN = re.compile(
        r"(\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}:\\d{2})?\\s*"
        r"\\[?(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\\]?\\s*:?\\s*(.*)",
        re.IGNORECASE
    )

    def __init__(self):
        self.entries = []
        self.level_counts = Counter()
        self.errors = []

    def parse_file(self, filepath):
        with open(filepath) as f:
            for line_no, line in enumerate(f, 1):
                self._parse_line(line.strip(), line_no)
        return self

    def parse_text(self, text):
        for line_no, line in enumerate(text.strip().split("\\n"), 1):
            self._parse_line(line.strip(), line_no)
        return self

    def _parse_line(self, line, line_no):
        if not line:
            return
        match = self.PATTERN.match(line)
        if match:
            timestamp = match.group(1) or ""
            level = match.group(2).upper()
            if level == "WARN":
                level = "WARNING"
            message = match.group(3).strip()
            entry = {"line": line_no, "timestamp": timestamp, "level": level, "message": message}
            self.entries.append(entry)
            self.level_counts[level] += 1
            if level in ("ERROR", "CRITICAL", "FATAL"):
                self.errors.append(entry)

    def report(self):
        return {
            "total_lines": len(self.entries),
            "level_distribution": dict(self.level_counts),
            "error_count": len(self.errors),
            "errors": [{"line": e["line"], "message": e["message"][:100]} for e in self.errors[:20]],
        }

    def summary(self):
        r = self.report()
        lines = [f"Total entries: {r['total_lines']}"]
        for level in self.LEVELS:
            count = r["level_distribution"].get(level, 0)
            if count:
                lines.append(f"  {level}: {count}")
        if r["errors"]:
            lines.append(f"Errors ({r['error_count']}):")
            for e in r["errors"]:
                lines.append(f"  L{e['line']}: {e['message']}")
        return "\\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyzer = LogAnalyzer().parse_file(sys.argv[1])
    else:
        sample = """2024-01-01 10:00:00 [INFO] System started
2024-01-01 10:00:01 [DEBUG] Loading config
2024-01-01 10:00:02 [WARNING] Disk usage at 80%
2024-01-01 10:00:03 [ERROR] Failed to connect to database
2024-01-01 10:00:04 [INFO] Retrying...
2024-01-01 10:00:05 [ERROR] Connection timeout
2024-01-01 10:00:06 [CRITICAL] Service unavailable"""
        analyzer = LogAnalyzer().parse_text(sample)
    print(analyzer.summary())
''',
            "test_analyzer.py": '''#!/usr/bin/env python3
import unittest
from analyzer import LogAnalyzer

SAMPLE_LOG = """2024-01-01 10:00:00 [INFO] Boot complete
2024-01-01 10:00:01 [DEBUG] Config loaded
2024-01-01 10:00:02 [WARNING] Low memory
2024-01-01 10:00:03 [ERROR] Disk read failure
2024-01-01 10:00:04 [INFO] Recovered
2024-01-01 10:00:05 [CRITICAL] Kernel panic"""

class TestLogAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = LogAnalyzer().parse_text(SAMPLE_LOG)

    def test_total_entries(self):
        self.assertEqual(len(self.analyzer.entries), 6)

    def test_error_count(self):
        self.assertEqual(len(self.analyzer.errors), 2)

    def test_levels(self):
        r = self.analyzer.report()
        self.assertEqual(r["level_distribution"]["INFO"], 2)
        self.assertEqual(r["level_distribution"]["ERROR"], 1)
        self.assertEqual(r["level_distribution"]["CRITICAL"], 1)

    def test_summary_output(self):
        s = self.analyzer.summary()
        self.assertIn("Total entries: 6", s)
        self.assertIn("ERROR", s)

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_analyzer.py -v"
    },
    {
        "name": "file_hasher",
        "description": "File integrity checker using SHA-256 hashing",
        "keywords": ["hash", "checksum", "integrity", "sha"],
        "files": {
            "hasher.py": '''#!/usr/bin/env python3
"""File integrity checker using SHA-256."""
import hashlib
import os
import json
import sys

HASH_DB = "checksums.json"

def hash_file(filepath):
    sha = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha.update(chunk)
    return sha.hexdigest()

def hash_directory(dirpath):
    results = {}
    for root, dirs, files in os.walk(dirpath):
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, dirpath)
            results[rel] = hash_file(fpath)
    return results

def save_checksums(checksums, db_path=HASH_DB):
    with open(db_path, 'w') as f:
        json.dump(checksums, f, indent=2)

def load_checksums(db_path=HASH_DB):
    if os.path.exists(db_path):
        with open(db_path) as f:
            return json.load(f)
    return {}

def verify(dirpath, db_path=HASH_DB):
    saved = load_checksums(db_path)
    current = hash_directory(dirpath)
    report = {"ok": [], "modified": [], "added": [], "removed": []}
    for f, h in current.items():
        if f in saved:
            if saved[f] == h:
                report["ok"].append(f)
            else:
                report["modified"].append(f)
        else:
            report["added"].append(f)
    for f in saved:
        if f not in current:
            report["removed"].append(f)
    return report

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: hasher.py [hash|verify] <path>")
        sys.exit(1)
    cmd = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else "."
    if cmd == "hash":
        checksums = hash_directory(path)
        save_checksums(checksums)
        print(f"Hashed {len(checksums)} files")
    elif cmd == "verify":
        report = verify(path)
        print(f"OK: {len(report['ok'])}, Modified: {len(report['modified'])}, Added: {len(report['added'])}, Removed: {len(report['removed'])}")
''',
            "test_hasher.py": '''#!/usr/bin/env python3
import unittest
import tempfile
import os
from hasher import hash_file, hash_directory, save_checksums, verify

class TestHasher(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(self.tmpdir, "a.txt"), 'w') as f:
            f.write("hello")
        with open(os.path.join(self.tmpdir, "b.txt"), 'w') as f:
            f.write("world")

    def test_hash_file(self):
        h = hash_file(os.path.join(self.tmpdir, "a.txt"))
        self.assertEqual(len(h), 64)

    def test_hash_directory(self):
        result = hash_directory(self.tmpdir)
        self.assertIn("a.txt", result)
        self.assertIn("b.txt", result)

    def test_verify_no_changes(self):
        checksums = hash_directory(self.tmpdir)
        db = os.path.join(self.tmpdir, "db.json")
        save_checksums(checksums, db)
        report = verify(self.tmpdir, db)
        self.assertEqual(len(report["modified"]), 0)

    def test_verify_modified(self):
        checksums = hash_directory(self.tmpdir)
        db = os.path.join(self.tmpdir, "db.json")
        save_checksums(checksums, db)
        with open(os.path.join(self.tmpdir, "a.txt"), 'w') as f:
            f.write("changed")
        report = verify(self.tmpdir, db)
        self.assertIn("a.txt", report["modified"])

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_hasher.py -v"
    },
    {
        "name": "key_value_store",
        "description": "In-memory key-value store with persistence",
        "keywords": ["kv", "store", "database", "key", "value", "cache"],
        "files": {
            "kvstore.py": '''#!/usr/bin/env python3
"""Thread-safe key-value store with optional disk persistence."""
import json
import os
import threading
import time

class KVStore:
    def __init__(self, persist_path=None):
        self._data = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if persist_path and os.path.exists(persist_path):
            self._load()

    def get(self, key, default=None):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            if self._is_expired(key):
                del self._data[key]
                return default
            return entry["value"]

    def set(self, key, value, ttl=None):
        with self._lock:
            entry = {"value": value, "created": time.time()}
            if ttl:
                entry["expires"] = time.time() + ttl
            self._data[key] = entry
            self._save()

    def delete(self, key):
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save()
                return True
            return False

    def exists(self, key):
        with self._lock:
            return key in self._data and not self._is_expired(key)

    def keys(self):
        with self._lock:
            self._cleanup_expired()
            return list(self._data.keys())

    def all(self):
        with self._lock:
            self._cleanup_expired()
            return {k: v["value"] for k, v in self._data.items()}

    def count(self):
        with self._lock:
            return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()
            self._save()

    def _is_expired(self, key):
        entry = self._data.get(key)
        if entry and "expires" in entry:
            return time.time() > entry["expires"]
        return False

    def _cleanup_expired(self):
        expired = [k for k in self._data if self._is_expired(k)]
        for k in expired:
            del self._data[k]

    def _save(self):
        if self._persist_path:
            with open(self._persist_path, 'w') as f:
                json.dump(self._data, f)

    def _load(self):
        with open(self._persist_path) as f:
            self._data = json.load(f)

if __name__ == "__main__":
    store = KVStore()
    store.set("name", "DevOS")
    store.set("version", 1)
    print(store.all())
''',
            "test_kvstore.py": '''#!/usr/bin/env python3
import unittest
import tempfile
import os
from kvstore import KVStore

class TestKVStore(unittest.TestCase):
    def test_set_get(self):
        store = KVStore()
        store.set("a", 1)
        self.assertEqual(store.get("a"), 1)

    def test_delete(self):
        store = KVStore()
        store.set("x", "val")
        self.assertTrue(store.delete("x"))
        self.assertFalse(store.exists("x"))

    def test_keys(self):
        store = KVStore()
        store.set("k1", "v1")
        store.set("k2", "v2")
        self.assertEqual(sorted(store.keys()), ["k1", "k2"])

    def test_persistence(self):
        path = tempfile.mktemp(suffix=".json")
        store1 = KVStore(persist_path=path)
        store1.set("persist", "yes")
        store2 = KVStore(persist_path=path)
        self.assertEqual(store2.get("persist"), "yes")
        os.remove(path)

    def test_clear(self):
        store = KVStore()
        store.set("a", 1)
        store.clear()
        self.assertEqual(store.count(), 0)

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_kvstore.py -v"
    },
]

PROJECT_TEMPLATES_ADVANCED = [
    {
        "name": "task_scheduler",
        "description": "Cron-like task scheduler with interval support",
        "keywords": ["schedule", "cron", "timer", "task"],
        "files": {
            "scheduler.py": '''#!/usr/bin/env python3
"""Simple task scheduler with interval-based execution."""
import time
import threading
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

class Task:
    def __init__(self, name, func, interval, args=None):
        self.name = name
        self.func = func
        self.interval = interval
        self.args = args or []
        self.last_run = 0
        self.run_count = 0
        self.enabled = True

    def is_due(self):
        return self.enabled and (time.time() - self.last_run) >= self.interval

    def execute(self):
        try:
            self.func(*self.args)
            self.last_run = time.time()
            self.run_count += 1
            return True
        except Exception as e:
            logging.error(f"TASK [{self.name}] failed: {e}")
            return False

class Scheduler:
    def __init__(self):
        self.tasks = {}
        self._running = False

    def add(self, name, func, interval, args=None):
        self.tasks[name] = Task(name, func, interval, args)

    def remove(self, name):
        self.tasks.pop(name, None)

    def run_once(self):
        for task in self.tasks.values():
            if task.is_due():
                task.execute()

    def run_forever(self, tick=1):
        self._running = True
        while self._running:
            self.run_once()
            time.sleep(tick)

    def stop(self):
        self._running = False

    def status(self):
        return {name: {"runs": t.run_count, "enabled": t.enabled} for name, t in self.tasks.items()}

if __name__ == "__main__":
    s = Scheduler()
    s.add("heartbeat", lambda: print("alive"), interval=5)
    s.run_forever()
''',
            "test_scheduler.py": '''#!/usr/bin/env python3
import unittest
import time
from scheduler import Scheduler, Task

class TestScheduler(unittest.TestCase):
    def test_task_due(self):
        t = Task("t", lambda: None, interval=0.1)
        self.assertTrue(t.is_due())

    def test_task_execute(self):
        results = []
        t = Task("t", lambda: results.append(1), interval=0)
        t.execute()
        self.assertEqual(results, [1])
        self.assertEqual(t.run_count, 1)

    def test_scheduler_run_once(self):
        results = []
        s = Scheduler()
        s.add("test", lambda: results.append("ok"), interval=0)
        s.run_once()
        self.assertEqual(results, ["ok"])

    def test_scheduler_status(self):
        s = Scheduler()
        s.add("a", lambda: None, interval=1)
        status = s.status()
        self.assertIn("a", status)

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_scheduler.py -v"
    },
    {
        "name": "text_indexer",
        "description": "Full-text search index for files",
        "keywords": ["search", "index", "text", "find", "grep"],
        "files": {
            "indexer.py": '''#!/usr/bin/env python3
"""Simple inverted index for full-text file search."""
import os
import re
from collections import defaultdict

class TextIndexer:
    def __init__(self):
        self.index = defaultdict(set)
        self.documents = {}

    def add_file(self, filepath):
        with open(filepath) as f:
            content = f.read()
        doc_id = filepath
        self.documents[doc_id] = content
        words = self._tokenize(content)
        for word in words:
            self.index[word].add(doc_id)

    def add_directory(self, dirpath, extensions=None):
        extensions = extensions or ['.py', '.txt', '.md', '.json', '.sh']
        for root, dirs, files in os.walk(dirpath):
            for fname in files:
                if any(fname.endswith(ext) for ext in extensions):
                    self.add_file(os.path.join(root, fname))

    def search(self, query):
        words = self._tokenize(query)
        if not words:
            return []
        result_sets = [self.index.get(w, set()) for w in words]
        matches = set.intersection(*result_sets) if result_sets else set()
        results = []
        for doc_id in matches:
            lines = self.documents[doc_id].split("\\n")
            matching_lines = []
            for i, line in enumerate(lines, 1):
                if any(w in line.lower() for w in words):
                    matching_lines.append((i, line.strip()))
            results.append({"file": doc_id, "matches": matching_lines[:5]})
        return results

    def stats(self):
        return {"documents": len(self.documents), "terms": len(self.index)}

    def _tokenize(self, text):
        return list(set(re.findall(r"[a-z0-9_]+", text.lower())))

if __name__ == "__main__":
    idx = TextIndexer()
    idx.add_directory(".")
    print(f"Indexed: {idx.stats()}")
''',
            "test_indexer.py": '''#!/usr/bin/env python3
import unittest
import tempfile
import os
from indexer import TextIndexer

class TestIndexer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(self.tmpdir, "a.txt"), 'w') as f:
            f.write("hello world\\nfoo bar\\nhello again")
        with open(os.path.join(self.tmpdir, "b.txt"), 'w') as f:
            f.write("goodbye world\\nbaz qux")

    def test_add_and_search(self):
        idx = TextIndexer()
        idx.add_directory(self.tmpdir)
        results = idx.search("hello")
        self.assertEqual(len(results), 1)

    def test_multi_word_search(self):
        idx = TextIndexer()
        idx.add_directory(self.tmpdir)
        results = idx.search("world")
        self.assertEqual(len(results), 2)

    def test_stats(self):
        idx = TextIndexer()
        idx.add_directory(self.tmpdir)
        stats = idx.stats()
        self.assertEqual(stats["documents"], 2)

if __name__ == "__main__":
    unittest.main()
''',
        },
        "test_cmd": "python3 -m unittest test_indexer.py -v"
    },
]
