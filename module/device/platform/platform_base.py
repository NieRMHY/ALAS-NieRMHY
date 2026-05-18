import os
import sys
import typing as t
import subprocess

from pydantic import BaseModel

from module.base.decorator import cached_property, del_cached_property
from module.device.connection import Connection
from module.device.method.utils import get_serial_pair
from module.device.platform.emulator_base import EmulatorInstanceBase, EmulatorManagerBase, remove_duplicated_path
from module.logger import logger
from module.map.map_grids import SelectedGrids


class EmulatorInfo(BaseModel):
    emulator: str = ''
    name: str = ''
    path: str = ''

    # For APIs of chinac.com, a phone cloud platform.
    # access_key: SecretStr = ''
    # secret: SecretStr = ''


def serial_to_id(serial: str):
    """
    Predict instance ID from serial
    E.g.
        "127.0.0.1:16384" -> 0
        "127.0.0.1:16416" -> 1
        Port from 16414 to 16418 -> 1

    Returns:
        int: instance_id, or None if failed to predict
    """
    try:
        port = int(serial.split(':')[1])
    except (IndexError, ValueError):
        return None
    index, offset = divmod(port - 16384 + 16, 32)
    offset -= 16
    if 0 <= index < 32 and offset in [-2, -1, 0, 1, 2]:
        return index
    else:
        return None


