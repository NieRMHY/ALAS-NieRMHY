"""卡片程序的可序列化公共模型。"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


PortType = Literal['any', 'number', 'boolean', 'string', 'time', 'duration', 'resource', 'task', 'tasks', 'result', 'list', 'object']
Mode = Literal['native', 'enhance', 'takeover']


class PortDefinition(Model):
    name: str
    type: PortType = 'any'
    required: bool = False


class CardDefinition(Model):
    type: str
    label: str
    category: str
    pure: bool = True
    entry: bool = False
    inputs: list[PortDefinition] = Field(default_factory=list)
    outputs: list[PortDefinition] = Field(default_factory=list)
    exits: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class CardNode(Model):
    id: str = Field(min_length=1, max_length=80)
    type: str
    label: str = ''
    comment: str = Field(default='', max_length=2000)
    params: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float | int] = Field(default_factory=lambda: {'x': 0, 'y': 0})


class Connection(Model):
    id: str
    source: str
    sourcePort: str
    target: str
    targetPort: str = 'in'
    kind: Literal['control', 'data'] = 'control'


class VariableDefinition(Model):
    name: str = Field(min_length=1, max_length=80)
    type: PortType = 'any'
    initial: Any = None
    persistent: bool = False


class Graph(Model):
    entry: str
    nodes: list[CardNode] = Field(max_length=500)
    edges: list[Connection] = Field(default_factory=list, max_length=2000)


class SubgraphDefinition(Graph):
    id: str
    name: str
    pure: bool = False
    inputs: list[PortDefinition] = Field(default_factory=list)
    outputs: list[PortDefinition] = Field(default_factory=list)


class ProgramDocument(Graph):
    schemaVersion: Literal[1] = 1
    name: str = '自定义调度'
    subgraphs: list[SubgraphDefinition] = Field(default_factory=list, max_length=100)
    variables: list[VariableDefinition] = Field(default_factory=list, max_length=200)
    viewport: dict[str, float | int] = Field(default_factory=lambda: {'x': 0, 'y': 0, 'zoom': 1})


class ResourceObservation(Model):
    name: str
    value: int | float | None = None
    limit: int | float | None = None
    total: int | float | None = None
    observedAt: str | None = None
    source: str = 'unknown'
    status: Literal['fresh', 'stale', 'missing', 'unavailable'] = 'missing'
    refreshable: bool = False


class TaskInvocation(Model):
    task: str
    node: str
    overrides: dict[str, Any] = Field(default_factory=dict)


class TaskOutcome(Model):
    task: str
    status: Literal['completed', 'yielded', 'recoverable', 'failed', 'interrupted']
    reason: str = ''
    finishedAt: str | None = None


class Diagnostic(Model):
    message: str
    node: str | None = None
    graph: str = 'main'


class ProgramState(Model):
    status: str = 'idle'
    node: str | None = None
    reason: str = ''
    task: str | None = None
    deadline: str | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, ResourceObservation] = Field(default_factory=dict)
