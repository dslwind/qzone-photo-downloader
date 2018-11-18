import time

from bs4 import BeautifulSoup
from selenium import webdriver

# driver = webdriver.Chrome("C:\Program Files (x86)\Google\Chrome\Application\chromedriver.exe")
# # 设置浏览器窗口的位置和大小
# driver.set_window_position(20, 40)
# driver.set_window_size(1100, 700)
#
# # 打开一个页面（QQ 空间登录页）
# driver.get("http://qzone.qq.com")
# # 登录表单在页面的框架中，所以要切换到该框架
# driver.switch_to_frame("login_frame")
# # 通过使用选择器选择到表单元素进行模拟输入和点击按钮提交
# driver.find_element_by_id("switcher_plogin").click()
# driver.find_element_by_id("u").clear()
# driver.find_element_by_id("u").send_keys("917464311")
# driver.find_element_by_id("p").clear()
# driver.find_element_by_id("p").send_keys("123456")
# driver.find_element_by_id("login_button").click()
#
# # 退出窗口
# driver.quit()

def login():
    driver = webdriver.Chrome("C:\Program Files (x86)\Google\Chrome\Application\chromedriver.exe")
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
        driver.find_element_by_id('u').send_keys('QQ号码')
        driver.find_element_by_id('p').clear()
        driver.find_element_by_id('p').send_keys('QQ密码')
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
    for c in cookies:
        ck = "{0}={1};".format(c['name'], c['value'])
        cookie_dict.append(ck)
    i = ''
    for c in cookie_dict:
        i += c
    print('Cookies:', i)

    driver.close()
    driver.quit()
    return cookies

# -----------------
# 计算 g_tk
# -----------------
def utf8_unicode(c):
    if len(c)==1:
        return ord(c)
    elif len(c)==2:
        n = (ord(c[0]) & 0x3f) << 6
        n += ord(c[1]) & 0x3f
        return n
    elif len(c)==3:
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

def getGTK(skey):
    hash = 5381
    for i in range(0,len(skey)):
        hash += (hash << 5) + utf8_unicode(skey[i])
    return hash & 0x7fffffff


# 登录 QQ 空间
def get_shuoshuo(qq):
    driver = webdriver.Chrome("C:\Program Files (x86)\Google\Chrome\Application\chromedriver.exe")
    # 使用 get() 方法打开待抓取的 URL
    driver.get('http://user.qzone.qq.com/{}/311'.format(qq))
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
        driver.find_element_by_id('u').send_keys('QQ号码')
        driver.find_element_by_id('p').clear()
        driver.find_element_by_id('p').send_keys('QQ密码')
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
        driver.switch_to.frame('app_canvas_frame')
        content = driver.find_elements_by_css_selector('.content')
        stime = driver.find_elements_by_css_selector('.c_tx.c_tx3.goDetail')
        for con, sti in zip(content, stime):
            data = {
                'time': sti.text,
                'shuos': con.text
            }
            print(data)
        pages = driver.page_source
        soup = BeautifulSoup(pages, 'lxml')

    # 尝试一下获取 Cookie，使用 get_cookies()
    cookie = driver.get_cookies()
    cookie_dict = []
    for c in cookie:
        ck = "{0}={1};".format(c['name'], c['value'])
        cookie_dict.append(ck)
    i = ''
    for c in cookie_dict:
        i += c
    print('Cookies:', i)

    driver.close()
    driver.quit()


if __name__ == '__main__':
    get_shuoshuo('QQ号码')