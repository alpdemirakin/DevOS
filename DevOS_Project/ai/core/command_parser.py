
import re
import os
import logging
import json
from tools import TOOL_REGISTRY, run_command, write_file, read_file, git_init, git_commit, run_tests

# Command parser: converts operator imperative commands into tool invocations.
# Supports both Turkish and English commands.
# No questions. No clarification. Infer defaults and execute.

# Intent mapping: keyword patterns -> action plans
INTENT_PATTERNS = [
    # Project creation
    {
        "patterns": [
            r"(yeni|new)\s+(proje|project)\s+(?:oluştur|yarat|aç|create|init)\s*:?\s*(.*)",
            r"(proje|project)\s+(oluştur|yarat|aç|create|init)\s*:?\s*(.*)",
            r"create\s+project\s+(.*)",
            r"init\s+project\s+(.*)",
        ],
        "intent": "create_project",
    },
    # Write API
    {
        "patterns": [
            r"(api|rest|endpoint)\s*(yaz|oluştur|ekle|write|create|build)",
            r"(yaz|oluştur|create|build|write)\s+(bir\s+)?(api|rest|endpoint)",
            r"(basit|simple)\s+(bir\s+)?(api|rest)\s*(yaz|oluştur|create)",
        ],
        "intent": "create_api",
    },
    # Write/create a tool/utility
    {
        "patterns": [
            r"(yaz|oluştur|create|build|write)\s+(bir\s+)?(.*?)(\s+tool|\s+araç|\s+utility)?$",
        ],
        "intent": "create_tool",
    },
    # Add feature
    {
        "patterns": [
            r"(ekle|add)\s+(.*)",
            r"(.*)\s+(ekle|add)$",
        ],
        "intent": "add_feature",
    },
    # Run tests
    {
        "patterns": [
            r"(test|testleri?)\s*(çalıştır|run|yap|koş)",
            r"(çalıştır|run)\s+(test|testleri?)",
            r"run\s+tests?",
        ],
        "intent": "run_tests",
    },
    # Build
    {
        "patterns": [
            r"(build|derleme|derle)\s*(al|yap|et)?",
            r"(al|yap)\s+(build|derleme)",
        ],
        "intent": "build",
    },
    # Dockerize
    {
        "patterns": [
            r"docker(ize|la|le)?\s*(et|yap)?",
            r"(container|konteyner)\s*(oluştur|yap|et)",
        ],
        "intent": "dockerize",
    },
    # Git operations
    {
        "patterns": [
            r"(commit|kaydet)\s*(et|yap)?",
            r"git\s+(commit|push|pull|status|log)",
        ],
        "intent": "git_op",
    },
    # List/show
    {
        "patterns": [
            r"(listele|göster|list|show|ls)\s+(.*)",
            r"(dosyalar|files|projeler|projects)\s*(listele|göster|list|show)",
        ],
        "intent": "list",
    },
    # Read file
    {
        "patterns": [
            r"(oku|read|cat|göster|show)\s+(.+\.\w+)",
        ],
        "intent": "read_file",
    },
    # Fix/debug
    {
        "patterns": [
            r"(düzelt|fix|debug|hata)\s*(.*)",
            r"(.*)\s+(düzelt|fix)$",
        ],
        "intent": "fix",
    },
    # Raw shell command (fallback for direct commands)
    {
        "patterns": [
            r"^(python3?|pip|git|npm|node|cargo|go|make|gcc|g\+\+|sh|bash)\s+.*",
            r"^(ls|cat|mkdir|cp|mv|rm|find|grep|chmod|chown)\s+.*",
        ],
        "intent": "shell",
    },
]


