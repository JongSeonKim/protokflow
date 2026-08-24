import uvicorn

if __name__ == "__main__":
    # Why create this startup file: https://stackoverflow.com/questions/64003384

    # DEBUG:
    # If you like to debug in the IDE, you can right-click to start this file in the IDE
    # If you like to debug through print, it is recommended to use the gsplay cli to start the service

    # Warning:
    # If you are starting this file through the python command, please follow the following matters:
    # 1. Install dependencies through uv according to the official documentation
    # 2. The command line space is located in the backend directory
    # For testing
    uvicorn.run(
        app="backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_excludes=["../.venv/**"],
    )
