#!/usr/bin/env python2
#coding=utf-8

from datetime import datetime
import logging

import web
from google.appengine.api import users
from google.appengine.ext import db
from icalendar import Calendar, Event, UTC

from environment import render
from model.dbevent import Dbevent, dbevent2event, xml2dbevents
from model.syncqueue import SyncQueue
from controller.sync import Sync, SyncLocation
from util.doubanapi import fetchEvent

routes = (
    '/test', 'Test',
    '/sync-location', 'SyncLocation',
    '/sync', 'Sync',
    '/location/(.+)', 'Get',
)

category_map = {
    'all': u'所有类型',
    'music': u'音乐/演出',
    'exhibition': u'展览',
    'film': u'电影',
    'salon': u'讲座/沙龙',
    'drama': u'戏剧/曲艺',
    'party': u'生活/聚会',
    'sports': u'体育',
    'travel': u'旅行',
    'commonweal': u'公益',
    'others': u'其他',
}

class Get:
    def GET(self, location):
        web.header('Content-Type', 'text/plain;charset=UTF-8')
        params = web.input(type='all', length=None) #web.py post/get默认值
        category = params.type #活动类型
        length = params.length #活动长度
        if category not in category_map: #处理意外的type参数
            category = 'all'
        category = category.strip()
        if length != None and length.isdigit() and length > 0:
            length = int(length)

        cal = Calendar()
        cal.add('prodid', '-//Google Inc//Google Calendar 70.9054//EN')
        cal.add('version', '2.0')
        cal.add('X-WR-TIMEZONE', 'Asia/Shanghai')
        cal.add('CLASS', 'PUBLIC')
        cal.add('METHOD', 'PUBLISH')
        cal.add('CALSCALE', 'GREGORIAN')
        cal.add('X-WR-CALNAME', u'豆瓣%s - %s活动' \
                %(location, category_map[category]))
        desc = u'dbevent2gc - 豆瓣%s - %s活动 \n' \
                %(location, category_map[category])
        if length != None:
            desc += u'活动时间长度：%d小时 以内' %length
        desc += u'via https://github.com/alswl/dbevent2gc\n' \
                u'by alswl(http://log4d.com)'
        cal.add('X-WR-CALDESC', desc)
        cal['dtstamp'] = datetime.strftime(datetime.now(), '%Y%m%dT%H%M%SZ')

        query = getDbeventsQuery(location, category, length)

        result = query.fetch(50)
        #豆瓣活动转换到iCalendar Event
        events = [dbevent2event(e) for e in result]
        for e in events:
            cal.add_component(e)

        return cal.as_string()

def getDbeventsQuery(location_id, category, length, start=0, count=50):
    """
    从数据库获取dbevents的query，如果取不到就去豆瓣同步
    """
    def getDbeventsQueryFromDb(location_id, category, length, start, count):
        """内函数"""
        dbevents = Dbevent.all() #从数据库获取数据
        dbevents.filter('location_id =', location_id) #地点
        if category != 'all': #类别
            dbevents.filter('category =', 'event.' + category)
        if length > 0: #活动长度
            dbevents.filter('length <=', length)
        dbevents.order("-id")
        return dbevents

    dbevents = getDbeventsQueryFromDb(location_id,
                                      category,
                                      length,
                                      start,
                                      count)

    if dbevents.count() == 0: #如果数据库没有值，则去实时查询
        xml = fetchEvent(location_id, category=category)
        dbevents_new = xml2dbevents(xml)
        db.put(dbevents_new)
        SyncQueue(key_name=location_id,
                  location=location_id,
                  last_sync=datetime(1988, 12, 24)).put()
        #db.run_in_transaction(lambda i, j: db.put(i) and db.put(j),
                             #dbevents_new, #FIXME 加入事务
                             #sysQueue)

    return getDbeventsQueryFromDb(location_id,
                                  category,
                                  length,
                                  start,
                                  count)

class Test:
    def GET(self):
        location = 'nanjing'
        category = 'all'
        xml = fetchEvent(location, category=category, start=50, max=50)
        dbevents_new = xml2dbevents(xml)

        db.put(dbevents_new)

        return 'ok'


app = web.application(routes, locals())

# vim: set ft=python:
