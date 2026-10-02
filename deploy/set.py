"""通过命令行快速修改 config/deploy.yaml 中的配置项。

用法示例：
    python -m deploy.set GitExecutable=/usr/bin/git PythonExecutable=/usr/bin/python3.8
"""
import sys
import typing as t

from deploy.utils import poor_yaml_read, poor_yaml_write, DEPLOY_TEMPLATE


def get_args() -> t.Dict[str, str]:
    """解析命令行中形如 key=value 的键值对参数。

    Returns:
        dict[str, str]: 参数键值对映射。
    """
    args = {}
    for arg in sys.argv[1:]:
        if '=' not in arg:
            continue
        k, v = arg.split('=')
        k, v = k.strip(), v.strip()
        args[k] = v
    return args


def config_set(output='./config/deploy.yaml'):
    """将命令行解析的配置覆盖写入指定的部署配置文件。

    Args:
        output (str): 输出的 YAML 配置文件路径，默认为 './config/deploy.yaml'。
    """
    data = poor_yaml_read(DEPLOY_TEMPLATE)
    data.update(poor_yaml_read(output))
    for k, v in get_args().items():
        if k in data:
            print(f'{k} set')
            data[k] = v
        else:
            print(f'{k} not exist')
    poor_yaml_write(data, file=output)


if __name__ == '__main__':
    config_set()
