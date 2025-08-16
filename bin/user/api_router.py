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

# Create regex for month validation
VALID_MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'
REGEX_PATTERN = rf'(?i)^({VALID_MONTHS})$'


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


def get_var_daily_record(db_path, obs_type, month_name, day, func='max'):
    func = func.lower()
    if func not in {'max', 'min', 'sum'}:
        raise ValueError("func must be one of {'max','min','sum'}")

    if func == 'max':
        value_col, time_col, agg = 'max', 'maxTime', 'MAX'
    elif func == 'min':
        value_col, time_col, agg = 'min', 'minTime', 'MIN'
    else:  # func == 'sum'
        value_col, time_col, agg = 'sum', 'dateTime', 'MAX'

    # Parse month name → 'MM'
    try:
        mm = f"{datetime.strptime(month_name.strip(), '%B').month:02d}"
    except ValueError:
        raise ValueError('month_name must be a full month name')

    dd = f'{int(day):02d}'
    table = f'archive_day_{obs_type}'

    sql = f"""
    WITH mx AS (
      SELECT {agg}({value_col}) AS target_val
      FROM {table}
      WHERE strftime('%m', dateTime, 'unixepoch') = :mm
        AND strftime('%d', dateTime, 'unixepoch') = :dd
    )
    SELECT t.{value_col} AS val,
           GROUP_CONCAT(datetime(t.{time_col}, 'unixepoch')) AS times
    FROM {table} AS t
    JOIN mx ON t.{value_col} = mx.target_val
    WHERE strftime('%m', t.dateTime, 'unixepoch') = :mm
      AND strftime('%d', t.dateTime, 'unixepoch') = :dd
    GROUP BY t.{value_col};
    """

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(sql, {'mm': mm, 'dd': dd})
        row = cur.fetchone()

    if not row:
        return None

    value = row[0]
    times = row[1].split(',') if row[1] else []
    times = [datetime.strptime(dt, '%Y-%m-%d %H:%M:%S').isoformat() + 'Z' for dt in times]
    times.sort()
    return value, times


def get_var_monthly_record(db_path, obs_type, month_name, func='max'):
    func = func.lower()
    if func not in {'max', 'min', 'sum'}:
        raise ValueError("func must be one of {'max','min','sum'}")

    if func == 'max':
        value_col, time_col, agg = 'max', 'maxTime', 'MAX'
    elif func == 'min':
        value_col, time_col, agg = 'min', 'minTime', 'MIN'
    else:  # sum
        value_col, time_col, agg = 'sum', 'dateTime', 'MAX'

    try:
        mm = f"{datetime.strptime(month_name.strip(), '%B').month:02d}"
    except ValueError:
        raise ValueError('month_name must be a full month name')

    table = f'archive_day_{obs_type}'

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()

        if func in {'max', 'min'}:
            sql = f"""
            WITH per_year AS (
              SELECT
                strftime('%Y', dateTime, 'unixepoch') AS yr,
                {agg}({value_col}) AS target_val
              FROM {table}
              WHERE strftime('%m', dateTime, 'unixepoch') = :mm
              GROUP BY yr
            )
            SELECT
              t.{value_col} AS val,
              GROUP_CONCAT(datetime(t.{time_col}, 'unixepoch')) AS times
            FROM {table} AS t
            JOIN per_year AS py
              ON strftime('%Y', t.dateTime, 'unixepoch') = py.yr
             AND strftime('%m', t.dateTime, 'unixepoch') = :mm
             AND t.{value_col} = py.target_val
            GROUP BY t.{value_col};
            """
            cur.execute(sql, {'mm': mm})
            row = cur.fetchone()
            if not row:
                return None
            val = row[0]
            times = []
            if row[1]:
                for dt_str in row[1].split(','):
                    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                    times.append(dt.isoformat() + 'Z')
            times.sort()
            return val, times

        else:
            # SUM case

            # --- wettest year(s) ---
            sql_year = f"""
            WITH per_year AS (
              SELECT
                strftime('%Y', dateTime, 'unixepoch') AS yr,
                SUM({value_col}) AS total
              FROM {table}
              WHERE strftime('%m', dateTime, 'unixepoch') = :mm
              GROUP BY yr
            ),
            mx AS ( SELECT MAX(total) AS max_total FROM per_year )
            SELECT total, GROUP_CONCAT(yr) AS years
            FROM per_year, mx
            WHERE total = max_total
            GROUP BY total;
            """
            cur.execute(sql_year, {'mm': mm})
            row = cur.fetchone()
            if row:
                total = row[0]
                years = row[1].split(',') if row[1] else []
                years.sort()
                wettest_year = (total, years)
            else:
                wettest_year = None

            # --- wettest day(s) ---
            sql_day = f"""
            WITH mx AS (
              SELECT MAX({value_col}) AS max_day
              FROM {table}
              WHERE strftime('%m', dateTime, 'unixepoch') = :mm
            )
            SELECT t.{value_col} AS val,
                   GROUP_CONCAT(datetime(t.{time_col}, 'unixepoch')) AS times
            FROM {table} AS t
            JOIN mx ON t.{value_col} = mx.max_day
            WHERE strftime('%m', t.dateTime, 'unixepoch') = :mm
            GROUP BY t.{value_col};
            """
            cur.execute(sql_day, {'mm': mm})
            row = cur.fetchone()
            if row:
                val = row[0]
                times = []
                if row[1]:
                    for dt_str in row[1].split(','):
                        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                        times.append(dt.isoformat() + 'Z')
                times.sort()
                wettest_day = (val, times)
            else:
                wettest_day = None

            return wettest_year, wettest_day


