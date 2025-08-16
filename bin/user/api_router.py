# Carter Humphreys
# https://github.com/HumphreysCarter/weewx-fastapi

import json
import math
import sqlite3
import weewx.units
from pathlib import Path
from statistics import mean
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query


def load_prism_normals(path_to_json):
    try:
        with open(path_to_json, 'r') as file:
            prism_normals = json.load(file)
    except FileNotFoundError:
        return None

    return prism_normals


def build_where_clause(ts_start=None, ts_end=None, start_inclusive=True, end_inclusive=True):
    if start_inclusive:
        start_clause = '>='
    else:
        start_clause = '>'
    if end_inclusive:
        end_clause = '<='
    else:
        end_clause = '<'

    if ts_start and ts_end:
        return f'WHERE dateTime BETWEEN {ts_start} AND {ts_end}'
    elif ts_start:
        return f'WHERE dateTime {start_clause} {ts_start}'
    elif ts_end:
        return f'WHERE dateTime {end_clause} {ts_end}'

    return ''


def get_db_connection(db_path):
    connection = sqlite3.connect(db_path)
    return connection


def get_db_columns(db_path):
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute('PRAGMA table_info(archive)')
        db_columns = cur.fetchall()

    db_columns = [{'name': column[1], 'type': column[2]} for column in db_columns]

    return db_columns


def get_db_data(db_path, var, ts_start=None, ts_end=None, latest=False):
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        if latest:
            cur.execute(f'SELECT dateTime,{var} FROM archive ORDER BY dateTime DESC LIMIT 1')
        else:
            where_clause = build_where_clause(ts_start, ts_end)
            cur.execute(f'SELECT dateTime,{var} FROM archive {where_clause}')

        return cur.fetchall()


def get_var_stats(db_path, var, ts_start=None, ts_end=None):
    # Build the where clause
    where_clause = build_where_clause(ts_start, ts_end)

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()

        cur.execute(f'SELECT MIN({var}), MAX({var}), AVG({var}), SUM({var}), COUNT({var}) FROM archive {where_clause}')
        min, max, svg, sum, count = cur.fetchone()

        return {'min': min, 'max': max, 'avg': svg, 'sum': sum, 'count': count}


def aggregate_db_data(db_path, var, ts_start=None, ts_end=None, aggregate_func='AVG', bin_size=3600):
    # Build the where clause
    where_clause = build_where_clause(ts_start, ts_end)

    # Check bin_size
    if bin_size <= 0:
        raise ValueError('bin_size must be greater than 0')

    # Check function
    aggregate_func = aggregate_func.upper()
    if aggregate_func not in ['AVG', 'MIN', 'MAX']:
        raise ValueError('aggregate_func must be one of AVG, MIN, MAX')

    # Get aggregated data from the database
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT dateTime,{aggregate_func}({var}) FROM archive {where_clause} GROUP BY dateTime/{bin_size}')
        return cur.fetchall()