class PlatformBase(Connection, EmulatorManagerBase):
    """
    Base interface of a platform, platform can be various operating system or phone clouds.
    For each `Platform` class, the following APIs must be implemented.
    - all_emulators()
    - all_emulator_instances()
    - emulator_start()
    - emulator_stop()
    """

    def __init__(self, config, *, connect: bool = True):
        """
        Args:
            config: AzurLaneConfig or config name
            connect: Whether to immediately establish ADB connection.
        """
        if connect:
            super().__init__(config)
        else:
            from module.device.connection_attr import ConnectionAttr
            ConnectionAttr.__init__(self, config)

    def emulator_start(self):
        """
        Start a emulator, until startup completed.
        - Retry is required.
        - Using bored sleep to wait startup is forbidden.
        """
        logger.info(f'Current platform {sys.platform} does not support emulator_start, skip')

    def emulator_stop(self):
        """
        Stop a emulator.
        """
        logger.info(f'Current platform {sys.platform} does not support emulator_stop, skip')

    def run_remote_ssh_command(self, command=None):
        if not getattr(self.config, 'EmulatorInfo_EnableRemoteSSH', False):
            logger.info('Remote SSH is not enabled (EnableRemoteSSH=False), skip')
            return

        host = self.config.EmulatorInfo_RemoteSSHHost
        port = self.config.EmulatorInfo_RemoteSSHPort
        user = self.config.EmulatorInfo_RemoteSSHUser
        key = getattr(self.config, 'EmulatorInfo_RemoteSSHPublicKey', '')

        if not command:
            logger.warning('No SSH command provided, skip')
            return

        if not host:
            logger.warning(f'RemoteSSHHost is empty, skip remote SSH command: {command}')
            return

        logger.hr('Remote SSH Command', level=1)
        target = f'{user}@{host}' if user else host
        # -n: Redirects stdin from /dev/null
        # -T: Disable pseudo-terminal allocation
        # BatchMode to avoid hanging on password prompts
        cmd = ['ssh', '-n', '-T', '-p', str(port), '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']

        key_file = None
        if key and len(key) > 50:
            import tempfile
            try:
                fd, key_file = tempfile.mkstemp()
                with os.fdopen(fd, 'w') as f:
                    f.write(key.strip() + '\n')

                if os.name == 'nt':
                    user_env = os.environ.get('USERNAME')
                    subprocess.run(['icacls', key_file, '/reset'], capture_output=True)
                    subprocess.run(['icacls', key_file, '/inheritance:r'], capture_output=True)
                    subprocess.run(['icacls', key_file, '/grant:r', f'{user_env}:F'], capture_output=True)
                else:
                    os.chmod(key_file, 0o600)

                cmd += ['-i', key_file]
                logger.info(f'Using provided private key for authentication')
            except Exception as e:
                logger.error(f'Failed to create or secure temporary key file: {e}')

        cmd += [target, command]
        logger.info(f'Executing remote command: {" ".join(cmd)}')

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # Store stderr to show only if it fails
            stderr_content = []

            import threading

            def collect_stderr():
                for line in process.stderr:
                    stderr_content.append(line.strip())

            def collect_stdout():
                for line in process.stdout:
                    logger.info(f'Remote: {line.strip()}')

            stderr_thread = threading.Thread(target=collect_stderr)
            stdout_thread = threading.Thread(target=collect_stdout)
            stderr_thread.start()
            stdout_thread.start()

            try:
                # Main thread waits for the process to exit
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                logger.error('Remote SSH command timed out after 30 seconds')
            finally:
                stderr_thread.join(timeout=5)
                stdout_thread.join(timeout=5)

            if process.returncode == 0:
                logger.info('Remote command executed successfully')
            else:
                logger.error(f'Remote command failed with return code {process.returncode}')
                for line in stderr_content:
                    logger.error(f'Remote Error: {line}')
        except Exception as e:
            logger.error(f'Failed to execute remote SSH command: {e}')
        finally:
            if key_file and os.path.exists(key_file):
                try:
                    os.remove(key_file)
                except Exception as e:
                    logger.error(f'Failed to remove temporary key file: {e}')

    @cached_property
    def emulator_info(self) -> EmulatorInfo:
        emulator = self.config.EmulatorInfo_Emulator
        if emulator == 'auto':
            emulator = ''

        def parse_info(value):
            if isinstance(value, str):
                value = value.strip().replace('\n', '')
                if value in ['None', 'False', 'True']:
                    value = ''
                return value
            else:
                return ''

        name = parse_info(self.config.EmulatorInfo_name)
        path = parse_info(self.config.EmulatorInfo_path)

        return EmulatorInfo(
            emulator=emulator,
            name=name,
            path=path,
        )

    @cached_property
    def emulator_instance(self) -> t.Optional[EmulatorInstanceBase]:
        """
        Returns:
            EmulatorInstanceBase: Emulator instance or None
        """
        data = self.emulator_info
        old_info = dict(
            emulator=data.emulator,
            path=data.path,
            name=data.name,
        )
        # Redirect emulator-5554 to 127.0.0.1:5555
        serial = self.serial
        port_serial, _ = get_serial_pair(self.serial)
        if port_serial is not None:
            serial = port_serial

        instance = self.find_emulator_instance(
            serial=serial,
            name=data.name,
            path=data.path,
            emulator=data.emulator,
        )

        # Write complete emulator data
        if instance is not None:
            new_info = dict(
                emulator=instance.type,
                path=instance.path,
                name=instance.name,
            )
            if new_info != old_info:
                with self.config.multi_set():
                    self.config.EmulatorInfo_Emulator = instance.type
                    self.config.EmulatorInfo_name = instance.name
                    self.config.EmulatorInfo_path = instance.path
                del_cached_property(self, 'emulator_info')

        return instance

    def find_emulator_instance(
            self,
            serial: str,
            name: str = None,
            path: str = None,
            emulator: str = None
    ) -> t.Optional[EmulatorInstanceBase]:
        """
        Args:
            serial: Serial like "127.0.0.1:5555"
            name: Instance name like "Nougat64"
            path: Emulator install path like "C:/Program Files/BlueStacks_nxt/HD-Player.exe"
            emulator: Emulator type defined in Emulator class, like "BlueStacks5"

        Returns:
            EmulatorInstance: Emulator instance or None if no instances not found.
        """
        logger.hr('Find emulator instance', level=2)
        if emulator == 'SSH':
            instance = EmulatorInstanceBase(
                serial=serial,
                name=name or '',
                path=path or '',
            )
            # Monkey patch type for SSH instance
            instance.__dict__['type'] = 'SSH'
            logger.hr('Emulator instance', level=2)
            logger.info(f'Found emulator instance (SSH): {instance}')
            return instance

        instances = SelectedGrids(self.all_emulator_instances)
        for instance in instances:
            logger.info(instance)
        search_args = dict(serial=serial)

        # Search by serial
        select = instances.select(**search_args)
        if select.count == 0:
            logger.warning(f'No emulator instance with {search_args}, serial invalid')
            return None
        if select.count == 1:
            instance = select[0]
            logger.hr('Emulator instance', level=2)
            logger.info(f'Found emulator instance: {instance}')
            return instance

        # Additional fixup for MuMu12
        # MuMu12 may have 127.0.0.1:7555 in vbox config but user setting serial=127.0.0.1:16xxx
        # If that happens, we check if serial pairs with instance_id
        instance_id = serial_to_id(self.serial)
        if instance_id is not None:
            select = instances.select(MuMuPlayer12_id=instance_id)
            # No logs for if select.count == 1:
            # because this is just a trial
            if select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # search by emulator type first, which is the easiest setting for user to setup, so more trustworthy
        # Multiple instances in given serial, name and path, search by emulator
        if emulator:
            search_args['type'] = emulator
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, type invalid')
                search_args.pop('type')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # Multiple instances in given serial, search by name
        if name:
            search_args['name'] = name
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, name invalid')
                search_args.pop('name')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # Multiple instances in given serial and name, search by path
        if path:
            search_args['path'] = path
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, path invalid')
                search_args.pop('path')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # Still too many instances, search from running emulators
        running = remove_duplicated_path(list(self.iter_running_emulator()))
        logger.info('Running emulators')
        for exe in running:
            logger.info(exe)
        if len(running) == 1:
            logger.info('Only one running emulator')
            # Same as searching path
            search_args['path'] = running[0]
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f'No emulator instances with {search_args}, path invalid')
                search_args.pop('path')
            elif select.count == 1:
                instance = select[0]
                logger.hr('Emulator instance', level=2)
                logger.info(f'Found emulator instance: {instance}')
                return instance

        # Still too many instances
        logger.warning(f'Found multiple emulator instances with {search_args}')
        return None
