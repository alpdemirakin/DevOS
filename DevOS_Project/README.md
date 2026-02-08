
# DevOS — Autonomous Developer Operating System

**DevOS** is a specialized Linux distribution designed to house an autonomous AI software engineer.
Unlike traditional OSs that wait for user input, DevOS boots directly into a continuous development loop.

## Core Behavior

1. **Boot**: The system boots into a minimal environment.
2. **Init**: The `system/init` script launches the AI Core (`ai/core/main.py`) as PID 1.
3. **Loop**: The AI Core enters an infinite loop:
    - **Goal Generation**: Identifies a new tool or library to build (e.g., "JSON Parser", "HTTP Server").
    - **Plan**: Decomposes the goal into file operations.
    - **Execute**: Writes code, runs tests.
    - **Commit**: If successful, commits the work to a local git repository.
    - **Repeat**: Moves to the next goal.

## No User Interaction

- There is no shell prompt for the user.
- There is no login.
- The screen displays only the execution logs of the AI.
- Input is ignored.

## Building and Running

### 1. Build the ISO (Docker Required)

```powershell
.\run_docker_build.cmd
```

This will produce `output/devos.iso`.

### 2. Run in VirtualBox

1. Create a VM (Linux 64-bit).
2. Mount `output/devos.iso`.
3. Boot.
4. Watch the AI write code on the screen.

## Extending

To make the AI smarter (i.e., not just using mock goals):
1. Place a GGUF model in `ai/models/`.
2. Edit `ai/core/autonomous.py` to use `llama-cpp-python` to generate dynamic goals and code based on the `system_prompt.txt`.

## License

MIT - Use responsibly. The AI runs autonomously and modifies its own filesystem.