def get_var_yearly_record(db_path, obs_type, year, func='max'):
    func = func.lower()
    if func not in {'max', 'min', 'sum'}:
        raise ValueError("func must be one of {'max','min','sum'}")

    if func == 'max':
        value_col, time_col, agg = 'max', 'maxTime', 'MAX'
    elif func == 'min':
        value_col, time_col, agg = 'min', 'minTime', 'MIN'
    else:  # sum case
        value_col, time_col, agg = 'sum', 'dateTime', 'SUM'

    table = f'archive_day_{obs_type}'
    yr = str(int(year))  # normalize

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        if func in {'max', 'min'}:
            # Get the extreme value for the year, then collect all tied times
            sql = f"""
            WITH mx AS (
              SELECT {('MAX' if func == 'max' else 'MIN')}({value_col}) AS target_val
              FROM {table}
              WHERE strftime('%Y', dateTime, 'unixepoch') = :yr
            )
            SELECT t.{value_col} AS val,
                   GROUP_CONCAT(datetime(t.{time_col}, 'unixepoch')) AS times
            FROM {table} AS t
            JOIN mx ON t.{value_col} = mx.target_val
            WHERE strftime('%Y', t.dateTime, 'unixepoch') = :yr
            GROUP BY t.{value_col};
            """
            cur.execute(sql, {'yr': yr})
            row = cur.fetchone()
            if not row:
                return None
            val = row[0]
            times = []
            if row[1]:
                for dt_str in row[1].split(','):
                    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                    times.append(dt.isoformat() + 'Z')
            times.sort()
            return val, times

        else:
            # SUM case: total over the year + greatest single-day sum in that year
            # 1) total for the year
            sql_total = f"""
            SELECT SUM({value_col}) AS total
            FROM {table}
            WHERE strftime('%Y', dateTime, 'unixepoch') = :yr;
            """
            cur.execute(sql_total, {'yr': yr})
            total_row = cur.fetchone()
            total = total_row[0] if total_row and total_row[0] is not None else None

            # 2) greatest single-day sum (with all tied dates)
            sql_day = f"""
            WITH mx AS (
              SELECT MAX({value_col}) AS max_day
              FROM {table}
              WHERE strftime('%Y', dateTime, 'unixepoch') = :yr
            )
            SELECT t.{value_col} AS val,
                   GROUP_CONCAT(datetime(t.{time_col}, 'unixepoch')) AS times
            FROM {table} AS t
            JOIN mx ON t.{value_col} = mx.max_day
            WHERE strftime('%Y', t.dateTime, 'unixepoch') = :yr
            GROUP BY t.{value_col};
            """
            cur.execute(sql_day, {'yr': yr})
            row = cur.fetchone()
            if row:
                max_daily_val = row[0]
                times = []
                if row[1]:
                    for dt_str in row[1].split(','):
                        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                        times.append(dt.isoformat() + 'Z')
                times.sort()
                wettest_day = (max_daily_val, times)
            else:
                wettest_day = None

            if total is None and wettest_day is None:
                return None

            return total, wettest_day


