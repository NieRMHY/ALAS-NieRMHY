"""协议信封、错误码及参数类型；禁止隐式调用任意 Python 方法。"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

VERSION = 1


class ApiError(Exception):
    """可以安全展示给用户的业务错误。"""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


class Params(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Request(Params):
    v: Literal[1]
    type: Literal['request']
    id: StrictStr = Field(min_length=1, max_length=100)
    method: StrictStr = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class AuthParams(Params):
    password: StrictStr = Field(default='', max_length=256)


class SchemaParams(Params):
    language: Literal['zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW'] = 'zh-CN'


class InstanceParams(Params):
    instance: StrictStr = Field(min_length=1, max_length=64)


class CreateParams(Params):
    name: StrictStr = Field(min_length=1, max_length=64)
    source: StrictStr | None = None
    import_file: StrictStr | None = None


class ImportParams(Params):
    """上传一份配置文件到导入目录，供创建实例时选用。"""

    name: StrictStr = Field(min_length=1, max_length=64)
    content: StrictStr = Field(min_length=2, max_length=2_000_000)


class TaskParams(InstanceParams):
    task: StrictStr = Field(min_length=1, max_length=80)


class ShopStrategyValidateParams(InstanceParams):
    """高级商店策略的只读语法校验请求。"""

    task: Literal['EventShop', 'ShopFrequent', 'ShopOnce', 'PrivateQuarters', 'OpsiShop', 'OpsiVoucher']
    script: StrictStr = Field(max_length=20000)


class ConfigChange(Params):
    path: StrictStr = Field(min_length=1, max_length=180)
    value: Any


class PatchParams(InstanceParams):
    revision: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    changes: list[ConfigChange] = Field(min_length=1, max_length=200)


class RevisionParams(InstanceParams):
    revision: StrictStr


class SubscribeParams(Params):
    instance: StrictStr | None = None
    topics: list[Literal['instances', 'overview', 'logs', 'preview']] = Field(max_length=4)


class LogsParams(InstanceParams):
    after: StrictInt = Field(default=0, ge=0)


class StatisticsParams(InstanceParams):
    days: StrictInt = Field(default=7, ge=1, le=90)
    resource: Literal['Oil', 'Coin', 'Gem', 'Cube', 'Pt', 'ActionPoint', 'Core', 'Medal', 'Merit', 'GuildCoin', 'YellowCoin', 'PurpleCoin'] = 'Oil'


class StatisticsReportParams(InstanceParams):
    category: Literal['resources', 'action', 'opsi', 'commission', 'ships', 'loot'] = 'resources'
    month: StrictStr | None = Field(default=None, pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    days: StrictInt = Field(default=7, ge=1, le=365)
    period: Literal['day', 'week', 'month'] = 'month'


class MeowfficerScoreReportParams(InstanceParams):
    """指挥喵评分报告的只读查询。"""

    limit: StrictInt = Field(default=100, ge=1, le=500)


class MeowfficerClearReportParams(InstanceParams):
    """清空指挥喵评分报告（删掉 json / md / html 三份产物）。"""


class DeployParams(Params):
    values: dict[str, Any]


class CommitsParams(Params):
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=50, ge=1, le=100)


class StartupParams(InstanceParams):
    enabled: StrictBool | None = None
    remember: StrictBool | None = None


def response(request_id, result):
    return {'v': VERSION, 'type': 'response', 'id': request_id, 'ok': True, 'result': result}


def failure(request_id, error: ApiError):
    return {'v': VERSION, 'type': 'response', 'id': request_id, 'ok': False,
            'error': {'code': error.code, 'message': error.message, 'details': error.details}}
