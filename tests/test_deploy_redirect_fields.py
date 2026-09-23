"""远程访问公开字段应进入两个部署模型，并被实际提供器使用。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import config as deploy_config
from deploy.Windows import config as windows_config
from module.runtime.remote_access import SSHRemoteAccessProvider
from module.runtime.setting import State


class DeployRedirectFieldsTests(unittest.TestCase):
    def test_model_defaults_match_public_settings(self):
        for module in (deploy_config, windows_config):
            self.assertIsNone(module.ConfigModel.AllowedRedirectHosts)
            self.assertEqual(module.ConfigModel.MaxRedirects, 2)

    def test_saved_fields_reach_runtime_provider(self):
        for module in (deploy_config, windows_config):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                template = root / 'template.yaml'
                file = root / 'deploy.yaml'
                text = ('Repository: https://example.invalid/custom\nBranch: master\n'
                        'AllowedRedirectHosts: null\nMaxRedirects: 2\n')
                template.write_text(text)
                file.write_text(text.replace('AllowedRedirectHosts: null',
                                             'AllowedRedirectHosts: custom.example')
                                    .replace('MaxRedirects: 2', 'MaxRedirects: 0'))
                template_patch = (patch.object(module, 'get_deploy_template', return_value=str(template))
                                  if module is deploy_config
                                  else patch.object(module, 'DEPLOY_TEMPLATE', str(template)))
                with template_patch, patch.object(module.DeployConfig, 'show_config'), \
                        patch.object(module, 'get_country_code', side_effect=AssertionError('不得联网')):
                    config = module.DeployConfig(str(file))
                self.assertEqual(config.AllowedRedirectHosts, 'custom.example')
                self.assertEqual(config.MaxRedirects, 0)
                with patch.object(State, '_deploy_config_', config, create=True):
                    provider = SSHRemoteAccessProvider()
                    self.assertEqual(provider._max_redirects(), 0)
                    self.assertEqual(provider._redirect_hosts('primary.example'), ['custom.example'])

    def test_windows_template_exposes_redirect_fields(self):
        from deploy.Windows.utils import poor_yaml_read

        values = poor_yaml_read('deploy/Windows/template.yaml')
        self.assertIn('AllowedRedirectHosts', values)
        self.assertIsNone(values['AllowedRedirectHosts'])
        self.assertEqual(values['MaxRedirects'], 2)


if __name__ == '__main__':
    unittest.main()
