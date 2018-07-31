# -*- coding: utf-8 -*-

from flask import Flask, render_template, jsonify, request
from peewee import *
import time
import json
import re
import uuid

# 数据库配置
db = MySQLDatabase('yun', host='localhost', port=3306,
                   user='yun', password='@yun', charset='utf8mb4')


class BaseModel(Model):
    class Meta:
        database = db


class Project(BaseModel):
    id = IntegerField(index=True, unique=True, primary_key=True)
    name = CharField(max_length=40)
    create_time = DateTimeField(null=True)

    class Meta:
        table_name = 'project'


class Host(BaseModel):
    id = CharField(max_length=40, index=True, unique=True, primary_key=True)
    name = CharField(max_length=40)
    private_ip = CharField(max_length=20, null=True)
    public_ip = CharField(max_length=20, null=True)
    cpu = IntegerField()
    memory = IntegerField()
    disk = CharField(max_length=256)
    cpu_usage = FloatField(null=True)
    memory_usage = FloatField(null=True)
    disk_usage = CharField(max_length=256, null=True)
    create_time = DateTimeField()
    expire_time = DateTimeField(null=True)
    type = CharField(max_length=20)  # PREPAID 包年包月, POSTPAID_BY_HOUR 按量计费
    price = IntegerField(null=True)
    status = IntegerField(default=0)  # 0 使用 1 销毁
    project = ForeignKeyField(
        Project, backref='hosts', null=True, on_delete='SET NULL', on_update='CASCADE')

    class Meta:
        table_name = 'host'


class Cost(BaseModel):
    id = CharField(max_length=40, index=True, primary_key=True)
    value = DoubleField()
    type = CharField(max_length=20)  # host, mysql, redis, mongodb
    create_time = DateTimeField()
    host = ForeignKeyField(Host, backref='costs', null=True,
                           on_delete='CASCADE', on_update='CASCADE')

    class Meta:
        table_name = 'cost'


class History(BaseModel):
    id = CharField(max_length=40, index=True, primary_key=True)
    host = IntegerField()
    host_cost = IntegerField()
    mysql = IntegerField()
    mysql_cost = IntegerField()
    redis = IntegerField()
    redis_cost = IntegerField()
    mongodb = IntegerField()
    mongodb_cost = IntegerField()
    create_time = DateTimeField()
    project_id = IntegerField(index=True)
    project_name = CharField(max_length=40)

    class Meta:
        table_name = 'history'


app = Flask(__name__)
app.config.update(
    DEBUG=True,
    SECRET_KEY='0bfeed58-8a45-11e8-9657-f0def165d278'
)

db.connect()
db.create_tables([Project, Host, Cost, History])
if Project.get_or_none(Project.id == 0):
    pass
else:
    Project.insert(id=0, name=u'默认').execute()
db.close()


@app.route('/', methods=['GET'])
@app.route('/host', methods=['GET'])
def host():
    return render_template('host.html')


@app.route('/project', methods=['GET'])
def project():
    return render_template('project.html')

# 接口 - 云主机


@app.route('/api/host', methods=['GET'])
def get_host():
    # /api/host?sort=project&order=desc&offset=0&limit=20&_=1532684368819
    
    query = Host.select(Host, Project.name) \
        .join(Project, join_type=JOIN.LEFT_OUTER, on=(Host.project_id == Project.id)) \
        .where(Host.status == 0)

    data = [{
        'id': q.id, 'name': q.name, 'project': q.project.name,
        'private_ip': q.private_ip, 'public_ip': q.public_ip,
        'cpu': q.cpu, 'memory': q.memory, 'disk': format_disk(q.disk),
        'cpu_usage': q.cpu_usage,
        'memory_usage': q.memory_usage, 
        'disk_usage': q.disk_usage,
        'create_time': q.create_time, 'expire_time': q.expire_time,
        'type': q.type, 'price': q.price}
        for q in query]

    return jsonify(data)


