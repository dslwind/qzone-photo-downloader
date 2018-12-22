# -*- coding: UTF-8 -*-

import os
import random
import time
from collections import namedtuple

import requests
from selenium import webdriver

# import qzone_login
from io_in_out import *

curpath = os.path.dirname(os.path.realpath(__file__))
curpath = io_in_arg(curpath)

QzoneAlbum = namedtuple('QzoneAlbum', ['uid', 'name', 'count'])
QzonePhoto = namedtuple('QzonePhoto', ['url', 'name', 'album'])


def func_save_dir(user):
    '''
    提供下载的文件保存在哪   
    保存至 <脚本目录>/qzone_photo/<用户QQ> 目录
    '''
    return os.path.join(curpath, u'qzone_photo', u'{0}'.format(user))


def func_save_photo_net_helper(session, url, timeout):
    '''
    辅助函数，先用带会话的 session 尝试下载，如果不行就去掉会话尝试下载
    '''
    if session:
        # 使用已经登陆过的账户下载，不然加密的照片下载都是写着“加密照片”
        # 使用 post 还不行，要用 get
        try:
            return session.get(url, timeout=timeout)
        except requests.ReadTimeout:
            try:
                return session.post(url, timeout=timeout)
            except requests.ReadTimeout:
                return func_save_photo_net_helper(None, url, timeout)
    else:
        return requests.get(url, timeout=timeout)


def func_save_photo(arg):
    '''
    线程函数，运行在线程池中
    文件保存格式 <相册名字>_<文件在相册的索引数字>_<文件名字>.jpeg

    1、Q.分次下载的文件，能确保同一个文件名字，都是同一个文件吗？
       A. 这个由 Qzone 的 API 保证，API 能保证顺序，那么这里就能保证顺序
    2. Q.文件名字非法，不可创建文件，怎么处理？
       A. 会用文件名字 <相册在所有相册中的索引数字>_<文件在相册的索引数字>.jpg 进行二次试创建，
         解决因为相册名字，照片名字引起的文件名非法问题。
    '''
    session, user, album_index, album_name, index, photo = arg

    dest_path = os.path.join(func_save_dir(user), album_name.strip())
    # if not os.path.exists(dest_path):
    #     os.makedirs(dest_path)

    fn = u'{0}_{1}.jpeg'.format(index, photo.name)

    print("正在下载相册 {0} 的第 {1} 张图片".format(album_name, index+1))

    def _func_replace_os_path_sep(x): return x.replace(
        u'/', u'_').replace(u'\\', u'_')
    fn = _func_replace_os_path_sep(fn)
    c_p = os.path.join(dest_path, fn)
    if not io_is_path_valid(c_p):
        c_p = os.path.join(
            dest_path, u'random_name_{0}_{1}.jpeg'.format(album_index, index))

    # 可能使用其他 api 下载过文件就不再下载
    if os.path.exists(c_p):
        return

    url = photo.url.replace('\\', '')
    attempts = 0
    timeout = 10
    while attempts < 10:
        try:
            req = func_save_photo_net_helper(session, url, timeout)
            break
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            attempts += 1
            timeout += 5
    else:
        io_print(u'down fail user:{0} {1}'.format(user, photo.url))
        return
    c = req.content

    with open(c_p, 'wb') as f:
        f.write(c)


