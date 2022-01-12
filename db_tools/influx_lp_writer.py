"""
Reads data from PostgreSQL database, maps onto oTherm data fields,
and outputs .dat file using the influx line protocol
"""

import configuration
import datetime
import numpy as np
import psycopg2
import pandas as pd
from otherm_db_reader import get_equipment_data, get_site_info


def get_data_for_influx(installation_id, start, end, msp_columns):
    """
    Retrieves data from a PostgreSQL database.

    :param int installation_id:  site identifier in target database
    :param date start: start date (e.g. 2018-1-1)
    :param date end: end date (e.g. 2018-12-31)
    :param str msp_columns: list of columns for the SQL query (see below)

    :return:   *pandas.DataFrame*  containing data records for the columns in ``msp_columns``.

    .. note::

       msp_columns for SQL query are a single *str* representing a comma separated list,
       such as::

            'ewt, lwt, compressor, created, flow_rate, auxiliary, outdoor_temperature'

    .. note::
       For the purposes of writing the line-protocol files, the DataFrame does **not** have a DatetimeIndex

    """
    ges = configuration.a2h_ge_read
    db_read = psycopg2.connect(**ges)
    parameters = (msp_columns, str(installation_id),
                  start.strftime('%Y-%m-%d 00:00:00%z'),
                  end.strftime('%Y-%m-%d 00:00:00%z'))

    #sql = """SELECT %s from results_flattenedresponse WHERE installation_id = %s
    #and created BETWEEN TIMESTAMPTZ '%s' AND TIMESTAMPTZ '%s'""" % parameters

    sql = """SELECT %s FROM results_wattresponse w INNER JOIN results_flattenedresponse fr ON w.response_id = fr.id
    WHERE fr.installation_id = %s AND created BETWEEN TIMESTAMPTZ '%s' AND TIMESTAMPTZ
    '%s' ORDER BY fr.created """ % parameters

    data = pd.read_sql(sql, db_read)
    data.sort_values('created', inplace=True)
    db_read.close()
    return data


def write_files(db_name, uuid, df, column_mapping, chunk_size, slug):
    """ Takes heat pump operating data as pandas dataframe and writes to datafile 
    using influx line protocol.

    :param str db_name: Name of the influx database, default is 'otherm-data'
    :param str uuid:  oTherm uuid of the thermal equipment, this is that influx db tag
    :param pandas.DataFrame df: Monitoring system data
    :param dict column_mapping: Mapping of monitoring system column names to standardized oTherm column names
    :param int chunk_size: Number of lines in each chunk file, recommended value is 8000
    :return: Function produces a set of line-protocol text files

    The influx db line protocol consists of three *space delimited* elements: (1) a comma delimited pair of \
    the database name and the measurement tag, (2) a comma delimited list of fields and values (no spaces), and (3) \
    a timestamp in epoch time.  For example, with spaces shown with `|_|`:

    ``otherm-data,equipment=59468786-1ab3-4203-82d9-78f480ce0600|_|\
    source_supplytemp=6.88,source_returntemp=4.59,heatpump_power=2100.0|_|1454768864``

    There is one line for each record.

    """

    df.rename(mapper=column_mapping, inplace=True, axis=1)
    if 'heat_flow_rate' in column_mapping.values():
        df['heat_flow_rate'] = df['heat_flow_rate'].fillna(0)
    df['outdoor_temperature'] = df['outdoor_temperature'].fillna(method='ffill')
    line_reference = ",".join([db_name, "=".join(['equipment', uuid])])
    columns = df.columns.tolist()
    chunks = int(len(df)/chunk_size)
    df_split = np.array_split(df, chunks)
    print (len(df_split))
    for i in range(len(df_split)):
        lp_file_name = ['../temp_files/cgb_ges_data/' + db_name, slug, ('chunk_%d.txt' % i)]
        lp_file_for_chunk = open("_".join(lp_file_name), 'w')
        for index, row in df_split[i].iterrows():
            measures = []
            for column in columns:
                if column != 'created':
                    measures.append("=".join([column, str(row[column])]))
                data_elements = ','.join(measures)
                timestamp = str(row.created.timestamp()).split('.')[0]
            lp_line = " ".join([line_reference, data_elements, timestamp, '\n'])
            lp_file_for_chunk.write(lp_line)
        lp_file_for_chunk.flush()
        lp_file_for_chunk.close()
    return


if __name__ == '__main__':
    db_name = 'otherm-data'
    install_info = pd.read_csv('../temp_files/cgb_ges_installs.csv')
    for i in range(13, len(install_info)):
        install_id = install_info['MonSysID'][i]
        site_name = str(install_info['NGEN'][i])
        site_info = get_site_info(site_name, 'othermcgb')
        site_id = site_info.id

        start_date = install_info['StartDate'][i]
        stop_date = '2022-01-11'
        start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        stop = datetime.datetime(2022, 1, 11)

        equipment_data = get_equipment_data(site_id, start_date, stop_date, 'US/Eastern', 'othermcgb')
        equip_uuid = equipment_data[0].uuid

        msp_columns = 'ewt_1, lwt_1, compressor_1, created, q_1_device, auxiliary_1, heat_flow_1, outdoor_temperature'
        chunk_size = 8000

        print('Working on .db_to_influx...   ', install_id)

        column_mapping = {"auxiliary_1": "heatpump_aux",
                         "compressor_1": "heatpump_power",
                         "lwt_1": "source_returntemp",
                         "ewt_1": "source_supplytemp",
                         "q_1_device": "sourcefluid_flowrate",
                         "outdoor_temperature": "outdoor_temperature",
                         "heat_flow_1": "heat_flow_rate"}

        data = get_data_for_influx(install_id, start, stop, msp_columns)

        write_files(db_name, equip_uuid, data, column_mapping, chunk_size, site_name)



