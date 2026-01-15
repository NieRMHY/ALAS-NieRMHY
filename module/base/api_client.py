"""
API 客户端模块
负责与 alas-apiv2.nanoda.work 进行所有HTTP交互
包括Bug日志上报和CL1数据提交
"""
import threading
from typing import Any, Dict

import requests

from module.base.device_id import get_device_id
from module.logger import logger


class ApiClient:
    """统一的API客户端"""
    
    BUG_LOG_ENDPOINT = 'https://alas-apiv2.nanoda.work/api/post/bug'
    CL1_DATA_ENDPOINT = 'https://alas-apiv2.nanoda.work/api/telemetry'
    
    @staticmethod
    def _submit_bug_log(content: str, log_type: str):
        """
        内部方法：提交Bug日志
        
        Args:
            content: 日志内容
            log_type: 日志类型
        """
        try:
            device_id = get_device_id()
            data = {
                'device_id': device_id,
                'log_type': log_type,
                'log_content': content,
            }
            
            response = requests.post(
                ApiClient.BUG_LOG_ENDPOINT,
                json=data,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f'Bug log submitted: {content[:50]}...')
            else:
                logger.warning(f'Failed to submit bug log, status: {response.status_code}')
        except Exception as e:
            logger.warning(f'Failed to submit bug log: {e}')
    
    @classmethod
    def submit_bug_log(cls, content: str, log_type: str = 'warning', enabled: bool = True):
        """
        提交Bug日志（异步）
        
        Args:
            content: 日志内容
            log_type: 日志类型，默认为'warning'
            enabled: 是否启用上报，可传入 config.DropRecord_BugReport 配置值
        """
        if not enabled:
            return
        threading.Thread(
            target=cls._submit_bug_log,
            args=(content, log_type),
            daemon=True
        ).start()
    
    @staticmethod
    def _submit_cl1_data(data: Dict[str, Any], timeout: int):
        """
        内部方法：提交CL1数据
        
        Args:
            data: 数据字典
            timeout: 超时时间（秒）
        """
        try:
            # 如果没有任何战斗数据,不提交
            if data.get('battle_count', 0) == 0:
                logger.info('No CL1 battle data to submit')
                return
            
            logger.info(f'Submitting CL1 data for {data.get("month", "unknown")}...')
            logger.attr('battle_count', data.get('battle_count', 0))
            logger.attr('akashi_encounters', data.get('akashi_encounters', 0))
            logger.attr('akashi_probability', f"{data.get('akashi_probability', 0):.2%}")
            
            response = requests.post(
                ApiClient.CL1_DATA_ENDPOINT,
                json=data,
                timeout=timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                logger.info('✓ CL1 data submitted successfully')
            else:
                logger.warning(f'✗ CL1 data submission failed: HTTP {response.status_code}')
                logger.warning(f'Response: {response.text[:200]}')
        
        except requests.exceptions.Timeout:
            logger.warning(f'CL1 data submission timeout after {timeout}s')
        except requests.exceptions.RequestException as e:
            logger.warning(f'CL1 data submission failed: {e}')
        except Exception as e:
            logger.exception(f'Unexpected error during CL1 data submission: {e}')
    
    @classmethod
    def submit_cl1_data(cls, data: Dict[str, Any], timeout: int = 10):
        """
        提交CL1统计数据（异步）
        
        Args:
            data: 包含device_id和统计数据的字典
            timeout: 请求超时时间（秒），默认10秒
        """
        threading.Thread(
            target=cls._submit_cl1_data,
            args=(data, timeout),
            daemon=True
        ).start()
