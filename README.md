> [!IMPORTANT]  
> This is still a work in progress — while mostly functional, it may produce unexpected results.

# WeeWX FastAPI Extension

A [WeeWX](https://weewx.com/) extension that provides a lightweight API interface using the [FastAPI](https://fastapi.tiangolo.com/) framework.

## Requirements

- Python **3.11** or later  
- WeeWX **v4** or later  
- FastAPI **0.116.0** or later
- requests **2.32.0** or later


## Installation

1. **Install FastAPI and requests** packages
   ```bash
   $ pip install "fastapi[standard]" requests
   ```

2. **Install the extension** with `weectl extension`

   WeeWX 5.0+
   ```bash
   $ weectl extension install https://github.com/HumphreysCarter/weewx-fastapi/releases/latest/download/weewx-fastapi.zip
   ```

   WeeWX v4.0
   ```bash
   $ weectl extension --install https://github.com/HumphreysCarter/weewx-fastapi/releases/latest/download/weewx-fastapi.zip
   ```

3. **Restart WeeWX**


## Usage

The API server will run automatically whenever WeeWX is running via Uvicorn. FastAPI will automatically produce interactive API documentation, which by default, it is available at:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Configuration

The API server is configured via the `DataAPI` section of the `weewx.conf` file.

### Default Configuration
```ini
[DataAPI]
    enabled = True
    server_host = localhost
    server_port = 8000
    prism_normals = False
```

### Options
* Use the `enabled` option to either enable or disable the API server.
* The server host and port number can be set with the `server_host` and `server_port` settings. To enable all network interfaces, set `server_host` to `0.0.0.0`.
* 30-year normals for precipitation and temperature can also be retrieved for your location from the [PRISM Group](https://prism.oregonstate.edu/normals/) at Oregon State University by setting `prism_normals` to `True`. *This is only available for areas within the continental United States*.


