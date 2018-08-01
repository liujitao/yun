# -*- coding: utf-8 -*-
from QcloudApi.qcloudapi import QcloudApi
from concurrent.futures import ThreadPoolExecutor, wait, as_completed

import urllib2
import json
import time
from datetime import datetime
import calendar

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

url = 'http://127.0.0.1:5000'
config = {
    'Region': 'ap-shanghai',
    'secretId': '',
    'secretKey': '',
}

def cvm_total():
    module = 'cvm'
    action = 'DescribeInstances'

    service = QcloudApi(module, config)
    resp = service.call(action, {'Version': '2018-07-12', 'Limit': 1})
    count = json.loads(resp)['Response']['TotalCount']
    return count


def get_cvm_info(offset=0):
    module = 'cvm'
    action = 'DescribeInstances'

    service = QcloudApi(module, config)
    resp = service.call(
        action, {'Version': '2018-07-12', 'Offset': offset, 'Limit': 100})

    data = []
    data.extend(json.loads(resp)['Response']['InstanceSet'])

    return data


def get_cvm_price(id):
    module = 'cvm'
    service = QcloudApi(module, config)
    params = {
        'Version': '2018-07-12',
        'InstanceChargePrepaid.Period': 1,
        'RenewPortableDataDisk': True,
        'InstanceIds.0': id
    }

    try:
        resp = service.call('InquiryPriceRenewInstances', params)
        #time.sleep(5)
        if json.loads(resp)['Response'].has_key('Price'):  # 仅包年包月主机有续费价格
            price = json.loads(resp)['Response']['Price']['InstancePrice']['DiscountPrice']
            logger.info(u'获取云主机[%s] 成本[%s]' % (id, price)) 
            return {'id': id, 'price': price}
    except Exception as e:
        logger.info(u'获取云主机成本失败, %s' % e)  

def post_host_data(data):
    headers = {'Content-Type': 'application/json'}
    req = urllib2.Request(url='%s/api/sync/host' % url, headers=headers, data=json.dumps(data))
    urllib2.urlopen(req)


def put_host_data(data):
    headers = {'Content-Type': 'application/json'}
    req = urllib2.Request(url='%s/api/sync/host' % url, headers=headers, data=json.dumps(data))
    req.get_method = lambda: 'PUT'
    urllib2.urlopen(req)


def put_price_data(data):
    headers = {'Content-Type': 'application/json'}
    req = urllib2.Request(url='%s/api/sync/host/price' % url, headers=headers, data=json.dumps(data))
    req.get_method = lambda: 'PUT'
    urllib2.urlopen(req)


if __name__ == '__main__':
    # 获取腾讯云项目信息
    logger.info(u'处理项目信息开始')

    module = 'account'
    action = 'DescribeProject'

    service = QcloudApi(module, config)
    resp = service.call(action, {'Version': '2018-07-12'})
    projects = json.loads(resp)['data']
    headers = {'Content-Type': 'application/json'}
    req = urllib2.Request(url='%s/api/sync/project' % url, headers=headers, data=json.dumps(projects))
    req.get_method = lambda: 'PUT'
    urllib2.urlopen(req)
    logger.info(u'处理项目信息结束')

    # 获取腾讯云主机信息 (实例列表接口请求频率限制40次/每秒)
    logger.info(u'处理云主机信息开始')

    hosts = []

    offsets = range(0, cvm_total(), 100)
    executor = ThreadPoolExecutor(max_workers=40)
    for data in executor.map(get_cvm_info, offsets):
        hosts.extend(data)

    # 云主机id
    qcloud_id = [host['InstanceId'] for host in hosts]

    # 数据库主机id
    req = urllib2.urlopen('%s/api/host/id' % url)
    db_id = json.loads(req.read())

    # 比较云接口与本地数据库的数据差异
    insert_id = list(set(qcloud_id) - set(db_id))
    update_id = list(set(qcloud_id) & set(db_id))
    delete_id = list(set(db_id) - set(qcloud_id))

    logger.info(u'插入[%s]台，更新[%s]台, 置销毁标志[%s]台' % (len(insert_id), len(update_id), len(delete_id)))


    # 插入新数据
    if len(insert_id) > 0:
        logger.info(u'插入开始')
        data = [host for host in hosts if host['InstanceId'] in insert_id]
        executor = ThreadPoolExecutor(max_workers=20)
        executor.map(post_host_data, data)
        logger.info(u'插入结束')

    # 更新数据
    if len(update_id) > 0:
        logger.info(u'更新开始')
        data = [host for host in hosts if host['InstanceId'] in update_id]
        executor = ThreadPoolExecutor(max_workers=50)
        executor.map(put_host_data, data)
        logger.info(u'更新结束')

    # 置销毁标志
    if len(delete_id) > 0:
        logger.info(u'置销毁标志开始')
        headers = {'Content-Type': 'application/json'}
        req = urllib2.Request(url='%s/api/sync/host' % url, headers=headers, data=json.dumps(delete_id))
        req.get_method = lambda: 'DELETE'
        urllib2.urlopen(req)
        logger.info(u'置销毁标志结束')
    
    time.sleep(5)
    logger.info(u'处理云主机信息结束')
    
    # 获取云主机成本 (续费实例询价接口 请求频率限制：10次/每秒)
    logger.info(u'处理云主机价格信息开始')
    

    # 数据库主机id
    req = urllib2.urlopen('%s/api/host/id' % url)
    db_id = json.loads(req.read())
    logger.info(u'更新 [%s] 台云主机价格信息' % len(db_id))

    prices = []
    now = datetime.now()
    create_time = now.strftime('%Y-%m-%d 00:00:00')
    days = calendar.monthrange(now.year, now.month)[1]

    executor = ThreadPoolExecutor(max_workers=10)
    for data in executor.map(get_cvm_price, db_id):
        if data:
            data['price_day'] = data['price'] / days
            data['create_time'] = create_time
            prices.append(data)

    executor = ThreadPoolExecutor(max_workers=20)
    executor.map(put_price_data, prices)
    logger.info(u'处理云主机价格信息结束')
