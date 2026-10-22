"""前端模拟服务调用真实计算器，只处理管道内的夹具数据。"""
import json
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace


def dispatch(request):
    from module.runtime.mind_calculator import calculate, catalog, revision
    from module.api.mind_calculator_service import MindCalculatorService, import_ships
    action = request['action']
    ships = request.get('ships', [])
    if action.startswith('tech.'):
        import tempfile
        import threading
        from pathlib import Path
        from module.api.fleet_tech_service import FleetTechService
        from module.api.protocol import FleetTechChange
        from module.runtime.fleet_tech import RECORD_PATH
        from module.config.deep import deep_get
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            path.write_text(json.dumps({'MindCalculatorScan': {'MindCalculator': {'Result': {'ships': ships}}},
                'FleetTechScan': {'FleetTech': {'Record': request.get('record', {}),
                'MinLevel': request.get('min_level', 95), 'MaxLevel': request.get('max_level', 125),
            }}}), encoding='utf-8')
            configs = SimpleNamespace(path=lambda _: path, lock=threading.RLock(),
                                      read=lambda _: (json.loads(path.read_text(encoding='utf-8')), ''))
            service = FleetTechService(configs)
            if action == 'tech.catalog':
                result = service.catalog(request['instance'])
            elif action == 'tech.report':
                result = service.report(request['instance'])
            elif action == 'tech.syncMind':
                result = service.sync_mind(request['instance'])
            elif action == 'tech.patch':
                result = service.patch(request['instance'], request['revision'],
                                       [FleetTechChange.model_validate(c) for c in request.get('changes', [])], request.get('nations', {}))
            else:
                raise ValueError('未知科技模拟操作')
            return dict(result=result, record=deep_get(configs.read('')[0], RECORD_PATH, {}))
    if action == 'catalog':
        data = catalog()
        return dict(updated_at=data['updated_at'], ships=list(data['ships'].values()))
    if action in ('report', 'calculate'):
        return dict(revision=revision(ships), **calculate(ships))
    if action == 'import':
        return {'ships': import_ships(request['filename'], request['content'])}
    saved = {'MindCalculatorScan': {'MindCalculator': {'Result': {'ships': ships}}}}
    service = MindCalculatorService(SimpleNamespace(read=lambda _: (saved, ''), path=lambda _: None))
    if action == 'export':
        return service.export(request['instance'], request.get('format', 'xlsx'))
    if action == 'recognize':
        return service.recognize(request['instance'], request['filename'], request['content'])
    raise ValueError('未知模拟操作')


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            result = dispatch(request)
    except Exception as exc:
        result = {'error': str(exc), 'code': getattr(exc, 'code', 'INVALID_PARAMS')}
    print(json.dumps(result, ensure_ascii=False))
