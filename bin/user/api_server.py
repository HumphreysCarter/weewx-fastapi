# Carter Humphreys
# https://github.com/HumphreysCarter/weewx-fastapi

import json
import math
import logging
import uvicorn
import calendar
import requests
import threading
from pathlib import Path
from weewx.engine import StdService
from fastapi import FastAPI
from statistics import mean

from .api_router import data_router

log = logging.getLogger(__name__)


def prism_compute_annual_norms(daily_normals):
    precip_total = math.fsum(daily_normals['ppt'])
    max_temp = max(daily_normals['tmax'])
    min_temp = min(daily_normals['tmin'])
    mean_temp = mean(daily_normals['tmean'])

    return {
        'precip_total': precip_total,
        'temp_max': max_temp,
        'temp_avg': mean_temp,
        'temp_min': min_temp
    }

def prism_process_daily_norms(daily_normals):
    # Key rename mapping
    key_map = {
        'ppt': 'precip_total',
        'tmax': 'temp_max',
        'tmean': 'temp_avg',
        'tmin': 'temp_min'
    }

    # Build julian_day -> (month, day)
    jd_to_md = {}
    day_counter = 1
    for month in range(1, 13):
        days_in_month = 29 if month == 2 else calendar.monthrange(2000, month)[1]
        for day in range(1, days_in_month + 1):
            jd_to_md[day_counter] = (month, day)
            day_counter += 1

    # Month names as outer keys
    monthly_normals = {calendar.month_name[m].lower(): {} for m in range(1, 13)}

    # Fill values
    for key, values in daily_normals.items():
        new_key = key_map.get(key, key)
        for jd, value in enumerate(values, start=1):
            month, day = jd_to_md[jd]
            month_name = calendar.month_name[month].lower()
            if new_key not in monthly_normals[month_name]:
                monthly_normals[month_name][new_key] = {}
            monthly_normals[month_name][new_key][day] = value

    return monthly_normals

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
                prism_data = resp.json()
                if 'result' in prism_data and 'data' in prism_data['result']:
                    # Process data
                    daily_dict = prism_process_daily_norms(prism_data['result']['data'])
                    annual_dict = prism_compute_annual_norms(prism_data['result']['data'])

                    # Create norms dict for JSON file
                    norms_dict = {'annual_norms': annual_dict, 'daily_normals': daily_dict}
                    with open(normals_path, 'w') as f:
                        json.dump(norms_dict, f, indent=4)

                    log.info('PRISM normals downloaded and saved to file')
                else:
                    log.warning(f'PRISM normals data parse failed: missing data: {resp.text}')
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