def format_disk(value):
    # "SystemDisk|50|CLOUD_BASIC,DataDisks|50|CLOUD_BASIC,DataDisks|250|CLOUD_SSD"
    return value.replace('SystemDisk', u'SYS').replace('DataDisk', u'DATA').replace('LOCAL_BASIC', u'普通L').replace(
        'CLOUD_BASIC', u'普通').replace('CLOUD_PREMIUM', u'高性能').replace('LOCAL_SSD', u'SSDL').replace('CLOUD_SSD', 'SSD')


@app.route('/api/host/id', methods=['GET'])
def get_host_id():
    query = Host.select().where(Host.status == 0)
    data = [q.id for q in query]
    return jsonify(data)

@app.route('/api/host/disk', methods=['POST'])
def get_host_disk():
    id = request.json['id']
    query = Host.get_or_none(Host.id==id)

    if query:
        return jsonify(query.disk.split(','))
    else:
        return None

# 接口 - 项目


@app.route('/api/project', methods=['GET'])
@app.route('/api/project/<int:id>', methods=['GET'])
def get_project(id=None):
    if id:
        try:
            query = Project.select().where(Project.id == id).order_by(Project.id).get()
            data = {'id': query.id, 'name': query.name,
                    'create_time': query.createTime}
        except DoesNotExist:
            data = {}
    else:
        try:
            query = (Project.select(
                Project.id, Project.name, Project.create_time,
                fn.count(Host.id).alias('host'), fn.sum(
                    Host.price).alias('host_cost'),
            )
                .join(Host, join_type=JOIN.LEFT_OUTER, on=(Host.project_id == Project.id))
                .group_by(Project.id)
                .order_by(Project.create_time)
            )
            data = [{'id': q.id, 'name': q.name, 'host': q.host, 'host_cost': int(q.host_cost) if q.host_cost else 0, 'mysql': '', 'redis': '', 'mongo': '', 'create_time': q.create_time}
                    for q in query]
        except DoesNotExist:
            data = []

    return jsonify(data)


# 同步数据
@app.route('/api/sync/project', methods=['PUT'])
def qcloud_project():
    project = request.json

    # 数据库项目信息
    query = Project.select()
    project_id = [q.id for q in query]

    for p in project:
        if p['projectId'] == 0:
            continue
        elif p['projectId'] in project_id:
            Project.update(name=p['projectName']).where(
                Project.id == p['projectId']).execute()
        else:
            Project.insert(id=p['projectId'], name=p['projectName'],
                           create_time=p['createTime'].replace('T', ' ')[:-1]).execute()

    return jsonify({'msg': u'%s个项目更新成功' % len(project)})


@app.route('/api/sync/host', methods=['POST'])
def add_qcloud_host():
    id, name = request.json['InstanceId'], request.json['InstanceName']
    private_ip = request.json['PrivateIpAddresses'][0] if request.json['PrivateIpAddresses'] else None
    public_ip = request.json['PublicIpAddresses'][0] if request.json['PublicIpAddresses'] else None
    cpu, memory = request.json['CPU'], request.json['Memory']
    system_disk = request.json['SystemDisk']
    data_disk = request.json['DataDisks'] if request.json['DataDisks'] else None
    create_time = request.json['CreatedTime'].replace(
        'T', ' ')[:-1] if request.json['CreatedTime'] else None
    expire_time = request.json['ExpiredTime'].replace(
        'T', ' ')[:-1] if request.json['ExpiredTime'] else None
    type = request.json['InstanceChargeType']
    project_id = request.json['Placement']['ProjectId']

    # SystemDisk|50|CLOUD_BASIC,DataDisk|50|CLOUD_BASIC,DataDisk|250|CLOUD_SSD
    disks = ['SystemDisk|%s|%s' %
             (system_disk['DiskSize'], system_disk['DiskType'])]
    if data_disk:
        disks.extend(['DataDisk|%s|%s' % (d['DiskSize'], d['DiskType'])
                      for d in data_disk])

    try:
        Host.insert(id=id, name=name, private_ip=private_ip, public_ip=public_ip,
                    cpu=cpu, memory=memory, disk=','.join(disks), create_time=create_time, expire_time=expire_time,
                    type=type, status=0, project_id=project_id).execute()
        return jsonify({'msg': u'云主机%s创建成功' % str(request.json['InstanceId'])})
    except Exception as e:
        print e
        return jsonify({'msg': u'云主机%s创建失败' % str(request.json['InstanceId'])})

    return jsonify({})


