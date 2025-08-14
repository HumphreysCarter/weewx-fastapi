> [!IMPORTANT]  
> This is still a work in progress and while mostly working, it may produce unexpected results.

# WeeWX FastAPI Extension
A [WeeWx](https://weewx.com/) extension to create a lightweight API interface to WeeWX using the [FastAPI](https://fastapi.tiangolo.com/) framework.

## Requirements

* Python 3.11 or later
* WeeWX version 4 or later
* FastAPI 0.116+

## Installation

The extension can be installed to WeeWx with `weectl extension` using either of the commands below, depending on your WeeWX version.

WeeWX v5:
```
$ source ~/weewx-venv/bin/activate
$ weectl extension install https://github.com/HumphreysCarter/weewx-fastapi/releases/latest/download/weewx-fastapi.zip
```

WeeWX v4:
```
$ weectl extension --install https://github.com/HumphreysCarter/weewx-fastapi/releases/latest/download/weewx-fastapi.zip
```

## Usage

The API server will run automatically whenever WeeWX is running, and by default will run on localhost at port 8000. FastAPI provides two sets of interactive API docs which can be found at http://localhost:8000/docs using [Swagger UI](https://github.com/swagger-api/swagger-ui) or http://localhost:8000/redoc using [ReDoc](https://github.com/Rebilly/ReDoc).

The server and port number can be configured in weewx.conf under the Data API section.

```
[DataAPI]
    server_host = localhost
    server_port = 8000
```