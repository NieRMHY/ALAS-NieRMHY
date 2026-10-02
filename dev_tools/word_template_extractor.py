"""游戏敏感词字典提取工具。

从解密的 word_template.lua 脚本中提取屏蔽词前缀树，还原为完整的敏感词黑名单列表。
数据来源参考：https://github.com/Dimbreath/AzurLaneData
"""
import re

from dev_tools.slpp import slpp

file = ''
count = 0


def extract(dic, word_list):
    """递归遍历敏感词 Trie 树提取完整词语。

    Args:
        dic (dict): 当前节点的子树字典。
        word_list (list[str]): 当前已累积的字符列表。
    """
    global count
    for word, data in dic.items():
        word = str(word)
        if data.get('this', False):
            new = word_list + [word]
            new = ''.join(new)
            count += 1
            print(new)
        else:
            new = word_list + [word]
            extract(data, word_list=new)


if __name__ == '__main__':
    # 将解密脚本路径填入下方 file 变量，如 '<your_folder>/<server>/sharecfg/word_template.lua'
    # 支持的服务器列表: en-US, ja-JP, ko-KR, zh-CN, zh-TW
    if file:
        with open(file, 'r', encoding='utf-8') as f:
            text = f.read()

        # 国服提取
        for result in re.findall(r'word_template = (.*?)return', text, re.DOTALL):
            pg = slpp.decode(result)
            extract(pg, word_list=[])
        # 其他外服提取
        for result in re.findall(r'uv0\.{0,1}(.*?)end', text, re.DOTALL):
            pg = slpp.decode('{%s}' % result)
            extract(pg, word_list=[])

        print(f'Total count: {count}')
