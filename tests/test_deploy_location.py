import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import config as deploy_config
from deploy import geo
from deploy import git as deploy_git
from deploy.Windows import config as windows_config
from deploy.utils import poor_yaml_read


class TestIp9Location(unittest.TestCase):
    @patch('deploy.geo.requests.get')
    def test_returns_lowercase_country_code(self, get):
        response = get.return_value
        response.json.return_value = {'data': {'country_code': 'CN'}}
        self.assertEqual(geo.get_country_code(), 'cn')
        get.assert_called_once_with(
            geo.IP9_LOCATION_URL,
            timeout=5,
            headers={'User-Agent': 'AzurPilot'},
        )
        response.raise_for_status.assert_called_once_with()

    @patch('deploy.geo.requests.get')
    def test_invalid_response_returns_none(self, get):
        get.return_value.json.return_value = {'data': {}}
        self.assertIsNone(geo.get_country_code())


# Modify by MHY, 部署只迁移旧更新源，不请求定位或启用 CDN / 镜像分流
class TestDeployLocation(unittest.TestCase):
    def make_config(self, config_module, repository=None, branch='essex'):
        instance = object.__new__(config_module.DeployConfig)
        instance.config = {'Repository': repository or config_module.GITHUB_REPOSITORY,
                           'Branch': branch}
        instance.Repository = instance.config['Repository']
        instance.Branch = branch
        return instance

    @patch('deploy.geo.requests.get', side_effect=AssertionError('部署不得联网定位'))
    def test_local_channels_stay_on_own_github_without_location_lookup(self, get):
        for config_module in (deploy_config, windows_config):
            for branch in ('essex', 'dev_essex'):
                with self.subTest(module=config_module.__name__, branch=branch):
                    config = self.make_config(config_module, branch=branch)
                    config.config_redirect()
                    config.config_redirect()
                    self.assertEqual(config.Repository, 'https://github.com/NieRMHY/ALAS-NieRMHY.git')
                    self.assertEqual(config.config['Repository'], config.Repository)
                    self.assertEqual(config.Branch, branch)
                    self.assertFalse(getattr(config, 'GitOverCdn', False))
        get.assert_not_called()

    def test_old_repositories_and_aliases_migrate_to_local_channels(self):
        repositories = (
            'global', 'cn', 'cnb', 'gitcode',
            'https://github.com/wess09/AzurPilot.git/',
            'git://git.pull/AzurPilot',
            'https://cnb.cool/AzurPilot/AzurPilot',
            'https://gitcode.com/ddl2/AzurPilot',
            'https://gitcode.com/ddl2/AzurLaneAutoScript.git',
            'https://gitee.com/LmeSzinc/AzurLaneAutoScript',
            'https://github.com/NieRMHY/ALAS-NieRMHY',
        )
        for config_module in (deploy_config, windows_config):
            for repository in repositories:
                for old_branch, branch in (('master', 'essex'), ('dev', 'dev_essex')):
                    with self.subTest(module=config_module.__name__, repository=repository, branch=old_branch):
                        config = self.make_config(config_module, repository, old_branch)
                        config.config_redirect()
                        self.assertEqual(config.Repository, deploy_config.GITHUB_REPOSITORY)
                        self.assertEqual(config.config['Repository'], config.Repository)
                        self.assertEqual(config.Branch, branch)
                        self.assertEqual(config.config['Branch'], branch)

    def test_custom_repository_and_feature_branch_are_preserved(self):
        for config_module in (deploy_config, windows_config):
            for repository, branch in (('https://github.com/example/custom', 'master'),
                                       (config_module.GITHUB_REPOSITORY, 'feature/local')):
                with self.subTest(module=config_module.__name__, repository=repository):
                    config = self.make_config(config_module, repository, branch)
                    config.config_redirect()
                    self.assertEqual(config.Repository, repository)
                    self.assertEqual(config.Branch, branch)

    def test_all_templates_default_to_own_repository_and_stable_channel(self):
        files = [Path('deploy/template'), Path('deploy/Windows/template.yaml')]
        files.extend(Path('config').glob('deploy.template*.yaml'))
        self.assertEqual(len(files), 10)
        for file in files:
            with self.subTest(file=file):
                values = poor_yaml_read(str(file))
                self.assertEqual(values['Repository'], deploy_config.GITHUB_REPOSITORY)
                self.assertEqual(values['Branch'], 'essex')
                self.assertFalse(values['CDN'])
        for config_module in (deploy_config, windows_config):
            self.assertEqual(config_module.ConfigModel.Repository, deploy_config.GITHUB_REPOSITORY)
            self.assertEqual(config_module.ConfigModel.Branch, 'essex')

    def test_windows_legacy_git_deployer_remains_deleted(self):
        self.assertFalse(Path('deploy/Windows/git.py').exists())

    @patch('deploy.geo.requests.get', side_effect=AssertionError('Git 更新不得请求云端接口'))
    def test_git_update_uses_selected_local_channel(self, get):
        for branch in ('essex', 'dev_essex'):
            with self.subTest(branch=branch):
                manager = object.__new__(deploy_git.GitManager)
                manager.git = 'git'
                manager.Repository = deploy_config.GITHUB_REPOSITORY
                manager.Branch = branch
                manager.GitProxy = None
                manager.SSLVerify = True
                with patch.object(manager, 'execute', return_value=True) as execute, \
                        patch.object(deploy_git.os.path, 'exists', return_value=False):
                    manager.git_install()
                commands = [call.args[0] for call in execute.call_args_list]
                self.assertIn(f'"git" remote set-url origin {manager.Repository}', commands)
                self.assertIn(f'"git" fetch origin {branch}', commands)
                self.assertIn(f'"git" reset --hard origin/{branch}', commands)
                self.assertIn(f'"git" pull --ff-only origin {branch}', commands)
        get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
