
Download GGUF model files and place them in this directory.
Get one from Hugging Face (e.g., specific for chat or code).
Ensure it is compatible with llama.cpp usage.

Recommend:
- CodeLlama-7B-v2.Q4_K_M.gguf
- TinyLlama-1.1B.Q4_K_M.gguf (for smaller memory/faster inference)

Update `ai/core/main.py` with the path to the chosen model if not using default.
