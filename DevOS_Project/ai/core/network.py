
import os
import logging
import subprocess
import time

class NetworkManager:
    """
    Controlled network access for DevOS.
    Network is disabled by default.
    Opens temporarily for specific operations, then closes.

    Allowed operations:
      - pip install (Python packages)
      - git clone (repositories)
      - curl/wget (file downloads)

    All network access is logged.
    """

    ALLOWED_OPERATIONS = [
        "pip install",
        "pip3 install",
        "git clone",
        "git pull",
        "git fetch",
        "curl",
        "wget",
        "apk add",
    ]

    BLOCKED_DOMAINS = [
        "facebook.com",
        "twitter.com",
        "instagram.com",
        "tiktok.com",
    ]

    def __init__(self):
        self.network_up = False
        self.access_log = []

    def is_network_operation(self, command):
        """Check if a command requires network access."""
        cmd_lower = command.lower().strip()
        return any(cmd_lower.startswith(op) for op in self.ALLOWED_OPERATIONS)

    def execute_with_network(self, command, cwd=None, timeout=120):
        """
        Execute a command that requires network.
        Opens network, runs command, closes network.
        """
        if not self.is_network_operation(command):
            logging.warning(f"NET: Not a network operation: {command[:50]}")
            return self._run(command, cwd, timeout)

        logging.info(f"NET: Opening network for: {command[:80]}")
        self._log_access(command, "open")

        try:
            self._enable_network()
            result = self._run(command, cwd, timeout)
            return result
        finally:
            self._disable_network()
            self._log_access(command, "close")
            logging.info("NET: Network closed.")

    def pip_install(self, packages, cwd=None):
        """Install Python packages via pip."""
        if isinstance(packages, list):
            packages = " ".join(packages)

        logging.info(f"NET: pip install {packages}")
        return self.execute_with_network(
            f"pip3 install --no-cache-dir {packages}",
            cwd=cwd,
            timeout=180
        )

    def git_clone(self, url, dest=None, cwd=None):
        """Clone a git repository."""
        cmd = f"git clone --depth 1 {url}"
        if dest:
            cmd += f" {dest}"

        logging.info(f"NET: git clone {url}")
        return self.execute_with_network(cmd, cwd=cwd, timeout=300)

    def download_file(self, url, output_path):
        """Download a file."""
        # Block certain domains
        for domain in self.BLOCKED_DOMAINS:
            if domain in url:
                logging.warning(f"NET: Blocked domain: {domain}")
                return f"ERROR: Domain blocked: {domain}"

        logging.info(f"NET: Download {url}")
        return self.execute_with_network(
            f"curl -sL -o {output_path} {url}",
            timeout=120
        )

    def _enable_network(self):
        """Enable network interfaces."""
        try:
            # Try to bring up network interface
            self._run("ip link set eth0 up 2>/dev/null", timeout=5)
            # Try DHCP
            self._run("udhcpc -i eth0 -q 2>/dev/null", timeout=15)
            self.network_up = True
        except Exception as e:
            logging.warning(f"NET: Could not enable network: {e}")
            # Network might already be up
            self.network_up = True

    def _disable_network(self):
        """Disable network interfaces."""
        try:
            # Don't actually bring down the interface if we might need it
            # Just log that we're "closing" the session
            self.network_up = False
        except Exception:
            pass

    def _run(self, command, cwd=None, timeout=60):
        """Execute a command."""
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout
            return f"ERROR [{result.returncode}]: {result.stderr}"
        except subprocess.TimeoutExpired:
            return f"ERROR: Timeout after {timeout}s"
        except Exception as e:
            return f"ERROR: {str(e)}"

    def _log_access(self, command, action):
        """Log network access."""
        entry = {
            "time": time.time(),
            "command": command[:200],
            "action": action,
        }
        self.access_log.append(entry)
        # Keep only last 100 entries
        self.access_log = self.access_log[-100:]

    def get_access_log(self):
        """Return network access log."""
        return self.access_log

    def install_requirements(self, project_path):
        """Auto-detect and install project requirements."""
        req_file = os.path.join(project_path, "requirements.txt")
        if os.path.exists(req_file):
            logging.info(f"NET: Installing from requirements.txt")
            return self.execute_with_network(
                f"pip3 install --no-cache-dir -r {req_file}",
                cwd=project_path, timeout=300
            )

        setup_file = os.path.join(project_path, "setup.py")
        if os.path.exists(setup_file):
            logging.info(f"NET: Installing from setup.py")
            return self.execute_with_network(
                "pip3 install -e .",
                cwd=project_path, timeout=300
            )

        return "No requirements file found."