def get_var_alltime_record(db_path, obs_type, func='max'):
    func = func.lower()
    if func not in {'max', 'min', 'sum'}:
        raise ValueError("func must be one of {'max','min','sum'}")

    if func == 'max':
        value_col, time_col, agg = 'max', 'maxTime', 'MAX'
    elif func == 'min':
        value_col, time_col, agg = 'min', 'minTime', 'MIN'
    else:  # sum
        value_col, time_col, agg = 'sum', 'dateTime', 'SUM'

    table = f'archive_day_{obs_type}'

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        if func in {'max', 'min'}:
            sql = f"""
            WITH mx AS (SELECT {('MAX' if func == 'max' else 'MIN')}({value_col}) AS target_val FROM {table})
            SELECT t.{value_col} AS val,
                   GROUP_CONCAT(datetime(t.{time_col}, 'unixepoch')) AS times
            FROM {table} AS t
            JOIN mx ON t.{value_col} = mx.target_val
            GROUP BY t.{value_col};
            """
            cur.execute(sql)
            row = cur.fetchone()
            if not row:
                return None
            val = row[0]
            times = []
            if row[1]:
                for dt_str in row[1].split(','):
                    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                    times.append(dt.isoformat() + 'Z')
            times.sort()
            return val, times

        else:
            # total across all time
            sql_total = f"SELECT SUM({value_col}) FROM {table};"
            cur.execute(sql_total)
            total_row = cur.fetchone()
            total = total_row[0] if total_row and total_row[0] is not None else None

            # greatest single-day sum across all time (with tied dates at midnight)
            sql_day = f"""
            WITH mx AS (SELECT MAX({value_col}) AS max_day FROM {table})
            SELECT t.{value_col} AS val,
                   GROUP_CONCAT(datetime(t.{time_col}, 'unixepoch')) AS times
            FROM {table} AS t
            JOIN mx ON t.{value_col} = mx.max_day
            GROUP BY t.{value_col};
            """
            cur.execute(sql_day)
            row = cur.fetchone()
            if row:
                max_daily_val = row[0]
                times = []
                if row[1]:
                    for dt_str in row[1].split(','):
                        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                        times.append(dt.isoformat() + 'Z')
                times.sort()
                wettest_day = (max_daily_val, times)
            else:
                wettest_day = None

            if total is None and wettest_day is None:
                return None

            return total, wettest_day


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

    # Get period of record from the database
    datetime_stats = get_var_stats(weewx_db_path, 'dateTime')
    records_start = datetime.fromtimestamp(datetime_stats['min'])
    records_end = datetime.fromtimestamp(datetime_stats['max'])

    # =================================================================================================================
    # Metadata

    @router.get(
        '/station',
        summary='Station metadata',
        description='Retrieves all metadata associated with the weather station.',
        tags=['Station Metadata'],
    )
    def station_metadata():
        return config_dict.get('Station', {})

    @router.get(
        '/station/name',
        summary='Station name',
        description='Retrieves the name of the weather station.',
        tags=['Station Metadata'],
    )
    def station_name():
        return config_dict.get('Station', {}).get('location', '')

    @router.get(
        '/station/location',
        summary='Station location',
        description='Retrieves the latitude and longitude of the weather station.',
        tags=['Station Metadata'],
    )
    def station_location():
        latitude = config_dict.get('Station', {}).get('latitude', None)
        longitude = config_dict.get('Station', {}).get('longitude', None)
        return latitude, longitude

    @router.get(
        '/station/elevation',
        summary='Station elevation',
        description='Retrieves the elevation of the weather station.',
        tags=['Station Metadata'],
    )
    def station_elevation():
        return config_dict.get('Station', {}).get('altitude', '')

    @router.get(
        '/station/type',
        summary='Station type',
        description='Retrieves the type of hardware for the weather station.',
        tags=['Station Metadata'],
    )
    def station_type():
        return config_dict.get('Station', {}).get('station_type', '')

    # =================================================================================================================
    # Database

    @router.get(
        '/database/obs_types',
        summary='List observation types',
        description='Retrieves a list of all available observation types in the database.',
        tags=['Database'],
    )
    def get_var_list():
        # Get the list of variables
        db_var_list = get_db_columns(weewx_db_path)

        # Keep only the variable names
        db_var_list = [var['name'] for var in db_var_list]

        return db_var_list

    @router.get(
        '/database/{obs_type}/data',
        summary='Get data for observation type',
        description='Retrieves a list of all data associated with a given observation type from the database.',
        tags=['Database'],
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
        summary='Get latest observation for observation type',
        description='Retrieves the latest record in the database for a given observation type.',
        tags=['Database'],
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
        summary='Aggregate data for observation type',
        description='Retrieves an aggregated list of data from the database for a given observation type.',
        tags=['Database'],
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
        summary='Observation type statistics',
        description='Retrieves the statistics for a given observation type.',
        tags=['Database'],
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
        summary='Observation type units',
        description='Retrieves the units for a given observation type.',
        tags=['Database'],
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
        summary='Observation type data type',
        description='Retrieves the data type for a given observation type.',
        tags=['Database'],
    )
    def get_var_dtype(obs_type: str):
        # Get the list of variables
        db_var_list = get_db_columns(weewx_db_path)

        for var in db_var_list:
            if var['name'] == obs_type:
                return var['type']

        return None

    # =================================================================================================================
    # Records

    @router.get(
        '/records/por',
        summary='Period of record',
        description='Retrieves the period of record.',
        tags=['Records'],
    )
    def get_period_of_record():
        # Calculate the number of days and years
        num_days = (records_end - records_start).days
        num_years = round(num_days / 365.25, 1)

        # Create the period of record dict
        por = {'start': records_start.isoformat() + 'Z', 'end': records_end.isoformat() + 'Z', 'num_days': num_days,
               'num_years': num_years}

        return por

    @router.get(
        '/records/{obs_type}/daily',
        summary='Daily record',
        description='Retrieves the daily record for a given observation type.',
        tags=['Records'],
    )
    def get_daily_record(
            obs_type: str,
            month: str = Query(..., description='Month', pattern=REGEX_PATTERN),
            day: int = Query(..., ge=1, le=30, description='Day of the Month')
    ):

        max_value, max_time = get_var_daily_record(weewx_db_path, obs_type, month, day, 'max')
        min_value, min_time = get_var_daily_record(weewx_db_path, obs_type, month, day, 'min')
        sum_value, sum_time = get_var_daily_record(weewx_db_path, obs_type, month, day, 'sum')

        resp_dict = {
            'max_value': max_value,
            'max_time': max_time,
            'min_value': min_value,
            'min_time': min_time,
            'sum_value': sum_value,
            'sum_time': sum_time
        }

        return resp_dict

    @router.get(
        '/records/{obs_type}/daily/today',
        summary='Daily record for today',
        description='Retrieves the daily record for the current day for a given observation type.',
        tags=['Records'],
    )
    def get_daily_record_today(obs_type: str):
        month = datetime.now().strftime('%B')
        day = datetime.now().day
        return get_daily_record(obs_type, month, day)

    @router.get(
        '/records/{obs_type}/monthly',
        summary='Monthly record',
        description='Retrieves the monthly record for a given observation type.',
        tags=['Records'],
    )
    def get_monthly_record(
            obs_type: str,
            month: str = Query(..., description='Month', pattern=REGEX_PATTERN),
    ):

        max_value, max_time = get_var_monthly_record(weewx_db_path, obs_type, month, 'max')
        min_value, min_time = get_var_monthly_record(weewx_db_path, obs_type, month, 'min')
        sum_month_total, sum_max_day = get_var_monthly_record(weewx_db_path, obs_type, month, 'sum')

        resp_dict = {
            'max_value': max_value,
            'max_time': max_time,
            'min_value': min_value,
            'min_time': min_time,
            'sum_value': sum_month_total[0],
            'sum_time': sum_month_total[1],
            'sum_max_day': sum_max_day[0],
            'sum_max_day_time': sum_max_day[1]
        }

        return resp_dict

    @router.get(
        '/records/{obs_type}/monthly/current',
        summary='Monthly record for current month',
        description='Retrieves the monthly record for the current month for a given observation type.',
        tags=['Records'],
    )
    def get_monthly_record_current(obs_type: str):
        current_month = datetime.now().strftime('%B')
        return get_monthly_record(obs_type, current_month)

    @router.get(
        '/records/{obs_type}/year',
        summary='Year record',
        description='Retrieves the records for a year for a given observation type.',
        tags=['Records'],
    )
    def get_year_record(
            obs_type: str,
            year: int = Query(..., ge=records_start.year, le=records_end.year, description='Year'),
    ):
        max_value, max_time = get_var_yearly_record(weewx_db_path, obs_type, year, 'max')
        min_value, min_time = get_var_yearly_record(weewx_db_path, obs_type, year, 'min')
        sum_year_total, sum_max_day = get_var_yearly_record(weewx_db_path, obs_type, year, 'sum')

        resp_dict = {
            'max_value': max_value,
            'max_time': max_time,
            'min_value': min_value,
            'min_time': min_time,
            'sum_value': sum_year_total,
            'sum_max_day': sum_max_day[0],
            'sum_max_day_time': sum_max_day[1]
        }

        return resp_dict

    @router.get(
        '/records/{obs_type}/year/current',
        summary='Current year record',
        description='Retrieves the records for the current year for a given observation type.',
        tags=['Records'],
    )
    def get_year_record_current(obs_type: str):
        year = datetime.now().year
        return get_year_record(obs_type, year)

    @router.get(
        '/records/{obs_type}/alltime',
        summary='All time record',
        description='Retrieves the all-time record for a given observation type.',
        tags=['Records'],
    )
    def get_alltime_record(obs_type: str):
        max_value, max_time = get_var_alltime_record(weewx_db_path, obs_type, 'max')
        min_value, min_time = get_var_alltime_record(weewx_db_path, obs_type, 'min')
        sum_all, sum_max_day = get_var_alltime_record(weewx_db_path, obs_type, 'sum')

        resp_dict = {
            'max_value': max_value,
            'max_time': max_time,
            'min_value': min_value,
            'min_time': min_time,
            'sum_value': sum_all,
            'sum_max_day': sum_max_day[0],
            'sum_max_day_time': sum_max_day[1]
        }

        return resp_dict

    # =================================================================================================================
    # Normals

    # Check if PRISM normals are enabled in config
    normals_enabled = config_dict.get('DataAPI', {}).get('prism_normals', 'True').upper() == 'TRUE'
    normals_path = weewx_config_path.parent / 'archive' / 'prism_daily_normals.json'
    if normals_enabled and normals_path.is_file():

        # Load the PRISM normals
        prism_normals = load_prism_normals(normals_path)

        @router.get(
            '/normals/prism',
            summary='Get complete normals from PRISM',
            description='Retrieves the all normals for total precipitation and max, min, and average temperature derived from PRISM.',
            tags=['Normals'],
        )
        def get_prism_normals():
            if prism_normals is None:
                return HTTPException(status_code=500, detail='No PRISM normals could be found for your location.')
            return prism_normals

        @router.get(
            '/normals/prism/annual',
            summary='Get annual normals from PRISM',
            description='Retrieves the annual normals for total precipitation and max, min, and average temperature derived from PRISM.',
            tags=['Normals'],
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
            today_dt = datetime.today()
            month = today_dt.strftime('%B')

            return get_prism_normals_monthly(month)

        @router.get(
            '/normals/prism/daily',
            summary='Get the normals for a day from PRISM',
            description='Retrieves the daily normals for total precipitation and max, min, and average temperature derived from PRISM for a given month and day.',
            tags=['Normals'],
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
            summary='Get the day normals for today from PRISM',
            description='Retrieves the daily normals for total precipitation and max, min, and average temperature derived from PRISM for the current day.',
            tags=['Normals'],
        )
        def get_prism_normals_today():
            today_dt = datetime.today()
            month = today_dt.strftime('%B')
            day = today_dt.day

            return get_prism_normals_daily(month, day)

    return router
