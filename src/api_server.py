# Carter Humphreys
# https://github.com/HumphreysCarter/weewx-fastapi

import uvicorn
import threading
import logging
from weewx.engine import StdService
from fastapi import FastAPI

from .api_router import data_router

log = logging.getLogger(__name__)


class DataAPI(StdService):
    def __init__(self, engine, config_dict):
        super().__init__(engine, config_dict)

        # Start the server thread
        self._thread = ApiServerThread(config_dict)
        self._thread.start()
        log.info('DataAPI: API server thread started')

    def shutdown(self):
        if getattr(self, '_thread', None):
            log.info('DataAPI: stopping API server thread...')
            self._thread.stop()
            self._thread.join(timeout=10)
            self._thread = None
            log.info('DataAPI: API server thread stopped')


class ApiServerThread(threading.Thread):
    def __init__(self, config_dict):
        super().__init__(name='ApiServerThread', daemon=True)
        self._server = None

        # Get API host and port from config
        self.host = config_dict.get('DataAPI', {}).get('server_host', 'localhost')
        self.port = int(config_dict.get('DataAPI', {}).get('server_port', 8000))

        # Build the FastAPI app instance for this thread
        self.app = FastAPI(
            title='WeeWX API',
            summary='An API interface to WeeWX.',
            version='0.1.0',
            openapi_tags=[
                {
                    'name': 'Database',
                    'description': ''
                },
                {
                    'name': 'Station Metadata',
                    'description': ''
                }
            ]
        )

        # Add the data router to the server
        self.app.include_router(data_router(config_dict))


    def run(self):
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level='info'
        )
        self._server = uvicorn.Server(config)
        self._server.run()

    def stop(self):
        if self._server is not None:
            self._server.should_exit = True