
import os
import subprocess
import logging
import json
import shutil

PROJECTS_DIR = "/projects"
LOGS_DIR = "/logs"
FORBIDDEN_COMMANDS = [
    "rm -rf /",
    ":(){ :|:& };:",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "mkfs",
    "> /dev/sda",
    "mv / ",
    "chmod -R 777 /",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init 0",
    "init 6",
]


def _check_safety(command):
    """Validates command against forbidden patterns. Returns True if safe."""
    cmd_lower = command.lower().strip()
    for forbidden in FORBIDDEN_COMMANDS:
        if forbidden in cmd_lower:
            logging.warning(f"BLOCKED: Forbidden command pattern detected: {forbidden}")
            return False
    return True


def run_command(command, cwd=None, timeout=60):
    """Executes a shell command with safety checks and timeout."""
    if not _check_safety(command):
        return "ERROR: Command blocked by safety filter."

    logging.info(f"EXEC: {command}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            if output:
                logging.info(f"OK: {output[:200]}")
            return result.stdout
        else:
            err = result.stderr.strip()
            logging.error(f"FAIL [{result.returncode}]: {err[:200]}")
            return f"ERROR [{result.returncode}]: {err}"
    except subprocess.TimeoutExpired:
        logging.error(f"TIMEOUT: Command exceeded {timeout}s")
        return f"ERROR: Command timed out after {timeout}s"
    except Exception as e:
        logging.error(f"EXEC ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def write_file(path, content):
    """Writes content to a file, creating parent directories if needed."""
    logging.info(f"WRITE: {path}")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        logging.info(f"WRITTEN: {path} ({len(content)} bytes)")
        return f"OK: Written {len(content)} bytes to {path}"
    except Exception as e:
        logging.error(f"WRITE ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def read_file(path):
    """Reads and returns file contents."""
    logging.info(f"READ: {path}")
    try:
        with open(path, 'r') as f:
            content = f.read()
        logging.info(f"READ OK: {path} ({len(content)} bytes)")
        return content
    except FileNotFoundError:
        logging.error(f"NOT FOUND: {path}")
        return f"ERROR: File not found: {path}"
    except Exception as e:
        logging.error(f"READ ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def append_file(path, content):
    """Appends content to a file."""
    logging.info(f"APPEND: {path}")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a') as f:
            f.write(content)
        return f"OK: Appended {len(content)} bytes to {path}"
    except Exception as e:
        logging.error(f"APPEND ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def delete_file(path):
    """Deletes a file. Won't delete system-critical paths."""
    critical = ["/ai/core/", "/init", "/bin/", "/sbin/", "/usr/bin/"]
    for c in critical:
        if path.startswith(c):
            logging.warning(f"BLOCKED: Cannot delete system file: {path}")
            return f"ERROR: Cannot delete system-critical path: {path}"

    logging.info(f"DELETE: {path}")
    try:
        os.remove(path)
        return f"OK: Deleted {path}"
    except Exception as e:
        logging.error(f"DELETE ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def list_dir(path, recursive=False):
    """Lists directory contents."""
    logging.info(f"LIST: {path} (recursive={recursive})")
    try:
        if recursive:
            entries = []
            for root, dirs, files in os.walk(path):
                level = root.replace(path, '').count(os.sep)
                indent = '  ' * level
                entries.append(f"{indent}{os.path.basename(root)}/")
                sub_indent = '  ' * (level + 1)
                for f in files:
                    entries.append(f"{sub_indent}{f}")
            return '\n'.join(entries)
        else:
            entries = os.listdir(path)
            result = []
            for e in sorted(entries):
                full = os.path.join(path, e)
                prefix = "d " if os.path.isdir(full) else "f "
                result.append(f"{prefix}{e}")
            return '\n'.join(result)
    except Exception as e:
        logging.error(f"LIST ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def find_files(path, pattern):
    """Finds files matching a pattern using shell find command."""
    logging.info(f"FIND: {pattern} in {path}")
    return run_command(f"find {path} -name '{pattern}' -type f 2>/dev/null")


def file_exists(path):
    """Checks if a file or directory exists."""
    exists = os.path.exists(path)
    kind = "directory" if os.path.isdir(path) else "file" if exists else "missing"
    return f"{kind}: {path}"


def make_dir(path):
    """Creates a directory (and parents)."""
    logging.info(f"MKDIR: {path}")
    try:
        os.makedirs(path, exist_ok=True)
        return f"OK: Directory created: {path}"
    except Exception as e:
        logging.error(f"MKDIR ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def copy_path(src, dst):
    """Copies a file or directory."""
    logging.info(f"COPY: {src} -> {dst}")
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        return f"OK: Copied {src} -> {dst}"
    except Exception as e:
        logging.error(f"COPY ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


def move_path(src, dst):
    """Moves/renames a file or directory."""
    logging.info(f"MOVE: {src} -> {dst}")
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return f"OK: Moved {src} -> {dst}"
    except Exception as e:
        logging.error(f"MOVE ERROR: {str(e)}")
        return f"ERROR: {str(e)}"


# --- Git Operations ---

def git_init(path):
    """Initialize a git repository."""
    make_dir(path)
    run_command("git config --global init.defaultBranch main", cwd=path)
    return run_command("git init", cwd=path)


def git_commit(path, message):
    """Stage all and commit."""
    run_command("git add -A", cwd=path)
    run_command("git config user.email 'devos@autonomous.local'", cwd=path)
    run_command("git config user.name 'DevOS-Agent'", cwd=path)
    return run_command(f'git commit -m "{message}"', cwd=path)


def git_status(path):
    """Get git status."""
    return run_command("git status --short", cwd=path)


def git_log(path, count=10):
    """Get recent git log."""
    return run_command(f"git log --oneline -n {count}", cwd=path)


def git_diff(path):
    """Get unstaged diff."""
    return run_command("git diff", cwd=path)


# --- Process Management ---

def list_processes():
    """List running processes."""
    return run_command("ps aux")


def kill_process(pid):
    """Kill a process by PID."""
    logging.info(f"KILL: PID {pid}")
    return run_command(f"kill {pid}")


# --- System Info ---

def system_info():
    """Get basic system information."""
    info = {}
    info['hostname'] = run_command("hostname").strip()
    info['uptime'] = run_command("uptime").strip()
    info['memory'] = run_command("free -m 2>/dev/null || cat /proc/meminfo | head -5").strip()
    info['disk'] = run_command("df -h / 2>/dev/null").strip()
    info['python'] = run_command("python3 --version").strip()
    return json.dumps(info, indent=2)


# --- GUI & Vision Tools ---

def take_screenshot(filename="screenshot.png"):
    """Takes a screenshot of the X11 display using scrot."""
    logging.info(f"VISION: Capturing screen to {filename}")
    # Ensure filename is absolute or relative to cwd
    return run_command(f"scrot '{filename}'")


def launch_browser(url="https://google.com"):
    """Launches Firefox in background."""
    logging.info(f"GUI: Launching browser at {url}")
    return run_command(f"firefox '{url}' &")


def click_at(x, y):
    """Moves mouse and clicks at coordinates."""
    logging.info(f"CONTROL: Click at {x},{y}")
    return run_command(f"xdotool mousemove {x} {y} click 1")


def type_text(text):
    """Types text using xdotool."""
    logging.info(f"CONTROL: Typing '{text}'")
    # Escape single quotes for shell safety
    safe_text = text.replace("'", "'\\''")
    return run_command(f"xdotool type '{safe_text}'")


# --- Build & Test ---

def detect_project_type(path):
    """Detect project type by examining files."""
    indicators = {
        'python': ['setup.py', 'pyproject.toml', 'requirements.txt', '*.py'],
        'node': ['package.json', 'node_modules'],
        'rust': ['Cargo.toml'],
        'go': ['go.mod'],
        'c': ['Makefile', '*.c', '*.h'],
        'shell': ['*.sh'],
    }

    detected = []
    try:
        files = os.listdir(path)
        for ptype, markers in indicators.items():
            for marker in markers:
                if marker.startswith('*'):
                    ext = marker[1:]
                    if any(f.endswith(ext) for f in files):
                        detected.append(ptype)
                        break
                elif marker in files:
                    detected.append(ptype)
                    break
    except Exception:
        pass

    return detected if detected else ['unknown']


def run_tests(path):
    """Auto-detect and run tests for a project."""
    ptypes = detect_project_type(path)
    logging.info(f"PROJECT TYPE: {ptypes}")

    results = []
    if 'python' in ptypes:
        r = run_command("python3 -m pytest -x 2>/dev/null || python3 -m unittest discover -s . 2>&1", cwd=path, timeout=120)
        results.append(f"[python] {r}")
    if 'node' in ptypes:
        r = run_command("npm test 2>&1", cwd=path, timeout=120)
        results.append(f"[node] {r}")
    if 'rust' in ptypes:
        r = run_command("cargo test 2>&1", cwd=path, timeout=120)
        results.append(f"[rust] {r}")
    if 'go' in ptypes:
        r = run_command("go test ./... 2>&1", cwd=path, timeout=120)
        results.append(f"[go] {r}")
    if 'c' in ptypes:
        r = run_command("make test 2>&1 || make && ./a.out 2>&1", cwd=path, timeout=120)
        results.append(f"[c] {r}")

    if not results:
        results.append("[unknown] No test runner detected")

    return '\n'.join(results)


# --- Tool Registry ---
# Maps tool names to functions for the command parser

TOOL_REGISTRY = {
    "run": run_command,
    "write": write_file,
    "read": read_file,
    "append": append_file,
    "delete": delete_file,
    "ls": list_dir,
    "find": find_files,
    "exists": file_exists,
    "mkdir": make_dir,
    "cp": copy_path,
    "mv": move_path,
    "git_init": git_init,
    "git_commit": git_commit,
    "git_status": git_status,
    "git_log": git_log,
    "git_diff": git_diff,
    "ps": list_processes,
    "kill": kill_process,
    "sysinfo": system_info,
    "detect_type": detect_project_type,
    "test": run_tests,
    # GUI Tools
    "screenshot": take_screenshot,
    "browser": launch_browser,
    "click": click_at,
    "type": type_text,
}
