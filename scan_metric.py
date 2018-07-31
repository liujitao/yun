# -*- coding: utf-8 -*-
from QcloudApi.qcloudapi import QcloudApi
from concurrent.futures import ThreadPoolExecutor, wait, as_completed

import urllib2
import json
import time
from datetime import datetime, timedelta

import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

config = {
    'Region': 'ap-shanghai',
    'secretId': '联系腾讯云客服',
    'secretKey': '联系腾讯云客服',
}

# 每小时采集一次 当前时间90天内的性能指标，入库
start = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d 00:00:00')

url = 'http://127.0.0.1:5000'


def get_host_metric_list():
    module = 'monitor'
    action = 'DescribeBaseMetrics'

    params = {
        'Version': '2018-07-12', 'namespace': 'qce/cvm'
    }

    service = QcloudApi(module, config)
    resp = service.call(action, params)
    return json.loads(resp)['metricSet']


def get_host_cpu(id):
    module = 'monitor'
    action = 'GetMonitorData'

    params = {
        'Version': '2018-07-12', 'namespace': 'qce/cvm', 'period': 86400, 'startTime': start,
        'metricName': 'cpu_usage', 'dimensions.0.name': 'unInstanceId', 'dimensions.0.value': id,
    }

    service = QcloudApi(module, config)
    try:
        resp = service.call(action, params)
        data = {'id': id, 'name': 'cpu_usage',
                'value': max(json.loads(resp)['dataPoints'])}
        logger.info(u'获取云主机 [%s] cpu性能指标值 [%.2f]' % (id, data['value']))
        return data
    except Exception as e:
        logger.info(u'获取云主机 [%s] cpu性能指标失败 %s' % (id, e))


def get_host_memory(id):
    module = 'monitor'
    action = 'GetMonitorData'

    params = {
        'Version': '2018-07-12', 'namespace': 'qce/cvm', 'period': 86400, 'startTime': start,
        'metricName': 'mem_usage', 'dimensions.0.name': 'unInstanceId', 'dimensions.0.value': id,
    }

    service = QcloudApi(module, config)
    try:
        resp = service.call(action, params)
        data = {'id': id, 'name': 'memory_usage',
                'value': max(json.loads(resp)['dataPoints'])}
        logger.info(u'获取云主机 [%s] memory性能指标值 [%.2f]' % (id, data['value']))
        return data
    except Exception as e:
        logger.info(u'获取云主机 [%s] memory性能指标失败 %s' % (id, e))


def get_host_disk(id):
    mount = ['vda1', 'vdb1', 'vdc1', 'vdd1', 'vde1', 'vdf1', 'vdg1',
             'vdh1', 'vdi1', 'vdj1', 'vdk1', 'vdl1', 'vdm1', 'vdn1']
    
    disk = []
    count = get_host_disk_mount(id)
    if count > 0:
        for i in range(0, count):
            usage = get_host_disk_usage(id, mount[i])
            total =  get_host_disk_total(id, mount[i])

            if usage and total:
                disk.append('%s|%.2f|%d' % (mount[i], usage, total/1000))
            elif usage:
                disk.append('%s|%.2f|' % (mount[i], usage))
            elif total:
                disk.append('%s||%d' % (mount[i], total/1000))
            else:
                disk.append('%s||' % mount[i])

        data = {'id': id, 'name': 'disk_usage', 'value': ','.join(disk)}
        logger.info(u'获取云主机 [%s] disk性能指标值 [%s]' % (id, data['value']))
        return data

def get_host_disk_mount(id):
    headers = {'Content-Type': 'application/json'}
    data = {'id': id}

    req = urllib2.Request(url='%s/api/host/disk' % url, headers=headers, data=json.dumps(data))
    resp = urllib2.urlopen(req)
    mount = len(json.loads(resp.read()))

    #logger.info(u'获取云主机 [%s] disk挂载点 [ %d ]' % (id, mount))
    return mount

def get_host_disk_usage(id, name):
    module = 'monitor'
    action = 'GetMonitorData'

    params = {
        'Version': '2018-07-12',
        'namespace': 'qce/cvm',
        'period': 86400,
        'startTime': start,
        'metricName': 'disk_usage',
        'dimensions.0.name': 'unInstanceId', 'dimensions.0.value': id,
        'dimensions.1.name': 'diskname', 'dimensions.1.value': name,
    }

    try:
        service = QcloudApi(module, config)
        resp = service.call(action, params)
        return max(json.loads(resp)['dataPoints'])
    except Exception as e:
        logger.info(u'获取云主机 [%s] disk_usage 性能指标失败 %s' % (id, e))
        return None

def get_host_disk_total(id, name):
    module = 'monitor'
    action = 'GetMonitorData'

    params = {
        'Version': '2018-07-12',
        'namespace': 'qce/cvm',
        'period': 86400,
        'startTime': start,
        'metricName': 'disk_total',
        'dimensions.0.name': 'unInstanceId', 'dimensions.0.value': id,
        'dimensions.1.name': 'diskname', 'dimensions.1.value': name,
    }

    try:
        service = QcloudApi(module, config)
        resp = service.call(action, params)
        return max(json.loads(resp)['dataPoints'])
    except Exception as e:
        logger.info(u'获取云主机 [%s] disk_total 性能指标失败 %s' % (id, e))
        return None

def put_host_metirc_data(data):
    if data:
        headers = {'Content-Type': 'application/json'}
        req = urllib2.Request(url='%s/api/sync/host/metric' % url, headers=headers, data=json.dumps(data))
        req.get_method = lambda: 'PUT'
        urllib2.urlopen(req)


if __name__ == '__main__':
    # 数据库主机id
    req = urllib2.urlopen('%s/api/host/id' % url)
    db_id = json.loads(req.read())

    # 获取监控指标列表 (接口调用频率限制为：50次/秒，500次/分钟)
    logger.info(u'更新云性能指标')
    
    cpu = []
    executor = ThreadPoolExecutor(max_workers=20)
    for data in executor.map(get_host_cpu, db_id):
        cpu.append(data)

    logger.info(u'cpu性能指标 [%d] 写入数据库' % len(cpu))
    executor = ThreadPoolExecutor(max_workers=50)
    executor.map(put_host_metirc_data, cpu)

    time.sleep(2)

    memory = []
    executor = ThreadPoolExecutor(max_workers=20)
    for data in executor.map(get_host_memory, db_id):
        memory.append(data)

    logger.info(u'memory性能指标 [%d] 写入数据库' % len(memory))
    executor = ThreadPoolExecutor(max_workers=50)
    executor.map(put_host_metirc_data, memory)

    time.sleep(2)

    disk = []
    executor = ThreadPoolExecutor(max_workers=20)
    for data in executor.map(get_host_disk, db_id):
        disk.append(data)

    logger.info(u'disk性能指标 [%d] 写入数据库' % len(disk))
    executor = ThreadPoolExecutor(max_workers=50)
    executor.map(put_host_metirc_data, disk)

    logger.info(u'更新云性能结束')