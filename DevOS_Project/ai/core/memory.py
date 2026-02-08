
import os
import json
import logging
import time

MEMORY_DIR = "/ai/memory"
STATE_FILE = os.path.join(MEMORY_DIR, "state.json")
HISTORY_FILE = os.path.join(MEMORY_DIR, "history.jsonl")
PROJECTS_FILE = os.path.join(MEMORY_DIR, "projects.json")
PATTERNS_FILE = os.path.join(MEMORY_DIR, "patterns.json")


class Memory:
    """
    Persistent memory system for DevOS agent.
    Stores: execution history, project registry, learned patterns, agent state.
    All data is JSON-based and persisted to /ai/memory/.
    """

    def __init__(self, memory_dir=MEMORY_DIR):
        self.memory_dir = memory_dir
        self.state_file = os.path.join(memory_dir, "state.json")
        self.history_file = os.path.join(memory_dir, "history.jsonl")
        self.projects_file = os.path.join(memory_dir, "projects.json")
        self.patterns_file = os.path.join(memory_dir, "patterns.json")

        os.makedirs(memory_dir, exist_ok=True)

        self.state = self._load_json(self.state_file, default={
            "boot_count": 0,
            "total_goals_completed": 0,
            "total_goals_failed": 0,
            "total_commands_executed": 0,
            "last_active_project": None,
            "last_boot": None,
        })
        self.projects = self._load_json(self.projects_file, default={})
        self.patterns = self._load_json(self.patterns_file, default={
            "successful_patterns": [],
            "failed_patterns": [],
        })

        # Update boot state
        self.state["boot_count"] += 1
        self.state["last_boot"] = time.time()
        self._save_state()

        logging.info(f"MEMORY: Loaded. Boot #{self.state['boot_count']}, "
                     f"{self.state['total_goals_completed']} goals completed historically.")

    def _load_json(self, path, default=None):
        """Load a JSON file, returning default if not found."""
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"MEMORY: Failed to load {path}: {e}")
        return default if default is not None else {}

    def _save_json(self, path, data):
        """Save data to a JSON file."""
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logging.error(f"MEMORY: Failed to save {path}: {e}")

    def _save_state(self):
        self._save_json(self.state_file, self.state)

    # --- History ---

    def record_action(self, action_type, details, success=True):
        """Append an action to the history log (JSONL format)."""
        entry = {
            "timestamp": time.time(),
            "type": action_type,
            "details": details,
            "success": success,
        }
        try:
            with open(self.history_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except IOError as e:
            logging.error(f"MEMORY: History write failed: {e}")

        self.state["total_commands_executed"] += 1
        self._save_state()

    def get_recent_history(self, count=20):
        """Get the last N history entries."""
        entries = []
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    lines = f.readlines()
                for line in lines[-count:]:
                    try:
                        entries.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass
        return entries

    # --- Project Registry ---

    def register_project(self, name, path, description="", language="python"):
        """Register a project in the memory."""
        self.projects[name] = {
            "path": path,
            "description": description,
            "language": language,
            "created": time.time(),
            "last_modified": time.time(),
            "commit_count": 0,
            "test_pass": None,
        }
        self.state["last_active_project"] = name
        self._save_json(self.projects_file, self.projects)
        self._save_state()
        logging.info(f"MEMORY: Registered project '{name}' at {path}")

    def update_project(self, name, **kwargs):
        """Update project metadata."""
        if name in self.projects:
            self.projects[name].update(kwargs)
            self.projects[name]["last_modified"] = time.time()
            self._save_json(self.projects_file, self.projects)

    def get_project(self, name):
        """Get project info by name."""
        return self.projects.get(name)

    def get_all_projects(self):
        """Get all registered projects."""
        return self.projects

    def get_active_project(self):
        """Get the last active project name."""
        return self.state.get("last_active_project")

    # --- Patterns (learned behaviors) ---

    def record_success(self, goal_description, approach):
        """Record a successful approach for future reference."""
        self.patterns["successful_patterns"].append({
            "goal": goal_description,
            "approach": approach,
            "timestamp": time.time(),
        })
        # Keep only last 100 patterns
        self.patterns["successful_patterns"] = self.patterns["successful_patterns"][-100:]
        self._save_json(self.patterns_file, self.patterns)
        self.state["total_goals_completed"] += 1
        self._save_state()

    def record_failure(self, goal_description, approach, error):
        """Record a failed approach to avoid repeating."""
        self.patterns["failed_patterns"].append({
            "goal": goal_description,
            "approach": approach,
            "error": str(error)[:500],
            "timestamp": time.time(),
        })
        self.patterns["failed_patterns"] = self.patterns["failed_patterns"][-100:]
        self._save_json(self.patterns_file, self.patterns)
        self.state["total_goals_failed"] += 1
        self._save_state()

    def get_successful_patterns(self):
        """Get recorded successful patterns."""
        return self.patterns.get("successful_patterns", [])

    def get_failed_patterns(self):
        """Get recorded failed patterns."""
        return self.patterns.get("failed_patterns", [])

    # --- Context for LLM ---

    def get_context_summary(self):
        """
        Generate a summary string suitable for including in LLM context.
        Provides the agent with awareness of past work.
        """
        lines = []
        lines.append(f"Boot #{self.state['boot_count']}")
        lines.append(f"Goals completed: {self.state['total_goals_completed']}")
        lines.append(f"Goals failed: {self.state['total_goals_failed']}")
        lines.append(f"Commands executed: {self.state['total_commands_executed']}")

        if self.projects:
            lines.append(f"Projects: {', '.join(self.projects.keys())}")

        active = self.get_active_project()
        if active:
            lines.append(f"Last active: {active}")

        recent = self.get_recent_history(5)
        if recent:
            lines.append("Recent actions:")
            for entry in recent:
                status = "OK" if entry.get("success") else "FAIL"
                lines.append(f"  [{status}] {entry.get('type', '?')}: {str(entry.get('details', ''))[:80]}")

        return '\n'.join(lines)
