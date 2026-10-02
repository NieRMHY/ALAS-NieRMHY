shape = 'G7'


def location2node(location):
    """将坐标元组转换为地图网格节点名称（如 (0, 0) -> 'A1'）。

    Args:
        location (tuple[int, int]): 网格二维索引坐标 (x, y)。

    Returns:
        str: 节点名称字符串。
    """
    return chr(location[0] + 64 + 1) + str(location[1] + 1)


def node2location(node):
    """将地图网格节点名称转换为零基坐标元组（如 'A1' -> (0, 0)）。

    Args:
        node (str): 节点名称字符串。

    Returns:
        tuple[int, int]: 对应的二维坐标索引 (x, y)。
    """
    return ord(node[0]) % 32 - 1, int(node[1]) - 1
shape = node2location(shape.upper())
for y in range(shape[1]+1):
    text = ', '.join([location2node((x, y)) for x in range(shape[0]+1)]) + ', \\'
    print(text)
print('    = MAP.flatten()')