class QzonePhotoManager(object):
    """
    查询QQ空间相册并下载的类。
    """
    albumbase1 = "http://alist.photo.qq.com/fcgi-bin/fcg_list_album?uin={0}&outstyle=2"  # 如果没有设置密保的相册是通过这个地址访问的

    # 2017.02.10 测试: 不对的，已经失效了，效果跟 albumbase1 一样，无法访问密保相册
    # albumbase2 = "http://xalist.photo.qq.com/fcgi-bin/fcg_list_album?uin=" # 设置密保的相册是通过这个地址访问的

    albumbase = albumbase1
    photobase1 = 'http://plist.photo.qq.com/fcgi-bin/fcg_list_photo?uin={0}&albumid={1}&outstyle=json'
    # photobase2 = "http://xaplist.photo.qq.com/fcgi-bin/fcg_list_photo?uin="
    photobase = photobase1

    # v3 的地址都是用过 Chrome 开发者模式查看的
    albumbase_v3 = (
        'https://h5.qzone.qq.com/proxy/domain/tjalist.photo.qzone.qq.com/fcgi-bin/fcg_list_album_v3?'
        'g_tk={gtk}&t={t}&hostUin={dest_user}&uin={user}'
        '&appid=4&inCharset=gbk&outCharset=gbk&source=qzone&plat=qzone&format=jsonp&callbackFun=&mode=3')

    # 不是原图质量
    photobase_v3 = ('https://h5.qzone.qq.com/proxy/domain/tjplist.photo.qzone.qq.com/fcgi-bin/'
                    'cgi_list_photo?g_tk={gtk}&t={t}&mode=0&idcNum=5&hostUin={dest_user}'
                    '&topicId={album_id}&noTopic=0&uin={user}&pageStart=0&pageNum=9000'
                    '&inCharset=gbk&outCharset=gbk'
                    '&source=qzone&plat=qzone&outstyle=json&format=jsonp&json_esc=1')

    def __init__(self, user, password):
        self.user = user
        self.password = password

        driver = webdriver.Chrome()
        # 使用 get() 方法打开待抓取的 URL
        driver.get('http://user.qzone.qq.com')
        time.sleep(5)
        # 等待 5 秒后，判断页面是否需要登录，通过查找页面是否有相应的 DIV 的 id 来判断
        try:
            driver.find_element_by_id('login_div')
            a = True
        except:
            a = False
        if a == True:
            # 如果页面存在登录的 DIV，则模拟登录
            driver.switch_to.frame('login_frame')
            driver.find_element_by_id('switcher_plogin').click()
            driver.find_element_by_id('u').clear()  # 选择用户名框
            driver.find_element_by_id('u').send_keys(user)
            driver.find_element_by_id('p').clear()
            driver.find_element_by_id('p').send_keys(password)
            driver.find_element_by_id('login_button').click()
            time.sleep(3)
        driver.implicitly_wait(3)

        # 判断好友空间是否设置了权限，通过判断是否存在元素 ID：QM_OwnerInfo_Icon
        try:
            driver.find_element_by_id('QM_OwnerInfo_Icon')
            b = True
        except:
            b = False
            # 如果有权限能够访问到说说页面，那么定位元素和数据，并解析
        if b == True:
            print("登录成功")

        # 尝试一下获取 Cookie，使用 get_cookies()
        cookies = driver.get_cookies()
        cookie_dict = []
        # 初始化 cookies 字典变量
        cookiess = {}
        skey = ""
        for c in cookies:
            ck = "{0}={1};".format(c['name'], c['value'])
            cookiess[c['name']] = c['value']
            cookie_dict.append(ck)
            # print("ck: " + ck)
            if c['name'] == "skey":
                skey = c['value']
        i = ''
        for c in cookie_dict:
            i += c
        print('Cookies:', i)

        self.cookie = cookiess
        self.session = ""
        self.qzone_g_tk = self.getGTK(skey)

        driver.close()
        driver.quit()

    # -----------------
    # 计算 g_tk
    # -----------------
    def utf8_unicode(self, c):
        if len(c) == 1:
            return ord(c)
        elif len(c) == 2:
            n = (ord(c[0]) & 0x3f) << 6
            n += ord(c[1]) & 0x3f
            return n
        elif len(c) == 3:
            n = (ord(c[0]) & 0x1f) << 12
            n += (ord(c[1]) & 0x3f) << 6
            n += ord(c[2]) & 0x3f
            return n
        else:
            n = (ord(c[0]) & 0x0f) << 18
            n += (ord(c[1]) & 0x3f) << 12
            n += (ord(c[2]) & 0x3f) << 6
            n += ord(c[3]) & 0x3f
            return n

    def getGTK(self, skey):
        hash = 5381
        for i in range(0, len(skey)):
            hash += (hash << 5) + self.utf8_unicode(skey[i])
        return hash & 0x7fffffff

    def access_net_v3(self, url, timeout):
        '''
        使用登录时的 session，cookie 访问网络 ，适用于高版本的 qzone api
        '''
        r = requests.get(url, cookies=self.cookie, timeout=timeout)
        # r = self.session.get(url, timeout=timeout)
        c = r.text
        c = c.replace('_Callback(', '').replace(');', '')
        return c

    def get_albums_v3(self, dest_user):
        import json
        albums = []
        url = self.albumbase_v3.format(gtk=self.qzone_g_tk,
                                       t=random.Random().random(),
                                       dest_user=dest_user,
                                       user=self.user)
        # print(url)
        c = self.access_net_v3(url, timeout=8)
        if c:
            c = json.loads(c)
            if ('data' in c) and ('albumListModeClass' in c['data']):
                for j in c['data']['albumListModeClass']:
                    if 'albumList' in j:
                        for i in j['albumList']:
                            albums.append(QzoneAlbum._make(
                                [i['id'], i['name'], i['total']]))
        # print(albums)
        return albums

    def get_photos_by_album_v3(self, dest_user, album):
        import json

        photos = []
        url = self.photobase_v3.format(
            gtk=self.qzone_g_tk,
            t=random.Random().random(),
            dest_user=dest_user,
            user=self.user,
            album_id=album.uid)
        # print(url)
        c = self.access_net_v3(url, timeout=10)
        # print(c)
        photolist=[]
        if c:
            c = json.loads(c)
            #print(c)
            if 'data' in c and 'photoList' in c['data']:
                photolist.append(c['data']['photoList'])

                # 先看是否存在原图
                # get picKey(=lloc)
                if photolist and 'lloc' in photolist[0]:
                    p = self.get_raw_photos_by_album(
                        dest_user, album, photolist[0]['lloc'])
                    if p:
                        return p
                pic_url=[]
                for i in photolist:
                    for j in i:
                        pic_url='origin_url' in j and j['origin_url'] or j['url']
                        name=j['name']
                        photos.append(QzonePhoto._make([
                            pic_url,name,album
                        ]))                        
        return photos

    def get_raw_photos_by_album(self, dest_user, album, pic_key):
        import json

        url_raw_photo_base = ('https://h5.qzone.qq.com/proxy/domain/tjplist.photo.qq.com/fcgi-bin/'
                              'cgi_floatview_photo_list_v2?'
                              'g_tk={gtk}&t={t}&topicId={album_id}&picKey={pic_key}'
                              '&shootTime=&cmtOrder=1&fupdate=1&plat=qzone&source=qzone'
                              '&cmtNum=10&inCharset=utf-8&outCharset=utf-8'
                              '&offset=0&uin={user}&appid=4&isFirst=1&hostUin={dest_user}&postNum=9999')

        photos = []
        url = url_raw_photo_base.format(
            gtk=self.qzone_g_tk,
            t=random.Random().random(),
            dest_user=dest_user,
            user=self.user,
            album_id=album.uid,
            pic_key=pic_key)

        c = self.access_net_v3(url, timeout=10)
        if c:
            c = json.loads(c)
            if 'data' in c and 'photos' in c['data']:
                for i in c['data']['photos']:
                    pic_url = ('raw' in i and i['raw']
                               or 'origin' in i and i['origin']
                               or i['url'])
                    photos.append(QzonePhoto._make([
                        pic_url, i['name'], album
                    ]))
        return photos

    def get_photos_v3(self, dest_user):
        '''
        能访问所有相册, 前提是先有权限访问该相册
        :param dest_user:
        :return:
        '''
        from concurrent.futures import ThreadPoolExecutor

        # 先获得所有相册
        albums = self.get_albums_v3(dest_user)
        photos_all = []
        io_print(u'获取到 {0} 个相册'.format(len(albums)))

        for i in range(len(albums)):
            print(albums[i].name)
            dest_path = os.path.join(func_save_dir(dest_user), albums[i].name)
            if not os.path.exists(dest_path):
                os.makedirs(dest_path)

        for i, album in enumerate(albums):
            # 根据相册 id 获取相册内所有照片
            photos = self.get_photos_by_album_v3(dest_user, album)
            photos = [(self.session, dest_user, i, album.name, si, photo)
                      for si, photo in enumerate(photos)]

            p = func_save_dir(dest_user)

            if not os.path.exists(p):
                os.makedirs(p)
            photos_all.extend(photos)

        with ThreadPoolExecutor(max_workers=20) as pool:
            r = pool.map(func_save_photo, photos_all)
            list(r)

        if not albums:
            io_stderr_print(u'未找到 {0} 可下载的相册'.format(dest_user))


def entry():
    # 你的 QQ和密码，QQ号必须写，密码可以省略，然后使用网页快速登录功能
    main_user = ''
    main_pass = ''

    # 要处理的目标 QQ 号，此处可填入多个QQ号，中间用逗号隔开
    dest_users = []

    a = QzonePhotoManager(main_user, main_pass)
    io_print(u'登录成功')

    # 如果遇到下载失败的，产生超时异常终止程序运行的，可以再重新运行，已经下载过的文件不会重新下载
    for e in dest_users:
        io_print(u'正在处理用户 {0}'.format(e))
        a.get_photos_v3(e)
        io_print(u'处理完成')


if __name__ == '__main__':
    entry()
