"""Lua 与 Python 数据结构转换解析器 (SLPP)。

基于 SirAnthony/slpp 的 Alas 定制分支，修复了复杂嵌套表中的序号索引解析问题。
原始仓库：https://github.com/SirAnthony/slpp
分支仓库：https://github.com/LmeSzinc/slpp
"""
import re
import sys
from numbers import Number

import six

ERRORS = {
    'unexp_end_string': u'Unexpected end of string while parsing Lua string.',
    'unexp_end_table': u'Unexpected end of table while parsing Lua string.',
    'mfnumber_minus': u'Malformed number (no digits after initial minus).',
    'mfnumber_dec_point': u'Malformed number (no digits after decimal point).',
    'mfnumber_sci': u'Malformed number (bad scientific format).',
}


def sequential(lst):
    """检查整数列表是否为从 0 开始连续递增的序列。

    Args:
        lst (list[int]): 待检查的键列表。

    Returns:
        bool: 若为从 0 开始连续递增的序列则返回 True，否则返回 False。
    """
    length = len(lst)
    if length == 0 or lst[0] != 0:
        return False
    for i in range(length):
        if i + 1 < length:
            if lst[i] + 1 != lst[i + 1]:
                return False
    return True


class ParseError(Exception):
    """Lua 语法解析异常。"""
    pass


