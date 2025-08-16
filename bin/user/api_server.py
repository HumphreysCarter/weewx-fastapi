# Carter Humphreys
# https://github.com/HumphreysCarter/weewx-fastapi

import json
import logging
import requests
import uvicorn
import threading
from pathlib import Path
from weewx.engine import StdService
from fastapi import FastAPI

from .api_router import data_router

log = logging.getLogger(__name__)


def download_prism_normals(config_dict):
    weewx_config_path = Path(config_dict.get('config_path'))
    normals_path = weewx_config_path.parent / 'archive' / 'prism_daily_normals.json'

    # Download data if the file doesn't exist
    if not normals_path.is_file():
        prism_api_url = 'https://www.prism.oregonstate.edu/explorer/dataexplorer/rpc.php'

        # Get the station latitude and longitude
        latitude = config_dict.get('Station', {}).get('latitude', None)
        longitude = config_dict.get('Station', {}).get('longitude', None)

        # Create the request payload
        payload = {
            'spares': '800m',
            'interp': 'idw',
            'stats': 'ppt tmin tmean tmax',
            'units': 'eng',
            'range': 'daily_normals',
            'stability': 'stable',
            'lon': longitude,
            'lat': latitude,
            'call': 'pp/daily_normals_timeseries',
            'proc': 'gridserv',
        }

        # Request headers
        headers = {'User-Agent': 'https://github.com/HumphreysCarter/weewx-fastapi'}

        # Make data request
        try:
            resp = requests.post(prism_api_url, data=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            try:
                data = resp.json()
                with open(normals_path, 'w') as f:
                    json.dump(data, f, indent=4)
                log.info('PRISM normals downloaded and saved to file')
            except ValueError:
                log.warning(f'PRISM normals download failed: invalid JSON: {resp.text}')
        except requests.HTTPError as e:
            log.error(f'PRISM normals download failed: {e}')
        except requests.RequestException as e:
            log.error(f'Failed to request PRISM normals: {e}')


class DataAPI(StdService):
    def __init__(self, engine, config_dict):
        super().__init__(engine, config_dict)

        # Check if the server is enabled in config
        server_enabled = config_dict.get('DataAPI', {}).get('enable', 'True').upper() == 'TRUE'

        # Check if PRISM normals are enabled in config
        normals_enabled = config_dict.get('DataAPI', {}).get('prism_normals', 'True').upper() == 'TRUE'
        if normals_enabled :
            # Ensure PRISM normals are downloaded
            download_prism_normals(config_dict)

        # Start the server thread
        if server_enabled:
            self._thread = ApiServerThread(config_dict)
            self._thread.start()
            log.info('DataAPI: API server thread started')
        else:
            self._thread = None
            log.info('DataAPI: API server is disabled')

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
                    'name': 'Normals',
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