
import re
import logging

class OutputEnforcer:
    """
    Enforces the 'No Chat' policy strictly.
    Filters out ALL conversational filler, greetings, explanations.
    Only allows through:
      - TOOL: protocol messages
      - Direct shell commands
      - Structured JSON action plans
      - Execution logs
    """

    CONVERSATIONAL_PATTERNS = [
        r"^(Here is|I have|I will|I've|I'd|Sure|Okay|Certainly|Of course|Absolutely)",
        r"^(Let's|Let me|To do this|First|Now|Next|Finally|In order to)",
        r"^(Great|Good|Nice|Perfect|Excellent|Wonderful|Amazing)",
        r"^(Hello|Hi|Hey|Greetings|Welcome)",
        r"^(Thank|Thanks|Please|Sorry|Apolog)",
        r"^(As you|As we|As I|You can|You may|You should|You might)",
        r"^(This (is|will|would|should|can|may))",
        r"^(It (is|will|would|should|seems|appears|looks))",
        r"^(Note|Remember|Keep in mind|Important|Please note)",
        r"^(Would you|Could you|Can I|Do you|Shall I|May I)",
        r".*Hope this helps.*",
        r".*Let me know.*",
        r".*feel free.*",
        r".*happy to help.*",
        r".*Can I help you with.*",
        r".*Is there anything.*",
        r".*don't hesitate.*",
        r".*Here's (what|how|a|an|the).*",
    ]

    VALID_PREFIXES = [
        "TOOL:",
        "EXEC:",
        "WRITE:",
        "READ:",
        "DELETE:",
        "MKDIR:",
        "GIT:",
        "TEST:",
        "BUILD:",
        "ERROR:",
        "OK:",
        "FAIL:",
        "LOG:",
        "ACTION:",
    ]

    def __init__(self):
        self._compiled = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in self.CONVERSATIONAL_PATTERNS
        ]

    def enforce(self, text):
        """
        Filter LLM output. Returns only actionable content.
        Returns None if the output is purely conversational.
        """
        if not text:
            return None

        text = text.strip()

        # Pass through TOOL: protocol
        if text.startswith("TOOL:"):
            return text

        # Pass through structured JSON
        if text.startswith("{") or text.startswith("["):
            try:
                import json
                json.loads(text)
                return text
            except (json.JSONDecodeError, ValueError):
                pass

        # Pass through valid prefixed output
        for prefix in self.VALID_PREFIXES:
            if text.startswith(prefix):
                return text

        # Filter conversational text line by line
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            is_chat = False
            for pattern in self._compiled:
                if pattern.match(stripped):
                    is_chat = True
                    break
            if not is_chat:
                clean_lines.append(line)

        if not clean_lines:
            return None

        result = '\n'.join(clean_lines).strip()
        return result if result else None

    def enforce_output_only(self, text):
        """
        Stricter mode: only allow TOOL: and structured output.
        Everything else is silenced.
        """
        if not text:
            return None
        text = text.strip()
        if text.startswith("TOOL:"):
            return text
        if text.startswith("{") or text.startswith("["):
            return text
        for prefix in self.VALID_PREFIXES:
            if text.startswith(prefix):
                return text
        return None


class InputSanitizer:
    """
    Validates and sanitizes operator input and command arguments.
    Blocks dangerous operations while allowing legitimate developer work.
    """

    # Commands that could destroy the system
    FORBIDDEN_PATTERNS = [
        r"rm\s+-rf\s+/\s*$",
        r"rm\s+-rf\s+/\*",
        r":\(\)\s*\{",                  # fork bomb
        r"dd\s+if=/dev/(zero|random|urandom)\s+of=/dev/sd",
        r"mkfs\.",
        r">\s*/dev/sd",
        r"mv\s+/\s",
        r"chmod\s+-R\s+777\s+/\s*$",
        r"wget.*\|\s*(ba)?sh",          # remote code execution via pipe
        r"curl.*\|\s*(ba)?sh",
        r"python3?\s+-c\s+.*import\s+os.*system.*rm",
    ]

    # Paths that should never be modified
    PROTECTED_PATHS = [
        "/init",
        "/ai/core/main.py",
        "/ai/core/enforce.py",
        "/ai/core/tools.py",
        "/ai/core/memory.py",
        "/ai/core/command_parser.py",
        "/ai/core/system_prompt.txt",
        "/bin/",
        "/sbin/",
        "/usr/bin/",
        "/usr/sbin/",
        "/proc/",
        "/sys/",
        "/dev/",
    ]

    def __init__(self):
        self._forbidden = [
            re.compile(p, re.IGNORECASE)
            for p in self.FORBIDDEN_PATTERNS
        ]

    def is_safe_command(self, command):
        """Check if a shell command is safe to execute."""
        for pattern in self._forbidden:
            if pattern.search(command):
                logging.warning(f"SECURITY: Blocked forbidden command: {command[:100]}")
                return False
        return True

    def is_safe_path(self, path, operation="read"):
        """Check if a file path is safe for the given operation."""
        if operation == "read":
            return True  # Reading is always allowed

        # Writing/deleting protected paths is forbidden
        for protected in self.PROTECTED_PATHS:
            if path.startswith(protected):
                logging.warning(f"SECURITY: Blocked {operation} on protected path: {path}")
                return False
        return True

    def sanitize_input(self, text):
        """
        Basic input sanitization.
        Removes control characters, limits length.
        """
        if not text:
            return ""
        # Remove control characters except newline
        clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        # Limit length
        return clean[:4096]
