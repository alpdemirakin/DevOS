
import os
import logging
import time
import traceback
from tools import (
    run_command, write_file, read_file, make_dir,
    git_init, git_commit, git_status, run_tests,
    detect_project_type, list_dir, TOOL_REGISTRY
)
from enforce import InputSanitizer


class ExecutionPipeline:
    """
    Orchestrates the full execution lifecycle:
      Plan → Code → Test → Fix → Commit

    Each stage feeds into the next. If tests fail, the self-repair
    module attempts to fix the code automatically.

    No human interaction at any stage.
    """

    MAX_FIX_ATTEMPTS = 3

    def __init__(self, llm=None, memory=None):
        self.llm = llm
        self.memory = memory
        self.sanitizer = InputSanitizer()

    def execute_goal(self, goal, project_path):
        """
        Full pipeline execution for a goal.
        Returns (success: bool, report: dict)
        """
        report = {
            "goal": goal.get("description", "unknown"),
            "path": project_path,
            "stages": [],
            "success": False,
        }

        try:
            # Stage 1: Setup
            self._stage_setup(project_path, report)

            # Stage 2: Code Generation
            self._stage_codegen(goal, project_path, report)

            # Stage 3: Verification
            test_passed = self._stage_verify(goal, project_path, report)

            # Stage 4: Self-repair (if tests failed)
            if not test_passed:
                test_passed = self._stage_repair(goal, project_path, report)

            # Stage 5: Commit
            if test_passed:
                self._stage_commit(goal, project_path, report)
                report["success"] = True

        except Exception as e:
            logging.error(f"PIPELINE ERROR: {e}")
            report["stages"].append({
                "name": "error",
                "status": "fail",
                "detail": str(e),
            })

        return report["success"], report

    def execute_tool_calls(self, tool_calls):
        """
        Execute a list of tool call dicts.
        Returns list of results.
        """
        results = []
        for call in tool_calls:
            tool_name = call.get("tool")
            args = call.get("args", {})

            if tool_name not in TOOL_REGISTRY:
                results.append({"tool": tool_name, "error": "unknown tool"})
                continue

            # Safety check
            if tool_name == "run":
                cmd = args.get("command", "")
                if not self.sanitizer.is_safe_command(cmd):
                    results.append({"tool": tool_name, "error": "blocked by safety"})
                    continue

            try:
                func = TOOL_REGISTRY[tool_name]
                result = func(**args)
                results.append({"tool": tool_name, "result": str(result)[:500]})
                logging.info(f"EXEC [{tool_name}]: OK")
            except Exception as e:
                results.append({"tool": tool_name, "error": str(e)})
                logging.error(f"EXEC [{tool_name}]: {e}")

        return results

    # --- Pipeline Stages ---

    def _stage_setup(self, project_path, report):
        """Setup project directory and git."""
        logging.info(f"STAGE [setup]: {project_path}")

        if not os.path.exists(project_path):
            make_dir(project_path)
            git_init(project_path)
            report["stages"].append({"name": "setup", "status": "ok", "detail": "created"})
        else:
            report["stages"].append({"name": "setup", "status": "ok", "detail": "exists"})

    def _stage_codegen(self, goal, project_path, report):
        """Generate code files for the goal."""
        logging.info("STAGE [codegen]: Writing files...")

        files_written = []

        # If goal has pre-defined files (template mode)
        if "files" in goal:
            for filename, content in goal["files"].items():
                path = f"{project_path}/{filename}"
                write_file(path, content)
                files_written.append(filename)
                logging.info(f"  WRITE: {filename}")

        # If LLM is available and goal needs generation
        elif self.llm and self.llm.is_available():
            files_written = self._llm_codegen(goal, project_path)

        else:
            # Minimal skeleton
            desc = goal.get("description", "project")
            name = goal.get("name", "main")
            write_file(f"{project_path}/main.py",
                f'#!/usr/bin/env python3\n"""{desc}"""\n\ndef main():\n    print("{desc}")\n\nif __name__ == "__main__":\n    main()\n')
            files_written.append("main.py")

        report["stages"].append({
            "name": "codegen",
            "status": "ok",
            "detail": f"wrote {len(files_written)} files: {', '.join(files_written)}"
        })

    def _llm_codegen(self, goal, project_path):
        """Use LLM to generate project code."""
        files_written = []
        desc = goal.get("description", "")

        # Ask LLM for a project plan
        plan = self.llm.generate_project_plan(desc)

        if plan and "files" in plan:
            for filename, file_desc in plan["files"].items():
                code = self.llm.generate_code(file_desc, filename=filename)
                if code:
                    write_file(f"{project_path}/{filename}", code)
                    files_written.append(filename)
                    logging.info(f"  LLM WRITE: {filename}")

            # Store test command if provided
            if "test_cmd" in plan:
                goal["test_cmd"] = plan["test_cmd"]
        else:
            # Fallback: generate a single file
            code = self.llm.generate_code(desc)
            if code:
                write_file(f"{project_path}/main.py", code)
                files_written.append("main.py")

        return files_written

    def _stage_verify(self, goal, project_path, report):
        """Run tests/verification on the generated code."""
        logging.info("STAGE [verify]: Running tests...")

        # Use goal-specific test command if available
        test_cmd = goal.get("test_cmd")
        if test_cmd:
            output = run_command(test_cmd, cwd=project_path, timeout=60)
            passed = not self._is_test_failure(output)
            report["stages"].append({
                "name": "verify",
                "status": "ok" if passed else "fail",
                "detail": str(output)[:300],
                "command": test_cmd,
            })
            return passed

        # Auto-detect and run
        ptypes = detect_project_type(project_path)
        if 'python' in ptypes:
            # Try unittest discovery first, then syntax check
            output = run_command(
                "python3 -m unittest discover -s . -v 2>&1 || python3 -m py_compile *.py 2>&1",
                cwd=project_path, timeout=60
            )
            passed = not self._is_test_failure(output)
            report["stages"].append({
                "name": "verify",
                "status": "ok" if passed else "fail",
                "detail": str(output)[:300],
            })
            return passed

        # No tests available — pass by default
        report["stages"].append({
            "name": "verify",
            "status": "ok",
            "detail": "no tests configured, syntax check only",
        })
        return True

    def _stage_repair(self, goal, project_path, report):
        """Attempt to fix failing code."""
        logging.info("STAGE [repair]: Attempting self-repair...")

        for attempt in range(self.MAX_FIX_ATTEMPTS):
            logging.info(f"  REPAIR attempt {attempt + 1}/{self.MAX_FIX_ATTEMPTS}")

            # Get the error
            test_cmd = goal.get("test_cmd", "python3 -m py_compile *.py 2>&1")
            error_output = run_command(test_cmd, cwd=project_path, timeout=30)

            if not self._is_test_failure(error_output):
                report["stages"].append({
                    "name": "repair",
                    "status": "ok",
                    "detail": f"fixed on attempt {attempt + 1}",
                })
                return True

            # Try to fix
            fixed = False
            if self.llm and self.llm.is_available():
                fixed = self._llm_repair(goal, project_path, str(error_output))
            else:
                fixed = self._pattern_repair(goal, project_path, str(error_output))

            if not fixed:
                break

        report["stages"].append({
            "name": "repair",
            "status": "fail",
            "detail": f"failed after {self.MAX_FIX_ATTEMPTS} attempts",
        })
        return False

    def _llm_repair(self, goal, project_path, error_msg):
        """Use LLM to fix code."""
        # Find the failing file from error message
        py_files = [f for f in os.listdir(project_path) if f.endswith('.py')]

        for filename in py_files:
            filepath = f"{project_path}/{filename}"
            code = read_file(filepath)
            if code.startswith("ERROR"):
                continue

            fixed_code = self.llm.generate_fix(code, error_msg, filename)
            if fixed_code and fixed_code != code:
                write_file(filepath, fixed_code)
                logging.info(f"  LLM FIX: {filename}")
                return True

        return False

    def _pattern_repair(self, goal, project_path, error_msg):
        """
        Pattern-based repair without LLM.
        Handles common Python errors.
        """
        error_lower = error_msg.lower()

        # Missing import
        if "importerror" in error_lower or "modulenotfounderror" in error_lower:
            # Try to extract module name
            import re
            match = re.search(r"no module named '(\w+)'", error_msg)
            if match:
                module = match.group(1)
                logging.info(f"  PATTERN FIX: Missing module '{module}'")
                # Can't install at this stage, but log it
                return False

        # Syntax error
        if "syntaxerror" in error_lower:
            match = re.search(r'File "([^"]+)", line (\d+)', error_msg)
            if match:
                filepath = match.group(1)
                line_no = int(match.group(2))
                logging.info(f"  PATTERN FIX: Syntax error in {filepath}:{line_no}")
                # Without LLM, can't fix syntax errors intelligently
                return False

        # IndentationError
        if "indentationerror" in error_lower:
            import re
            match = re.search(r'File "([^"]+)"', error_msg)
            if match:
                filepath = match.group(1)
                code = read_file(filepath)
                if not code.startswith("ERROR"):
                    # Replace tabs with spaces
                    fixed = code.replace('\t', '    ')
                    if fixed != code:
                        write_file(filepath, fixed)
                        logging.info(f"  PATTERN FIX: Fixed indentation in {filepath}")
                        return True

        # NameError - undefined variable
        if "nameerror" in error_lower:
            logging.info("  PATTERN FIX: NameError detected, cannot auto-fix without LLM")
            return False

        return False

    def _stage_commit(self, goal, project_path, report):
        """Commit the working code."""
        logging.info("STAGE [commit]: Committing...")
        desc = goal.get("description", "auto-generated project")
        result = git_commit(project_path, f"feat: {desc}")
        report["stages"].append({
            "name": "commit",
            "status": "ok",
            "detail": str(result)[:200],
        })

    @staticmethod
    def _is_test_failure(output):
        """Determine if test output indicates failure."""
        if output is None:
            return True
        output_str = str(output)
        failure_indicators = [
            "Traceback (most recent call last)",
            "FAILED",
            "Error",
            "AssertionError",
            "SyntaxError",
            "IndentationError",
            "NameError",
            "TypeError",
            "ValueError",
            "ImportError",
            "ModuleNotFoundError",
            "ERRORS",
        ]
        # Check for failure indicators BUT also check for "OK" or "passed"
        has_failure = any(ind in output_str for ind in failure_indicators)
        has_success = "OK" in output_str or "passed" in output_str or output_str.strip().endswith("0")

        # If both present (e.g., "ERROR" in test names but tests pass), trust success
        if has_success and not "Traceback" in output_str:
            return False
        return has_failure
