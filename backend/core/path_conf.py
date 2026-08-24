from pathlib import Path

# Project root directory (backend/)
BASE_PATH = Path(__file__).resolve().parent.parent

# Environment variable file
ENV_FILE_PATH = BASE_PATH / ".env"

# Environment variable example file
ENV_EXAMPLE_FILE_PATH = BASE_PATH / ".env.example"

# Log file path
LOG_DIR = BASE_PATH / "log"

# Internationalization Documentation Directory
LOCALE_DIR = BASE_PATH / "locale"
