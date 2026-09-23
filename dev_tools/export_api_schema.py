"""从后端参数模型生成前端类型和可审阅的 API 契约。"""
import json
from pathlib import Path

from module.api.protocol import AuthParams, SubscribeParams
from module.api.router import Method, Router


def typescript(schema, definitions):
    if '$ref' in schema:
        return typescript(definitions[schema['$ref'].split('/')[-1]], definitions)
    if 'anyOf' in schema:
        return ' | '.join(typescript(item, definitions) for item in schema['anyOf'])
    if 'enum' in schema:
        return ' | '.join(json.dumps(item, ensure_ascii=False) for item in schema['enum'])
    kind = schema.get('type')
    if kind == 'array':
        return f'Array<{typescript(schema["items"], definitions)}>'
    if kind == 'object':
        fields = schema.get('properties', {})
        if not fields:
            return 'Record<string, unknown>' if schema.get('additionalProperties') else 'Record<string, never>'
        required = schema.get('required', [])
        return '{ ' + '; '.join(f'{key}{"" if key in required else "?"}: {typescript(value, definitions)}'
                               for key, value in fields.items()) + ' }'
    return {'string': 'string', 'integer': 'number', 'number': 'number',
            'boolean': 'boolean', 'null': 'null'}.get(kind, 'unknown')


def main():
    registry = dict(Router(None, None).methods)
    registry['auth.login'] = Method(AuthParams, lambda _: None)
    registry['events.subscribe'] = Method(SubscribeParams, lambda _: None)
    contracts, lines = {}, ['// 由 dev_tools.export_api_schema 生成，请勿手动编辑。', 'export interface Parameters {']
    for name, entry in registry.items():
        schema = entry.params.model_json_schema()
        contracts[name] = {'mutates': entry.mutates, 'params': schema}
        lines.append(f'  "{name}": {typescript(schema, schema.get("$defs", {}))}')
    lines.append('}')
    directory = Path(__file__).resolve().parents[1] / 'frontend/src/api'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'generated.ts').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (directory / 'contract.json').write_text(json.dumps({'version': 1, 'methods': contracts},
                                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