def data_router(config_dict: dict):
    router = APIRouter()

    # Find the weewx database path
    weewx_config_path = Path(config_dict.get('config_path'))
    weewx_db_path = weewx_config_path.parent / 'archive' / 'weewx.sdb'

    @router.get(
        '/station',
        summary = 'Station metadata',
        description = 'Retrieves all metadata associated with the weather station.',
        tags = ['Station Metadata'],
    )
    def station_metadata():
        return config_dict.get('Station', {})

    @router.get(
        '/station/name',
        summary = 'Station name',
        description = 'Retrieves the name of the weather station.',
        tags = ['Station Metadata'],
    )
    def station_name():
        return config_dict.get('Station', {}).get('location', '')

    @router.get(
        '/station/location',
        summary = 'Station location',
        description = 'Retrieves the latitude and longitude of the weather station.',
        tags = ['Station Metadata'],
    )
    def station_location():
        latitude = config_dict.get('Station', {}).get('latitude', None)
        longitude = config_dict.get('Station', {}).get('longitude', None)
        return latitude, longitude

    @router.get(
        '/station/elevation',
        summary = 'Station elevation',
        description = 'Retrieves the elevation of the weather station.',
        tags = ['Station Metadata'],
    )
    def station_elevation():
        return config_dict.get('Station', {}).get('altitude', '')

    @router.get(
        '/station/type',
        summary = 'Station type',
        description = 'Retrieves the type of hardware for the weather station.',
        tags = ['Station Metadata'],
    )
    def station_type():
        return config_dict.get('Station', {}).get('station_type', '')

    @router.get(
        '/database/por',
        summary = 'Period of record',
        description = 'Retrieves the period of record for the Database.',
        tags = ['Database'],
    )
    def get_period_of_record():
        # Get the stats for the datetime
        datetime_stats = get_var_stats(weewx_db_path, 'dateTime')

        # Convert from timestamps to ISO format
        datetime_min = datetime.fromtimestamp(datetime_stats['min'])
        datetime_max = datetime.fromtimestamp(datetime_stats['max'])

        # Calculate the number of days and years
        num_days = (datetime_max - datetime_min).days
        num_years = round(num_days / 365.25, 1)

        # Create the period of record dict
        por = {'start': datetime_min.isoformat(), 'end': datetime_max.isoformat(), 'num_days': num_days,
               'num_years': num_years}

        return por

    @router.get(
        '/database/obs_types',
        summary = 'List observation types',
        description = 'Retrieves a list of all available observation types in the database.',
        tags = ['Database'],
    )
    def get_var_list():
        # Get the list of variables
        db_var_list = get_db_columns(weewx_db_path)

        # Keep only the variable names
        db_var_list = [var['name'] for var in db_var_list]

        return db_var_list

    @router.get(
        '/database/{obs_type}/data',
        summary = 'Get data for observation type',
        description = 'Retrieves a list of all data associated with a given observation type from the database.',
        tags = ['Database'],
    )
    def get_all_data(obs_type: str, start: int = None, end: int = None):

        if start is not None:
            start = datetime.strptime(str(start), '%Y%m%d%H%M')
            ts_start = int(start.timestamp())
        else:
            ts_start = None

        if end is not None:
            end = datetime.strptime(str(end), '%Y%m%d%H%M')
            ts_end = int(end.timestamp())
        else:
            ts_end = None

        # Get the data
        data = get_db_data(weewx_db_path, obs_type, ts_start=ts_start, ts_end=ts_end)

        return data

    @router.get(
        '/database/{obs_type}/data/latest',
        summary = 'Get latest observation for observation type',
        description = 'Retrieves the latest record in the database for a given observation type.',
        tags = ['Database'],
    )
    def get_latest_ob(obs_type: str):
        try:
            # Get the latest value
            latest_ob = get_db_data(weewx_db_path, obs_type, latest=True)

            if latest_ob is not None and len(latest_ob) > 0:
                ts, value = latest_ob[0]
                return {'timestamp': ts, 'value': value}

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return None

    @router.get(
        '/database/{obs_type}/data/aggregate',
        summary = 'Aggregate data for observation type',
        description = 'Retrieves an aggregated list of data from the database for a given observation type.',
        tags = ['Database'],
    )
    def get_aggregated_data(obs_type: str, start: int = None, end: int = None, function: str = 'avg', hours: int = 1):

        if start is not None:
            start = datetime.strptime(str(start), '%Y%m%d%H%M')
            ts_start = int(start.timestamp())
        else:
            ts_start = None

        if end is not None:
            end = datetime.strptime(str(end), '%Y%m%d%H%M')
            ts_end = int(end.timestamp())
        else:
            ts_end = None

        # Get the data
        data = aggregate_db_data(weewx_db_path, obs_type, ts_start=ts_start, ts_end=ts_end, aggregate_func=function,
                                 bin_size=3600 * hours)

        return data

    @router.get(
        '/database/{obs_type}/data/stats',
        summary = 'Observation type statistics',
        description = 'Retrieves the statistics for a given observation type.',
        tags = ['Database'],
    )
    def get_stats(obs_type: str, start: int = None, end: int = None):

        if start is not None:
            start = datetime.strptime(str(start), '%Y%m%d%H%M')
            ts_start = int(start.timestamp())
        else:
            ts_start = None

        if end is not None:
            end = datetime.strptime(str(end), '%Y%m%d%H%M')
            ts_end = int(end.timestamp())
        else:
            ts_end = None

        # Get the data
        data = get_var_stats(weewx_db_path, obs_type, ts_start=ts_start, ts_end=ts_end)

        return data

    @router.get(
        '/database/{obs_type}/units',
        summary = 'Observation type units',
        description = 'Retrieves the units for a given observation type.',
        tags = ['Database'],
    )
    def get_var_units(obs_type: str):
        # Get the database unit system
        units_system_key = config_dict.get('StdConvert', {}).get('target_unit', weewx.US)

        units_map = {
            'US': weewx.US,
            'METRIC': weewx.METRIC,
            'METRICWX': weewx.METRICWX
        }

        units_system = units_map.get(units_system_key, weewx.US)

        # Get the units for the obs type
        unit, unit_group = weewx.units.getStandardUnitType(units_system, obs_type)

        return unit

    @router.get(
        '/database/{obs_type}/datatype',
        summary = 'Observation type data type',
        description = 'Retrieves the data type for a given observation type.',
        tags = ['Database'],
    )
    def get_var_dtype(obs_type: str):
        # Get the list of variables
        db_var_list = get_db_columns(weewx_db_path)

        for var in db_var_list:
            if var['name'] == obs_type:
                return var['type']

        return None

    # Check if PRISM normals are enabled in config
    normals_enabled = config_dict.get('DataAPI', {}).get('prism_normals', 'True').upper() == 'TRUE'
    normals_path = weewx_config_path.parent / 'archive' / 'prism_daily_normals.json'
    if normals_enabled and normals_path.is_file():

        # Load the PRISM normals
        prism_normals = load_prism_normals(normals_path)

        # Create regex for month validation
        VALID_MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'
        REGEX_PATTERN = rf'(?i)^({VALID_MONTHS})$'

        @router.get(
            '/normals/prism',
            summary = 'Get complete normals from PRISM',
            description = 'Retrieves the all normals for total precipitation and max, min, and average temperature derived from PRISM.',
            tags = ['Normals'],
        )
        def get_prism_normals():
            if prism_normals is None:
                return HTTPException(status_code=500, detail='No PRISM normals could be found for your location.')
            return prism_normals

        @router.get(
            '/normals/prism/annual',
            summary = 'Get annual normals from PRISM',
            description = 'Retrieves the annual normals for total precipitation and max, min, and average temperature derived from PRISM.',
            tags = ['Normals'],
        )
        def get_prism_normals_annual():
            if prism_normals is None:
                return HTTPException(status_code=500, detail='No PRISM normals could be found for your location.')
            return prism_normals['annual_norms']

        @router.get(
            '/normals/prism/monthly',
            summary='Get the normals for a month from PRISM',
            description='Retrieves the monthly normals for total precipitation and max, min, and average temperature derived from PRISM for a given month.',
            tags=['Normals'],
        )
        def get_prism_normals_monthly(month: str = Query(..., description='Month', pattern=REGEX_PATTERN)):
            if prism_normals is None:
                return HTTPException(status_code=500, detail='No PRISM normals could be found for your location.')

            try:
                resp_dict = {
                    'precip_total': math.fsum(prism_normals['daily_normals'][month.lower()]['precip_total'].values()),
                    'temp_max': max(prism_normals['daily_normals'][month.lower()]['temp_max'].values()),
                    'temp_avg': mean(prism_normals['daily_normals'][month.lower()]['temp_avg'].values()),
                    'temp_min': min(prism_normals['daily_normals'][month.lower()]['temp_min'].values()),
                }
                return resp_dict
            except KeyError:
                return HTTPException(status_code=404, detail=f'No normals found for {month}.')

        @router.get(
            '/normals/prism/monthly/current',
            summary='Get the normals for the current month from PRISM',
            description='Retrieves the monthly normals for total precipitation and max, min, and average temperature derived from PRISM for the currernt month.',
            tags=['Normals'],
        )
        def get_prism_normals_monthly_current():
            if prism_normals is None:
                return HTTPException(status_code=500, detail='No PRISM normals could be found for your location.')

            today_dt = datetime.today()
            month = today_dt.strftime('%B')

            try:
                resp_dict = {
                    'precip_total': math.fsum(prism_normals['daily_normals'][month.lower()]['precip_total'].values()),
                    'temp_max': max(prism_normals['daily_normals'][month.lower()]['temp_max'].values()),
                    'temp_avg': mean(prism_normals['daily_normals'][month.lower()]['temp_avg'].values()),
                    'temp_min': min(prism_normals['daily_normals'][month.lower()]['temp_min'].values()),
                }
                return resp_dict
            except KeyError:
                return HTTPException(status_code=404, detail=f'No normals found for {month}.')

        @router.get(
            '/normals/prism/daily',
            summary = 'Get the normals for a day from PRISM',
            description = 'Retrieves the daily normals for total precipitation and max, min, and average temperature derived from PRISM for a given month and day.',
            tags = ['Normals'],
        )
        def get_prism_normals_daily(month: str = Query(..., description='Month', pattern=REGEX_PATTERN),
                                    day: int = Query(..., ge=1, le=30, description='Day of the Month')
                                    ):
            if prism_normals is None:
                return HTTPException(status_code=500, detail='No PRISM normals could be found for your location.')

            try:
                resp_dict = {
                    'precip_total': prism_normals['daily_normals'][month.lower()]['precip_total'][str(day)],
                    'temp_max': prism_normals['daily_normals'][month.lower()]['temp_max'][str(day)],
                    'temp_avg': prism_normals['daily_normals'][month.lower()]['temp_avg'][str(day)],
                    'temp_min': prism_normals['daily_normals'][month.lower()]['temp_min'][str(day)],
                }
                return resp_dict
            except KeyError:
                return HTTPException(status_code=404, detail=f'No normals found for {month} {day}.')

        @router.get(
            '/normals/prism/daily/today',
            summary = 'Get the day normals for today from PRISM',
            description = 'Retrieves the daily normals for total precipitation and max, min, and average temperature derived from PRISM for the current day.',
            tags = ['Normals'],
        )
        def get_prism_normals_today():
            if prism_normals is None:
                return HTTPException(status_code=500, detail='No PRISM normals could be found for your location.')

            today_dt = datetime.today()
            month = today_dt.strftime('%B')
            day = str(today_dt.day)

            try:
                resp_dict = {
                    'precip_total': prism_normals['daily_normals'][month.lower()]['precip_total'][day],
                    'temp_max': prism_normals['daily_normals'][month.lower()]['temp_max'][day],
                    'temp_avg': prism_normals['daily_normals'][month.lower()]['temp_avg'][day],
                    'temp_min': prism_normals['daily_normals'][month.lower()]['temp_min'][day],
                }
                return resp_dict
            except KeyError:
                return HTTPException(status_code=404, detail=f'No normals found for {month} {day}.')

    return router
