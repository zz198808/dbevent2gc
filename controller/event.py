#!/usr/bin/env python2
#coding=utf-8

from datetime import datetime
import logging

import web
from google.appengine.api import users
from google.appengine.ext import db
from icalendar import Calendar, Event, UTC
from google.appengine.api import urlfetch
from BeautifulSoup import BeautifulStoneSoup
import iso8601

from environment import render
from model.dbevent import Dbevent
#from model.calendar import Calendar

routes = (
    '/test', 'Test',
    '/location/(.+)', 'Get',
)

apikey = '0a4b03a80958ff351ee10af81c0afd9f'
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

        if query.count() == 0: #如果数据库没有值，则去实时查询
            xml = fetchEvent(location, category=category)
            dbevents_new = xml2dbevents(xml)
            db.put(dbevents_new)
            query = getDbeventsQuery(location, category, length)

        result = query.fetch(50)
        #豆瓣活动转换到iCalendar Event
        events = [dbevent2event(e) for e in result]
        for e in events:
            cal.add_component(e)

        return cal.as_string()

def getDbeventsQuery(location_id, category, length, start=0, count=50):
    """从数据库获取dbevents的query"""
    def getDbeventsQueryFromDb(location_id, category, length, start, count):
        """内函数"""
        dbevents = Dbevent.all() #从数据库获取数据
        dbevents.filter('location_id =', location_id) #地点
        if category != 'all': #类别
            dbevents.filter('category =', 'event.' + category)
        if length > 0: #活动长度
            dbevents.filter('length <=', length)
        #dbevents.order("-id")
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

def dbevent2event(dbevent):
    """转换豆瓣数据模型到iCal数据模型"""
    event = Event()
    event.add('summary', dbevent.title)
    desc = dbevent.summary
    if isinstance(dbevent.participants, int):
        desc += '\n\n' + u'参与人数 %d, 感兴趣人数 %d' \
                %(dbevent.participants, dbevent.wishers)
    desc += '\n\n' + dbevent.alternate_link
    event.add('DESCRIPTION', desc)
    #event.add('dtstart', dbevent.start_time)
    event['dtstart'] = datetime.strftime(dbevent.start_time, '%Y%m%dT%H%M%SZ')
    #event.add('dtend', dbevent.end_time)
    event['dtend'] = datetime.strftime(dbevent.end_time, '%Y%m%dT%H%M%SZ')
    event.add('STATUS', 'CONFIRMED')
    location = dbevent.where
    if dbevent.geo_point != None:
        location += u' @(%s)' %dbevent.geo_point
    event.add('location', location)
    #event.add('dtstamp', datetime.now())
    event['dtstamp'] = datetime.strftime(datetime.now(), '%Y%m%dT%H%M%SZ')
    event['uid'] = dbevent.id
    return event

def fetchEvent(location, category='all', max=50, start=0):
    """从豆瓣api获取数据"""
    url = 'http://api.douban.com/event/location/%s?' \
            'type=%s&start-index=%d&max-results=%d&apikey=%s' %(location,
                                                                category,
                                                                start,
                                                                max,
                                                                apikey)
    logging.info('fetch events from douban url: %s'%url)
    result = urlfetch.fetch(url)
    if result.status_code == 200:
        return result.content
    else:
        raise Exception('get events from douban.com failed')

def xml2dbevents(xml):
    """使用beautifulsoup转换html到Dbevent"""
    soup = BeautifulStoneSoup(xml)
    entrys = soup.findAll('entry')
    events = [] #FIXME 名字修改
    for entry in entrys:
        events.append(entry2dbevent(entry))
    return events

def entry2dbevent(entry):
    """转换entry xml到dbevent"""
    self_link = entry.find('link', attrs={'rel': 'self'})['href']
    id = int(self_link.split('/')[-1])

    title = unicode(entry.title.string)
    category = entry.category['term'].split('#')[-1]
    alternate_link = entry.find('link', attrs={'rel': 'alternate'})['href']
    summary = unicode(entry.summary.string) #.replace(r'\n', '</br>')
    content = unicode(entry.content.string)

    if entry.find('db:attribute',
                  attrs={'name':'invite_only'}).string == 'yes':
        invite_only = True
    else:
        invite_only = False
    if entry.find('db:attribute',
                  attrs={'name':'invite_only'}).string == 'yes':
        can_invite = True
    else:
        can_invite = False
    participants = int(entry.find('db:attribute',
                                  attrs={'name':'participants'}).string)
    wishers  = int(entry.find('db:attribute',
                                  attrs={'name':'wishers'}).string)
    album  = int(entry.find('db:attribute',
                                  attrs={'name':'album'}).string)
    location  = entry.find('db:location')
    location_id = location['id']
    location_name = unicode(location.string)
    start_time = iso8601.parse_date(entry.find('gd:when')['starttime'])
    end_time = iso8601.parse_date(entry.find('gd:when')['endtime'])
    where = entry.find('gd:where')['valuestring']

    length = end_time-start_time
    length = length.days * 24 + length.seconds / 60 /60

    dbevent = Dbevent(
        key_name=str(id),
        id=id,
        title=title,
        self_link=self_link,
        alternate_link=alternate_link,
        category=category,
        summary=summary,
        content=content,
        participants=participants,
        wishers=wishers,
        location_id=location_id,
        location_name=location_name,
        start_time=start_time,
        end_time=end_time,
        length=length,
        where=where,
        )

    geo_point = entry.find('georss:point')
    if geo_point != None:
        dbevent.geo_point = unicode(geo_point.string)

    return dbevent


app = web.application(routes, locals())

