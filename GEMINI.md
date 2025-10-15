# GEMINI.md

## Project Overview

This project, named CLP (CLI Proxy), is a local AI proxy tool built with Python. It's designed to manage and proxy API requests to AI services like Claude and Codex. The tool provides a command-line interface (CLI) for starting, stopping, and managing these proxy services, as well as a web-based UI for real-time monitoring and configuration.

The core of the project is a `BaseProxyService` that uses FastAPI to create a proxy server. This service intercepts requests, applies various filters and routing rules, and then forwards them to the appropriate AI service. It supports features like dynamic configuration switching, weighted load balancing, and detailed request/response logging.

The web UI is a Flask application that communicates with the proxy services through a set of REST APIs. It allows users to view the status of the services, manage configurations, inspect traffic logs, and analyze token usage.

### Main Technologies

*   **Python 3.7+**
*   **FastAPI**: For the asynchronous proxy services.
*   **Flask**: For the web UI.
*   **httpx**: As the asynchronous HTTP client for forwarding requests.
*   **uvicorn**: As the ASGI server for the FastAPI applications.
*   **psutil**: For process management.

### Architecture

The project is structured into several components:

*   **`src/main.py`**: The main entry point for the CLI, which handles command-line arguments and controls the proxy services.
*   **`src/core/base_proxy.py`**: The heart of the application, containing the core proxying logic, including request handling, filtering, load balancing, and logging.
*   **`src/claude/` and `src/codex/`**: Service-specific modules for the Claude and Codex proxies, respectively. They each have their own `ctl.py` for service control and `proxy.py` for the proxy implementation.
*   **`src/ui/ui_server.py`**: The Flask application for the web UI, which provides a REST API for the frontend.
*   **`src/config/config_manager.py`**: A class for managing the JSON configuration files for the services.
*   **`src/filter/`**: Modules for the different types of request filtering (endpoint, header, and request body).
*   **`src/auth/`**: Modules for authentication and authorization.
*   **`~/.clp/`**: The directory in the user's home folder where all configuration and data files are stored.

## Building and Running

### Installation

The project is packaged as a Python wheel. To install it, you can use pip:

```bash
pip install --force-reinstall ./dist/clp-1.11.0-py3-none-any.whl
```

It is recommended to use a virtual environment to avoid conflicts with other packages.

### Running the Application

The main command-line interface is `clp`. Here are the most common commands:

*   **`clp start`**: Start all proxy services (Claude, Codex, and UI).
*   **`clp stop`**: Stop all services.
*   **`clp restart`**: Restart all services.
*   **`clp status`**: Show the status of all services.
*   **`clp ui`**: Open the web UI in a browser.

The proxy services run on the following ports:

*   **Claude**: 3210
*   **Codex**: 3211
*   **Web UI**: 3300

### Testing

The project contains a `tests` directory with unit and integration tests. To run the tests, you can use `pytest`:

```bash
pytest
```

## Development Conventions

*   **Configuration:** All configuration is stored in JSON files in the `~/.clp/` directory. The web UI provides a convenient way to manage these files.
*   **Logging:** Request and response data is logged to `.jsonl` files in `~/.clp/data/`. The UI provides a log viewer to inspect this data.
*   **Dependencies:** Project dependencies are managed in the `pyproject.toml` file.
*   **Code Style:** The code follows standard Python conventions (PEP 8).
*   **Modularity:** The project is well-structured, with clear separation of concerns between the different components.
