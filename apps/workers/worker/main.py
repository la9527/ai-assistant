import os
import time


def main() -> None:
    log_level = os.getenv("WORKER_LOG_LEVEL", "INFO")
    provider = os.getenv("LOCAL_LLM_PROVIDER", "ollama")
    base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")

    print(f"[worker] started log_level={log_level} provider={provider} base_url={base_url}")

    while True:
        print("[worker] heartbeat")
        time.sleep(30)


if __name__ == "__main__":
    main()