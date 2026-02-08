
print("DEVOS KERNEL LOADING...", flush=True)

import os
import sys
import logging
import traceback
import time

# Ensure ai/core is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autonomous import AutonomousAgent

# Configure logging to stdout - execution logs only, no chat
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    force=True
)

# Also log to file for persistence
try:
    os.makedirs("/logs", exist_ok=True)
    file_handler = logging.FileHandler("/logs/devos.log")
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logging.getLogger().addHandler(file_handler)
except Exception:
    pass  # File logging optional


def detect_mode():
    """
    Detect operating mode based on environment.
    - If stdin is a TTY (terminal attached): hybrid mode (accepts input + autonomous)
    - If stdin is not a TTY (piped/no terminal): autonomous mode only
    - Can be overridden with DEVOS_MODE env var
    """
    env_mode = os.environ.get("DEVOS_MODE", "").lower()
    if env_mode in ("operator", "autonomous", "hybrid"):
        return env_mode

    try:
        if os.isatty(sys.stdin.fileno()):
            return "hybrid"
    except Exception:
        pass

    return "autonomous"


def main():
    print("\n", flush=True)
    print("==================================================", flush=True)
    print("  DEVOS — AUTONOMOUS DEVELOPER OPERATING SYSTEM   ", flush=True)
    print("==================================================", flush=True)
    print("", flush=True)

    logging.info("Kernel connected.")
    logging.info("Initializing subsystems...")

    # Detect mode
    mode = detect_mode()
    logging.info(f"Mode: {mode}")

    # System checks
    logging.info("Python: " + sys.version.split()[0])
    logging.info("PID: " + str(os.getpid()))

    # Initialize agent
    agent = AutonomousAgent(mode=mode)

    logging.info("All systems nominal.")

    if mode == "hybrid":
        logging.info("Hybrid mode: type commands or wait for autonomous execution.")
    elif mode == "operator":
        logging.info("Operator mode: awaiting commands.")
    else:
        logging.info("Autonomous mode: no interaction required.")

    print("--------------------------------------------------", flush=True)

    # Main loop with crash recovery
    while True:
        try:
            agent.start_loop()
        except KeyboardInterrupt:
            logging.info("Shutdown signal received.")
            break
        except Exception as e:
            logging.error(f"Critical failure: {e}")
            traceback.print_exc()
            logging.info("Restarting in 5 seconds...")
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}", flush=True)
        traceback.print_exc()
        # Drop to shell on fatal error (if available)
        print("System halted. Press Ctrl+C or reboot.", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
