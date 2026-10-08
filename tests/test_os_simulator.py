"""大世界离线模拟的模型兼容、中断与配置默认值回归。"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from module.os_simulator.constants import AP, COIN, CL1_COUNT, MEOW_COUNT, HAS_CRASHED
from module.os_simulator.simulator import OSSimulator, _simulate_one
from module.runtime.os_simulator import SimulatorConfig, SimulatorLogs


def simulation_data(**parameters):
    data = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
    data['OpsiSimulator']['OpsiSimulatorParameters'].update({
        'Samples': 3, 'Draw': 'do_not', 'TotalTime': 180, 'TimeUseRatio': 1.0,
        'InitialAp': 500, 'InitialCoin': 100000, 'Cl1Time': 60,
        'Meow3Time': 100, 'Meow5Time': 120, 'AkashiProbability': 0.0,
        'CrossWeek': False, 'Deterministic': False, **parameters,
    })
    data['OpsiScheduling']['OpsiScheduling'].update({
        'OperationCoinsPreserve': 80000, 'OperationCoinsReturnThreshold': 1000,
        'ActionPointPreserve': 200,
    })
    return data


class OSSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.simulator = OSSimulator(figure_directory=self.temp.name)
        self.simulator.logger.logger.propagate = False

    def configure(self, **parameters):
        self.simulator.set_config(SimulatorConfig('testpilot', simulation_data(**parameters)))
        self.simulator.get_paras()
        return self.simulator

    def test_original_cl1_and_meow_transition_results(self):
        """按旧模型核对侵蚀1刷币与低黄币切换短猫的次数、消耗和自然恢复。"""
        params = (500., 100000., 180., 5, 80000., 1000., 200., 170., 1700.,
                  60., 120., 0., 6520., 40000., False, False, 7, True)
        result, *_ = _simulate_one(*params, False)
        np.testing.assert_allclose(result[[AP, COIN, CL1_COUNT, MEOW_COUNT, HAS_CRASHED]],
                                   [485.3, 100510., 3., 0., 0.])
        params = (500., 79000., 241., *params[3:])
        result, *_ = _simulate_one(*params, True)
        np.testing.assert_allclose(result[[AP, COIN, CL1_COUNT, MEOW_COUNT, HAS_CRASHED]],
                                   [435.5, 82570., 1., 2., 0.])

    def test_all_drawing_modes_execute_real_kernel_and_save_png(self):
        for draw in ('do_not', 'single_sample', 'multi_sample'):
            with self.subTest(draw=draw):
                simulator = self.configure(Draw=draw)
                simulator.completed_samples = 0
                simulator.plotter.result_figure_path = ''
                result = simulator.simulate()
                self.assertEqual((3, 8), result.shape)
                simulator._handle_result(result)
                self.assertAlmostEqual(485.3, simulator.result['ap'])
                self.assertEqual(3., simulator.result['cl1Count'])
                if draw == 'do_not':
                    self.assertFalse(simulator.figure)
                else:
                    self.assertTrue(Path(simulator.figure).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))

    def test_empty_statistics_fall_back_and_dashboard_values_are_used(self):
        simulator = self.simulator
        data = simulation_data(InitialAp=0, InitialCoin=0, Meow3Time=0, Meow5Time=0, Cl1Time=0)
        data['Dashboard']['ActionPoint']['Total'] = 1234
        data['Dashboard']['YellowCoin']['Value'] = 45678
        simulator.set_config(SimulatorConfig('testpilot', data))
        with patch('module.os_simulator.simulator.db.get_meow_stats', return_value={'avg_round_time': 0}), \
                patch('module.os_simulator.simulator.get_ship_exp_stats') as stats:
            stats.return_value.get_average_round_time.return_value = 75
            for level, duration in [('level3', 100), ('level5', 200)]:
                data['OpsiSimulator']['OpsiSimulatorParameters']['MeowHazardLevel'] = level
                simulator.get_paras()
                self.assertEqual(duration, simulator.meow_time)
                self.assertEqual(75, simulator.cl1_time)
                self.assertEqual(1234., simulator.init_ap)
                self.assertEqual(45678., simulator.init_coin)

    def test_interrupted_samples_and_average_exclude_uninitialized_tail(self):
        simulator = self.configure(Samples=1200, Draw='multi_sample')

        def finish_one_batch(results, record, grid_ap, grid_coin, grid_crash, *params):
            results[:] = 1
            grid_ap[:] = 2
            grid_coin[:] = 3
            grid_crash[:] = 0.5
            simulator._stop_event.set()

        with patch('module.os_simulator.simulator._simulate_batch_kernel', side_effect=finish_one_batch):
            result = simulator.simulate()
        self.assertEqual((1000, 8), result.shape)
        self.assertEqual(1000, simulator.completed_samples)
        np.testing.assert_allclose(simulator.history_multi_avg['ap'], 2)
        np.testing.assert_allclose(simulator.history_multi_avg['coin'], 3)
        np.testing.assert_allclose(simulator.history_multi_avg['crash'], 0.5)
        np.testing.assert_allclose(simulator.history_multi_avg['ap_std'], 0)

    def test_stop_before_sampling_does_not_publish_a_result(self):
        simulator = self.configure(Draw='single_sample')
        simulator._stop_event.set()
        self.assertEqual((0, 8), simulator.simulate().shape)
        self.assertFalse(simulator.history_single)

    def test_running_guard_interrupt_and_restart_clear_old_result(self):
        simulator = self.configure(Deterministic=True)
        entered, release = threading.Event(), threading.Event()

        def wait_for_release():
            entered.set()
            release.wait(timeout=5)

        with patch.object(simulator, 'precompile', side_effect=wait_for_release):
            self.assertTrue(simulator.start())
            self.assertTrue(entered.wait(timeout=5))
            self.assertFalse(simulator.start())
            simulator.interrupt()
            self.assertEqual('stopping', simulator.state)
            release.set()
            simulator._thread.join(timeout=5)
        self.assertEqual('interrupted', simulator.state)
        self.assertIsNone(simulator.result)
        simulator.plotter.result_figure_path = 'old.png'
        with patch.object(simulator, 'precompile'):
            self.assertTrue(simulator.start())
            simulator._thread.join(timeout=10)
        self.assertEqual('completed', simulator.state)
        self.assertEqual(1, simulator.completed_samples)
        self.assertFalse(simulator.figure)

    def test_invalid_parameters_fail_without_entering_the_kernel(self):
        for parameters in ({'TimeUseRatio': 0}, {'Samples': 0}, {'Cl1Time': -1}):
            with self.subTest(parameters=parameters):
                self.simulator.set_config(SimulatorConfig('testpilot', simulation_data(**parameters)))
                with patch.object(self.simulator, 'precompile') as compile_kernel:
                    self.simulator.start()
                    self.simulator._thread.join(timeout=5)
                    compile_kernel.assert_not_called()
                self.assertEqual('failed', self.simulator.state)
                self.assertTrue(self.simulator.error)
                self.assertIsNone(self.simulator.result)

    def test_logs_are_isolated_and_bounded(self):
        first, second = self.simulator, OSSimulator()
        logs1, logs2 = SimulatorLogs(), SimulatorLogs()
        first.logger.addHandler(logs1)
        second.logger.addHandler(logs2)
        second.logger.logger.propagate = False
        self.addCleanup(first.logger.removeHandler, logs1)
        self.addCleanup(second.logger.removeHandler, logs2)
        first.logger.info('实例一')
        second.logger.info('实例二')
        self.assertIn('实例一', logs1.snapshot('first')['entries'][0]['text'])
        self.assertNotIn('实例二', str(logs1.snapshot('first')))
        self.assertNotIn('实例一', str(logs2.snapshot('second')))
        for i in range(500):
            first.logger.info('进度 %s', i)
        snapshot = logs1.snapshot('first', after=1)
        self.assertEqual(400, len(snapshot['entries']))
        self.assertTrue(snapshot['reset'])
        logs1.clear()
        first.logger.info('新模拟')
        self.assertTrue(logs1.snapshot('first', after=snapshot['cursor'])['reset'])


if __name__ == '__main__':
    unittest.main()
