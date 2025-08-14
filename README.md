> [!IMPORTANT]  
> This is still a work in progress — while mostly functional, it may produce unexpected results.

# WeeWX FastAPI Extension

A [WeeWX](https://weewx.com/) extension that provides a lightweight API interface using the [FastAPI](https://fastapi.tiangolo.com/) framework.

## Requirements

- Python **3.11** or later  
- WeeWX **v4** or later  
- FastAPI **0.116** or later


## Installation

1. **Install FastAPI**  
   ```bash
   $ pip install "fastapi[standard]"
   ```

2. **Install the extension** with `weectl extension`

   **WeeWX 5.0+**  
   ```bash
   $ weectl extension install https://github.com/HumphreysCarter/weewx-fastapi/releases/latest/download/weewx-fastapi.zip
   ```

   **WeeWX v4.0**  
   ```bash
   $ weectl extension --install https://github.com/HumphreysCarter/weewx-fastapi/releases/latest/download/weewx-fastapi.zip
   ```

3. **Restart WeeWX**


## Usage

The API server will run automatically whenever WeeWX is running. FastAPI will automatically produce interactive API documentation, which by default, it is available at:

- Swagger UI: **[http://localhost:8000/docs](http://localhost:8000/docs)**
- ReDoc: **[http://localhost:8000/redoc](http://localhost:8000/redoc)**

## Configuration

The host and port number where the server runs can be changed via the under the **`[DataAPI]`** section of the `weewx.conf` file. Additionally, the API server can be deactivated by setting `enabled` to False.

```ini
[DataAPI]
    enabled = True
    server_host = localhost
    server_port = 8000
```