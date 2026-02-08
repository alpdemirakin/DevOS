
import os
import logging
import json
import re

MODELS_DIR = "/ai/models"
SYSTEM_PROMPT_PATH = "/ai/core/system_prompt.txt"


class LLMEngine:
    """
    Local LLM inference engine.
    Supports: llama-cpp-python (GGUF models)
    Falls back to template-based generation when no model is available.

    No cloud. No API calls. Fully offline.
    """

    def __init__(self, model_path=None, n_ctx=2048, n_threads=4):
        self.model = None
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.system_prompt = self._load_system_prompt()
        self.available = False

        if model_path:
            self._load_model(model_path)
        else:
            self._auto_detect_model()

    def _load_system_prompt(self):
        """Load the system prompt that constrains LLM behavior."""
        try:
            if os.path.exists(SYSTEM_PROMPT_PATH):
                with open(SYSTEM_PROMPT_PATH) as f:
                    return f.read().strip()
        except Exception:
            pass
        return self._default_system_prompt()

    def _default_system_prompt(self):
        return """You are an autonomous code execution engine.
You receive a task description and output ONLY structured tool calls.
Output format: TOOL: <name> ARGS: <json>

Available tools:
- write: {"path": str, "content": str}
- run: {"command": str}
- read: {"path": str}
- mkdir: {"path": str}
- git_init: {"path": str}
- git_commit: {"path": str, "message": str}
- test: {"path": str}

Rules:
- NEVER output conversational text
- NEVER ask questions
- NEVER explain your reasoning
- Output ONLY tool calls, one per line
- If a task is ambiguous, make a decision and execute"""

    def _auto_detect_model(self):
        """Scan /ai/models/ for GGUF files."""
        if not os.path.exists(MODELS_DIR):
            logging.info("LLM: No models directory found.")
            return

        gguf_files = []
        for f in os.listdir(MODELS_DIR):
            if f.endswith('.gguf'):
                gguf_files.append(os.path.join(MODELS_DIR, f))

        if gguf_files:
            # Pick the first (or largest) model
            gguf_files.sort(key=lambda p: os.path.getsize(p), reverse=True)
            self._load_model(gguf_files[0])
        else:
            logging.info("LLM: No GGUF models found. Running in template mode.")

    def _load_model(self, path):
        """Load a GGUF model using llama-cpp-python."""
        if not os.path.exists(path):
            logging.error(f"LLM: Model file not found: {path}")
            return

        try:
            from llama_cpp import Llama
            logging.info(f"LLM: Loading model: {os.path.basename(path)}")
            logging.info(f"LLM: Context: {self.n_ctx}, Threads: {self.n_threads}")

            self.model = Llama(
                model_path=path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=0,  # CPU only for now
                verbose=False,
            )
            self.model_path = path
            self.available = True
            logging.info(f"LLM: Model loaded successfully.")
        except ImportError:
            logging.warning("LLM: llama-cpp-python not installed. Template mode only.")
        except Exception as e:
            logging.error(f"LLM: Failed to load model: {e}")

    def generate(self, prompt, max_tokens=1024, temperature=0.2, stop=None):
        """
        Generate completion from the LLM.
        Returns raw text output.
        """
        if not self.available or not self.model:
            return None

        stop = stop or ["\n\n\n", "USER:", "HUMAN:"]

        try:
            full_prompt = f"{self.system_prompt}\n\nTASK: {prompt}\n\nOUTPUT:\n"

            result = self.model(
                full_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop,
                echo=False,
            )

            text = result['choices'][0]['text'].strip()
            logging.info(f"LLM: Generated {len(text)} chars")
            return text

        except Exception as e:
            logging.error(f"LLM: Generation failed: {e}")
            return None

    def generate_tool_calls(self, task_description):
        """
        Generate a list of tool calls for a given task.
        Returns list of dicts: [{"tool": str, "args": dict}, ...]
        """
        raw = self.generate(task_description)
        if not raw:
            return []

        return self.parse_tool_calls(raw)

    def generate_code(self, description, language="python", filename="main.py"):
        """
        Generate code for a specific task.
        Returns the code as a string.
        """
        prompt = f"Write {language} code for: {description}\nFilename: {filename}\nOutput ONLY the code, no explanations."

        raw = self.generate(prompt, max_tokens=2048, temperature=0.3)
        if not raw:
            return None

        # Extract code from markdown blocks if present
        code = self._extract_code(raw)
        return code

    def generate_project_plan(self, description):
        """
        Generate a project plan: list of files and their purposes.
        Returns dict: {"files": {"filename": "description"}, "test_cmd": "..."}
        """
        prompt = f"""Plan a project: {description}
Output JSON only:
{{"files": {{"filename.py": "description"}}, "test_cmd": "command to run tests"}}"""

        raw = self.generate(prompt, max_tokens=512, temperature=0.2)
        if not raw:
            return None

        try:
            # Try to extract JSON
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

        return None

    def generate_fix(self, code, error_message, filename="main.py"):
        """
        Given code and an error, generate a fix.
        Returns fixed code string.
        """
        prompt = f"""Fix this {filename}:
```
{code[:2000]}
```

Error:
{error_message[:500]}

Output ONLY the fixed code, nothing else."""

        raw = self.generate(prompt, max_tokens=2048, temperature=0.1)
        if not raw:
            return None

        return self._extract_code(raw)

    @staticmethod
    def parse_tool_calls(text):
        """Parse TOOL: name ARGS: json lines into structured calls."""
        calls = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            match = re.match(r'TOOL:\s*(\w+)\s*ARGS:\s*(.*)', line)
            if match:
                tool_name = match.group(1)
                args_str = match.group(2).strip()
                try:
                    args = json.loads(args_str) if args_str else {}
                    calls.append({"tool": tool_name, "args": args})
                except json.JSONDecodeError:
                    logging.warning(f"LLM: Invalid args JSON: {args_str[:100]}")
        return calls

    @staticmethod
    def _extract_code(text):
        """Extract code from markdown code blocks or return raw text."""
        # Try ```python ... ``` or ``` ... ```
        match = re.search(r'```(?:python|py)?\s*\n(.*?)```', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # If no code block, return the raw text (might be just code)
        return text.strip()

    def is_available(self):
        """Check if LLM inference is available."""
        return self.available

    def info(self):
        """Get engine info."""
        return {
            "available": self.available,
            "model": os.path.basename(self.model_path) if self.model_path else None,
            "n_ctx": self.n_ctx,
            "n_threads": self.n_threads,
        }