class SLPP(object):
    """Lua 数据结构编码与解码器。"""

    def __init__(self):
        """初始化解析器内部状态与正则匹配模式。"""
        self.text = ''
        self.ch = ''
        self.at = 0
        self.len = 0
        self.depth = 0
        self.space = re.compile(r'\s', re.M)
        self.alnum = re.compile(r'\w', re.M)
        self.newline = '\n'
        self.tab = '\t'

    def decode(self, text):
        """将 Lua 表或数据字符串反序列化为 Python 对象。

        Args:
            text (str): 待解析的 Lua 数据字符串。

        Returns:
            Any: 解析生成的 Python 字典、列表或基础类型对象。
        """
        if not text or not isinstance(text, six.string_types):
            return
        # 游戏脚本无注释，删除注释可能误伤长字符串内容，因此跳过正则过滤
        self.text = text
        self.at, self.ch, self.depth = 0, '', 0
        self.len = len(text)
        self.next_chr()
        result = self.value()
        return result

    def encode(self, obj):
        """将 Python 数据结构序列化为 Lua 格式字符串。

        Args:
            obj (Any): 待序列化的 Python 对象。

        Returns:
            str: 生成的 Lua 表或字面量字符串。
        """
        self.depth = 0
        return self.__encode(obj)

    def __encode(self, obj):
        """递归序列化 Python 对象的内部实现。

        Args:
            obj (Any): 当前待序列化的节点对象。

        Returns:
            str: 节点对应的 Lua 表达式字符串。
        """
        s = ''
        tab = self.tab
        newline = self.newline

        if isinstance(obj, str):
            s += '"%s"' % obj.replace(r'"', r'\"')
        elif six.PY2 and isinstance(obj, unicode):
            s += '"%s"' % obj.encode('utf-8').replace(r'"', r'\"')
        elif six.PY3 and isinstance(obj, bytes):
            s += '"{}"'.format(''.join(r'\x{:02x}'.format(c) for c in obj))
        elif isinstance(obj, bool):
            s += str(obj).lower()
        elif obj is None:
            s += 'nil'
        elif isinstance(obj, Number):
            s += str(obj)
        elif isinstance(obj, (list, tuple, dict)):
            self.depth += 1
            if len(obj) == 0 or (not isinstance(obj, dict) and len([
                x for x in obj
                if isinstance(x, Number) or (isinstance(x, six.string_types) and len(x) < 10)
            ]) == len(obj)):
                newline = tab = ''
            dp = tab * self.depth
            s += "%s{%s" % (tab * (self.depth - 2), newline)
            if isinstance(obj, dict):
                key = '[%s]' if all(isinstance(k, int) for k in obj.keys()) else '%s'
                contents = [dp + (key + ' = %s') % (k, self.__encode(v)) for k, v in obj.items()]
                s += (',%s' % newline).join(contents)
            else:
                s += (',%s' % newline).join(
                    [dp + self.__encode(el) for el in obj])
            self.depth -= 1
            s += "%s%s}" % (newline, tab * self.depth)
        return s

    def white(self):
        """跳过连续的空白字符。"""
        while self.ch:
            if self.space.match(self.ch):
                self.next_chr()
            else:
                break

    def next_chr(self):
        """前进到下一个字符。

        Returns:
            bool | None: 成功推进返回 True，到达字符串末尾返回 None。
        """
        if self.at >= self.len:
            self.ch = None
            return None
        self.ch = self.text[self.at]
        self.at += 1
        return True

    def value(self):
        """解析并返回当前位置的 Lua 值（对象、字符串、数字或关键字）。

        Returns:
            Any: 解析出的 Python 对应值。
        """
        self.white()
        if not self.ch:
            return
        if self.ch == '{':
            return self.object()
        if self.ch == "[":
            self.next_chr()
        if self.ch in ['"', "'", '[']:
            return self.string(self.ch)
        if self.ch.isdigit() or self.ch == '-':
            return self.number()
        return self.word()

    def string(self, end=None):
        """解析 Lua 字符串字面量。

        Args:
            end (str | None): 字符串结束闭合符号。

        Returns:
            str: 解析提取出的字符串内容。

        Raises:
            ParseError: 遇到未闭合的意外字符串结尾时抛出。
        """
        s = ''
        start = self.ch
        if end == '[':
            end = ']'
        if start in ['"', "'", '[']:
            while self.next_chr():
                if self.ch == end:
                    self.next_chr()
                    if start != "[" or self.ch == ']':
                        return s
                if self.ch == '\\' and start == end:
                    self.next_chr()
                    if self.ch != end:
                        s += '\\'
                s += self.ch
        raise ParseError(ERRORS['unexp_end_string'])

    def object(self):
        """解析 Lua table 对象结构（转换为 dict 或 list）。

        Returns:
            dict | list: 解析得到的 Python 集合。

        Raises:
            ParseError: 遇到结构损坏或未闭合的 table 时抛出。
        """
        o = {}
        k = None
        idx = 0
        self.depth += 1
        self.next_chr()
        self.white()
        if self.ch and self.ch == '}':
            self.depth -= 1
            self.next_chr()
            return o  # 正常空表退出
        else:
            while self.ch:
                self.white()
                if self.ch == '{':
                    o[idx] = self.object()
                    idx += 1
                    continue
                elif self.ch == '}':
                    self.depth -= 1
                    self.next_chr()
                    if k is not None:
                        o[idx] = k
                    if len([key for key in o if isinstance(key, six.string_types + (int, float, bool, tuple))]) == 0:
                        so = sorted([key for key in o])
                        if sequential(so):
                            ar = []
                            for key in o:
                                ar.insert(key, o[key])
                            o = ar
                    return o  # 正常闭合退出
                else:
                    if self.ch == ',':
                        self.next_chr()
                        continue
                    else:
                        k = self.value()
                        if self.ch == ']':
                            self.next_chr()
                    self.white()
                    ch = self.ch
                    if ch in ('=', ','):
                        self.next_chr()
                        self.white()
                        if ch == '=':
                            o[k] = self.value()
                        else:
                            o[idx] = k
                        idx += 1
                        k = None
        raise ParseError(ERRORS['unexp_end_table'])  # 异常退出

    words = {'true': True, 'false': False, 'nil': None}

    def word(self):
        """解析标识符或保留字（如 true, false, nil）。

        Returns:
            bool | None | str: 关键字映射值或原始标识符。
        """
        s = ''
        if self.ch != '\n':
            s = self.ch
        self.next_chr()
        while self.ch is not None and self.alnum.match(self.ch) and s not in self.words:
            s += self.ch
            self.next_chr()
        return self.words.get(s, s)

    def number(self):
        """解析数值（包括整数、浮点数、十六进制和科学计数法）。

        Returns:
            int | float: 解析后的数值。
        """
        def next_digit(err):
            n = self.ch
            self.next_chr()
            if not self.ch or not self.ch.isdigit():
                raise ParseError(err)
            return n

        n = ''
        try:
            if self.ch == '-':
                n += next_digit(ERRORS['mfnumber_minus'])
            n += self.digit()
            if n == '0' and self.ch in ['x', 'X']:
                n += self.ch
                self.next_chr()
                n += self.hex()
            else:
                if self.ch and self.ch == '.':
                    n += next_digit(ERRORS['mfnumber_dec_point'])
                    n += self.digit()
                if self.ch and self.ch in ['e', 'E']:
                    n += self.ch
                    self.next_chr()
                    if not self.ch or self.ch not in ('+', '-'):
                        raise ParseError(ERRORS['mfnumber_sci'])
                    n += next_digit(ERRORS['mfnumber_sci'])
                    n += self.digit()
        except ParseError:
            t, e = sys.exc_info()[:2]
            print(e)
            return 0
        try:
            return int(n, 0)
        except:
            pass
        return float(n)

    def digit(self):
        """连续读取十进制数字串。

        Returns:
            str: 提取到的连续数字字符串。
        """
        n = ''
        while self.ch and self.ch.isdigit():
            n += self.ch
            self.next_chr()
        return n

    def hex(self):
        """连续读取十六进制数字串。

        Returns:
            str: 提取到的十六进制数字字符。
        """
        n = ''
        while self.ch and (self.ch in 'ABCDEFabcdef' or self.ch.isdigit()):
            n += self.ch
            self.next_chr()
        return n


slpp = SLPP()