class CommandParser:
    """Parses operator input into executable action plans."""

    def __init__(self, project_root="/projects"):
        self.project_root = project_root

    def parse(self, input_text):
        """
        Parse operator input and return an action plan.
        Returns: dict with 'intent', 'params', and 'actions' list
        """
        text = input_text.strip()
        if not text:
            return None

        # Try TOOL: protocol first (structured commands from LLM)
        if text.startswith("TOOL:"):
            return self._parse_tool_protocol(text)

        # Try intent matching
        for entry in INTENT_PATTERNS:
            for pattern in entry["patterns"]:
                match = re.match(pattern, text, re.IGNORECASE)
                if match:
                    return self._build_plan(entry["intent"], match, text)

        # Fallback: treat as shell command
        return {
            "intent": "shell",
            "raw": text,
            "actions": [{"tool": "run", "args": {"command": text}}]
        }

    def _parse_tool_protocol(self, text):
        """Parse TOOL: name ARGS: json format."""
        try:
            match = re.match(r'TOOL:\s*(\w+)\s*ARGS:\s*(.*)', text, re.DOTALL)
            if match:
                tool_name = match.group(1)
                args_str = match.group(2).strip()
                args = json.loads(args_str) if args_str else {}
                return {
                    "intent": "tool_call",
                    "actions": [{"tool": tool_name, "args": args}]
                }
        except json.JSONDecodeError:
            logging.error(f"Invalid TOOL args JSON: {text}")
        return None

    def _build_plan(self, intent, match, raw_text):
        """Build an execution plan based on matched intent."""

        if intent == "create_project":
            name = self._extract_name(match, raw_text) or "new_project"
            name = self._sanitize_name(name)
            return self._plan_create_project(name)

        elif intent == "create_api":
            return self._plan_create_api()

        elif intent == "create_tool":
            desc = match.group(3) if match.lastindex >= 3 else raw_text
            return self._plan_create_tool(desc.strip())

        elif intent == "add_feature":
            feature = match.group(2) if match.lastindex >= 2 else raw_text
            return self._plan_add_feature(feature.strip())

        elif intent == "run_tests":
            return self._plan_run_tests()

        elif intent == "build":
            return self._plan_build()

        elif intent == "dockerize":
            return self._plan_dockerize()

        elif intent == "git_op":
            return self._plan_git_op(raw_text)

        elif intent == "list":
            target = match.group(2) if match.lastindex >= 2 else self.project_root
            return {
                "intent": "list",
                "actions": [{"tool": "ls", "args": {"path": target.strip() or self.project_root}}]
            }

        elif intent == "read_file":
            filepath = match.group(2) if match.lastindex >= 2 else ""
            return {
                "intent": "read_file",
                "actions": [{"tool": "read", "args": {"path": filepath.strip()}}]
            }

        elif intent == "fix":
            desc = match.group(2) if match.lastindex >= 2 else raw_text
            return self._plan_fix(desc.strip())

        elif intent == "shell":
            return {
                "intent": "shell",
                "raw": raw_text,
                "actions": [{"tool": "run", "args": {"command": raw_text}}]
            }

        return {"intent": "unknown", "raw": raw_text, "actions": []}

    def _extract_name(self, match, raw):
        """Extract project/tool name from match groups."""
        for i in range(match.lastindex or 0, 0, -1):
            g = match.group(i)
            if g and len(g) > 1 and not g.lower() in ['yeni', 'new', 'proje', 'project', 'oluştur', 'create', 'init', 'yarat', 'aç']:
                return g.strip()
        return None

    def _sanitize_name(self, name):
        """Sanitize a string into a valid directory/project name."""
        name = re.sub(r'[^\w\s-]', '', name.lower())
        name = re.sub(r'[\s]+', '_', name.strip())
        return name or "project"

    def _plan_create_project(self, name):
        """Plan: create a new project directory with git."""
        path = f"{self.project_root}/{name}"
        return {
            "intent": "create_project",
            "name": name,
            "path": path,
            "actions": [
                {"tool": "mkdir", "args": {"path": path}},
                {"tool": "git_init", "args": {"path": path}},
                {"tool": "write", "args": {
                    "path": f"{path}/README.md",
                    "content": f"# {name}\n\nAuto-generated project.\n"
                }},
                {"tool": "git_commit", "args": {"path": path, "message": f"init: {name}"}},
            ]
        }

    def _plan_create_api(self):
        """Plan: create a simple REST API project."""
        name = "api_server"
        path = f"{self.project_root}/{name}"
        server_code = '''#!/usr/bin/env python3
"""Minimal HTTP API Server."""
import json
import http.server
import socketserver

PORT = 8080
DATA = {}

class APIHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self._respond(200, {"status": "ok"})
        elif self.path == '/data':
            self._respond(200, {"data": DATA})
        elif self.path.startswith('/data/'):
            key = self.path.split('/')[-1]
            if key in DATA:
                self._respond(200, {key: DATA[key]})
            else:
                self._respond(404, {"error": "not found"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        try:
            payload = json.loads(body)
            for k, v in payload.items():
                DATA[k] = v
            self._respond(201, {"stored": payload})
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid json"})

    def do_DELETE(self):
        if self.path.startswith('/data/'):
            key = self.path.split('/')[-1]
            if key in DATA:
                del DATA[key]
                self._respond(200, {"deleted": key})
            else:
                self._respond(404, {"error": "not found"})
        else:
            self._respond(400, {"error": "specify key"})

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        pass  # Suppress default logging

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), APIHandler) as httpd:
        print(f"API listening on :{PORT}")
        httpd.serve_forever()
'''
        test_code = '''#!/usr/bin/env python3
"""API Server Tests."""
import unittest
import json
import threading
import http.client
import time
import sys

sys.path.insert(0, '.')

class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server import APIHandler
        import socketserver
        cls.port = 9999
        cls.server = socketserver.TCPServer(("", cls.port), APIHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _request(self, method, path, body=None):
        conn = http.client.HTTPConnection("localhost", self.port)
        headers = {'Content-Type': 'application/json'} if body else {}
        conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        conn.close()
        return resp.status, data

    def test_health(self):
        status, data = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_post_and_get(self):
        status, data = self._request("POST", "/data", {"key1": "value1"})
        self.assertEqual(status, 201)
        status, data = self._request("GET", "/data/key1")
        self.assertEqual(status, 200)
        self.assertEqual(data["key1"], "value1")

    def test_delete(self):
        self._request("POST", "/data", {"delme": "val"})
        status, data = self._request("DELETE", "/data/delme")
        self.assertEqual(status, 200)
        status, data = self._request("GET", "/data/delme")
        self.assertEqual(status, 404)

    def test_not_found(self):
        status, data = self._request("GET", "/nonexistent")
        self.assertEqual(status, 404)

if __name__ == '__main__':
    unittest.main()
'''
        return {
            "intent": "create_api",
            "name": name,
            "path": path,
            "actions": [
                {"tool": "mkdir", "args": {"path": path}},
                {"tool": "git_init", "args": {"path": path}},
                {"tool": "write", "args": {"path": f"{path}/server.py", "content": server_code}},
                {"tool": "write", "args": {"path": f"{path}/test_server.py", "content": test_code}},
                {"tool": "test", "args": {"path": path}},
                {"tool": "git_commit", "args": {"path": path, "message": "feat: REST API server with CRUD and tests"}},
            ]
        }

    def _plan_create_tool(self, description):
        """Plan: create a CLI tool based on description."""
        name = self._sanitize_name(description) or "cli_tool"
        path = f"{self.project_root}/{name}"
        return {
            "intent": "create_tool",
            "name": name,
            "description": description,
            "path": path,
            "actions": [
                {"tool": "mkdir", "args": {"path": path}},
                {"tool": "git_init", "args": {"path": path}},
            ],
            "requires_generation": True,
        }

    def _plan_add_feature(self, feature):
        """Plan: add a feature to the current/latest project."""
        return {
            "intent": "add_feature",
            "feature": feature,
            "actions": [],
            "requires_generation": True,
        }

    def _plan_run_tests(self):
        """Plan: run tests on the most recent project."""
        latest = self._get_latest_project()
        if latest:
            return {
                "intent": "run_tests",
                "path": latest,
                "actions": [{"tool": "test", "args": {"path": latest}}]
            }
        return {
            "intent": "run_tests",
            "actions": [{"tool": "ls", "args": {"path": self.project_root}}],
            "error": "No projects found"
        }

    def _plan_build(self):
        """Plan: build the latest project."""
        latest = self._get_latest_project()
        if not latest:
            return {"intent": "build", "actions": [], "error": "No project found"}
        return {
            "intent": "build",
            "path": latest,
            "actions": [
                {"tool": "run", "args": {"command": "python3 -m py_compile *.py 2>&1 || make 2>&1 || echo 'No build system detected'", "cwd": latest}},
            ]
        }

    def _plan_dockerize(self):
        """Plan: add Docker support to the latest project."""
        latest = self._get_latest_project()
        if not latest:
            return {"intent": "dockerize", "actions": [], "error": "No project found"}

        name = os.path.basename(latest)
        dockerfile = f"""FROM python:3.12-alpine
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
EXPOSE 8080
CMD ["python3", "main.py"]
"""
        compose = f"""version: '3.8'
services:
  {name}:
    build: .
    ports:
      - "8080:8080"
    restart: unless-stopped
"""
        return {
            "intent": "dockerize",
            "path": latest,
            "actions": [
                {"tool": "write", "args": {"path": f"{latest}/Dockerfile", "content": dockerfile}},
                {"tool": "write", "args": {"path": f"{latest}/docker-compose.yml", "content": compose}},
                {"tool": "git_commit", "args": {"path": latest, "message": "feat: add Docker support"}},
            ]
        }

    def _plan_git_op(self, raw):
        """Plan: git operation."""
        latest = self._get_latest_project()
        path = latest or self.project_root

        if "commit" in raw.lower() or "kaydet" in raw.lower():
            return {
                "intent": "git_commit",
                "actions": [{"tool": "git_commit", "args": {"path": path, "message": "auto: checkpoint commit"}}]
            }
        elif "status" in raw.lower():
            return {
                "intent": "git_status",
                "actions": [{"tool": "git_status", "args": {"path": path}}]
            }
        elif "log" in raw.lower():
            return {
                "intent": "git_log",
                "actions": [{"tool": "git_log", "args": {"path": path}}]
            }
        return {
            "intent": "git_op",
            "actions": [{"tool": "run", "args": {"command": raw}}]
        }

    def _plan_fix(self, description):
        """Plan: fix/debug something."""
        latest = self._get_latest_project()
        return {
            "intent": "fix",
            "description": description,
            "path": latest,
            "actions": [],
            "requires_generation": True,
        }

    def _get_latest_project(self):
        """Get the most recently modified project directory."""
        try:
            entries = os.listdir(self.project_root)
            dirs = [
                os.path.join(self.project_root, d)
                for d in entries
                if os.path.isdir(os.path.join(self.project_root, d))
            ]
            if dirs:
                return max(dirs, key=os.path.getmtime)
        except Exception:
            pass
        return None
