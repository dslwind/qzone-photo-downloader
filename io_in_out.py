# -*- coding: UTF-8 -*-
'''
输入输出函数

其他脚本中的进入的字符串参数和输出到屏幕的字符串参数都需要经过转换
进入的字符串需要转为 unicode （为了支持路径中的中文）
输出到屏幕的字符串需要从 unicode 转为 str （为了兼容重定向符号 > ,某些时候我们需要把脚本运行结果重定向到文件）

兼容 python 2.6, 2.7, 3
'''
import os
import sys

pyver = sys.version_info[0]  # major
if pyver >= 3:
    io_in_code = str # io 读取时应该转换成为的目标编码
    io_out_code = bytes
    io_raw_input = input
else:
    io_in_code = unicode
    io_out_code = str
    io_raw_input = raw_input
io_str_codes = (io_in_code, io_out_code)


def io_in_arg(arg):
    if isinstance(arg, io_in_code):
        return arg
    codes = ['utf-8', 'gbk']
    for c in codes:
        try:
            return arg.decode(c)
        except UnicodeDecodeError as er:
            pass
    else:
        raise er


def io_bytes_arg(arg):
    '''
    python 与 ctypes 交互也用这个， ctypes 需要 py3 中的 bytes 类型
    :param arg:
    :return:
    '''
    if isinstance(arg, io_in_code):
        codes = ['utf-8', 'gbk']
        for c in codes:
            try:
                return arg.encode(c)
            except UnicodeEncodeError as er:
                pass
        else:
            raise er
    return arg


def io_iter_files_from_arg(args):
    for e in args:
        if os.path.isfile(e):
            yield io_in_arg(e)
        elif os.path.isdir(e):
            for root, sub, files in os.walk(e):
                for i in files:
                    yield io_in_arg(os.path.join(root, i))
        else:
            io_print(u'unaccept arg {0}'.format(e))
    raise StopIteration


def io_out_arg(arg):
    global pyver
    if pyver < 3:
        codes = []
        c = sys.stdout.encoding
        if c:
            codes.append(c)
        codes.extend(['utf-8', 'gbk'])

        for c in codes:
            try:
                return arg.encode(c)
            except UnicodeEncodeError as er:
                pass
        else:
            raise er
    else:
        return arg


def io_sys_stdout(arg):
    io_conv_func = lambda e: io_out_arg(e) if isinstance(e, io_str_codes) else str(e)
    if isinstance(arg, (tuple, list, dict)):
        x = map(io_conv_func, arg)
        arg = '\t'.join(x)
    else:
        arg = io_conv_func(arg)
    r = sys.stdout.write(arg)
    sys.stdout.flush()
    return r


def io_print(arg):
    io_sys_stdout(arg)
    print ('')
    sys.stdout.flush()


def io_stderr_print(arg):
    global pyver
    sys.stdout.flush()
    sys.stderr.flush()
    if pyver < 3:
        print >> sys.stderr, arg
    else:
        eval('print(arg,file=sys.stderr)')


def io_files_from_arg(args):
    r = []
    for e in args:
        if os.path.isfile(e):
            r.append(io_in_arg(e))
        elif os.path.isdir(e):
            e = io_in_arg(e)
            for root, sub, files in os.walk(e):
                for i in files:
                    x = os.path.join(root, i)
                    r.append(io_in_arg(x))
        else:
            io_print(u'unaccept arg {0}'.format(io_in_arg(e)))
    return r


def io_is_path_valid(pathname):
    '''
    路径是否有效
    http://stackoverflow.com/questions/9532499/check-whether-a-path-is-valid-in-python-without-creating-a-file-at-the-paths-ta
    :param pathname:
    :return: bool
    '''
    import errno
    ERROR_INVALID_NAME = 123
    try:
        _, pathname = os.path.splitdrive(pathname)
        root_dirname = os.environ.get('HOMEDRIVE', 'C:') if sys.platform == 'win32' else os.path.sep
        root_dirname = root_dirname.rstrip(os.path.sep) + os.path.sep

        for pathname_part in pathname.split(os.path.sep):
            try:
                os.lstat(root_dirname + pathname_part)
            except OSError as exc:
                if hasattr(exc, 'winerror'):
                    if exc.winerror == ERROR_INVALID_NAME:
                        return False
                elif exc.errno in [errno.ENAMETOOLONG, errno.ERANGE]:
                    return False
    except TypeError:
        return False
    else:
        return True


'''
end
'''


def test_unicode_list():
    arg = [u'你好', u"中国"]
    io_print(arg)


def test_tupple():
    a = (1, '2', '34', u'中国')
    io_print(a)


def test():
    test_unicode_list()


def test_path():
    io_print(u'stdout_encoding:{0}'.format(sys.stdout.encoding))
    p = io_files_from_arg(sys.argv[1::])
    for e in p:
        io_print(e)
        io_print(io_is_path_valid(e))


if __name__ == '__main__':
    test()
    test_tupple()
    test_path()