@app.route('/api/sync/host', methods=['PUT'])
def update_qcloud_host():
    id, name = request.json['InstanceId'], request.json['InstanceName']
    private_ip = request.json['PrivateIpAddresses'][0] if request.json['PrivateIpAddresses'] else None
    public_ip = request.json['PublicIpAddresses'][0] if request.json['PublicIpAddresses'] else None
    cpu, memory = request.json['CPU'], request.json['Memory']
    system_disk = request.json['SystemDisk']
    data_disk = request.json['DataDisks'] if request.json['DataDisks'] else None
    create_time = request.json['CreatedTime'].replace(
        'T', ' ')[:-1] if request.json['CreatedTime'] else None
    expire_time = request.json['ExpiredTime'].replace(
        'T', ' ')[:-1] if request.json['ExpiredTime'] else None
    type = request.json['InstanceChargeType']
    project_id = request.json['Placement']['ProjectId']

    # SystemDisk|50|CLOUD_BASIC,DataDisk|50|CLOUD_BASIC,DataDisk|250|CLOUD_SSD
    disks = ['SystemDisk|%s|%s' %
             (system_disk['DiskSize'], system_disk['DiskType'])]
    if data_disk:
        disks.extend(['DataDisk|%s|%s' % (d['DiskSize'], d['DiskType'])
                      for d in data_disk])

    try:
        Host.update(name=name, private_ip=private_ip, public_ip=public_ip,
                    cpu=cpu, memory=memory, disk=','.join(disks), create_time=create_time, expire_time=expire_time,
                    type=type, status=0, project_id=project_id).where(Host.id == id).execute()

        return jsonify({'msg': u'云主机%s更新成功' % str(request.json['InstanceId'])})
    except Exception as e:
        print e
        return jsonify({'msg': u'云主机%s更新失败' % str(request.json['InstanceId'])})

    return jsonify({})


@app.route('/api/sync/host', methods=['DELETE'])
def delete_qcloud_host():
    id = request.json
    try:
        Host.update(status=1).where(Host.id.in_(id)).execute()
        return jsonify({'msg': u'%d台云主机置销毁标志位成功' % len(id)})
    except Exception as e:
        return jsonify({'msg': u'云主机置销毁标志位失败'})


@app.route('/api/sync/host/price', methods=['PUT'])
def update_qcloud_price():
    id = request.json['id']
    price = request.json['price']
    price_day = request.json['price_day']
    create_time = request.json['create_time']

    try:
        Host.update(price=price).where(Host.id == id).execute()
        if Cost.get_or_none(Cost.host_id == id, Cost.type == 'host', Cost.create_time == create_time):
            Cost.update(value=price_day).where(
                Cost.host_id == id, Cost.type == 'host').execute()
        else:
            Cost.insert(id=str(uuid.uuid1()), value=price_day,
                        type='host', create_time=create_time, host_id=id).execute()

        return jsonify({'msg': u'云主机%s价格更新成功' % id})
    except Exception as e:
        return jsonify({'msg': u'云主机%s价格更新失败' % id})


@app.route('/api/sync/host/metric', methods=['PUT'])
def update_qcloud_metric():
    id = request.json['id']
    name = request.json['name']
    value = request.json['value']

    try:
        if name == 'cpu_usage':
            Host.update(cpu_usage=value).where(Host.id == id).execute()
        elif name == 'memory_usage':
            Host.update(memory_usage=value).where(Host.id == id).execute()
        elif name == 'disk_usage':
            Host.update(disk_usage=value).where(Host.id == id).execute()

        return jsonify({'msg': u'云主机 [%s] 性能参数 [%s] 更新成功' % (id, name)})
    except Exception as e:
        return jsonify({'msg': u'云主机 [%s] 性能参数 [%s] 更新失败' % (id, name)})


if __name__ == '__main__':
    app.run(host='0.0.0.0')
