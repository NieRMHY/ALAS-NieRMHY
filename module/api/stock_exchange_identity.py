"""实例持久身份与签名；只确认身份和请求完整性，不验证游戏数据真实性。"""
import base64
import hashlib
import json
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from module.api.protocol import ApiError
from module.runtime.game_data import GameDataProtector
from module.config.transaction import config_transaction


def load_identity(root, instance):
    protection = GameDataProtector(root)
    identity = protection.resolve(instance)
    with config_transaction(protection.file_path('identities/' + identity + '.json')):
        key = _load_key(protection, instance, identity)
    protection.relocate_scheduler(instance, identity)
    return identity, key


def _load_key(protection, instance, identity):
    """首次生成签名私钥也纳入文件事务，多个进程必须得到同一把私钥。"""
    name = 'identities/' + identity + '.json'
    data = protection.read_file(name)
    legacy = protection.record(identity)['legacy']
    path = protection.directory / 'identities' / (hashlib.sha256(instance.encode()).hexdigest() + '.json')
    if data is None and legacy:
        try:
            data = json.loads(path.read_bytes())
        except (OSError, ValueError):
            raise ApiError('STOCK_IDENTITY_DAMAGED', '旧实例交易身份损坏，请恢复完整备份') from None
    if data is None:
        key = Ed25519PrivateKey.generate()
        data = {'instanceId': identity, 'privateKey': base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()}
        protection.write_file(name, data)
    try:
        if str(uuid.UUID(data['instanceId'])) != identity:
            raise ValueError()
        key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(data['privateKey'], validate=True))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ApiError('STOCK_IDENTITY_DAMAGED', '实例交易身份损坏，请恢复身份备份，不能自动创建新身份') from None
    if legacy:
        if not protection.file_path(name).exists():
            protection.write_file(name, data)
        from module.runtime.account_vault import AccountVault
        AccountVault.wipe_file(path)
        with protection.transaction() as (state, _):
            state['instances'][identity]['legacy'] = False
    return key


def binding_key(instance_id, key):
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    return hashlib.sha256((public + '\n' + instance_id).encode()).hexdigest()


def make_report(instance_id, key, total, observed_at):
    """签名仅用于实例身份及请求完整性，不验证行动力真实性。"""
    import time
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    result = {'instanceId': instance_id, 'publicKey': public, 'actionPoints': total,
              'observedAt': observed_at, 'issuedAt': int(time.time())}
    text = f"mmex-instance-v1\n{instance_id}\n{public}\n{total}\n{observed_at}\n{result['issuedAt']}\n"
    result['signature'] = base64.b64encode(key.sign(text.encode())).decode()
    return result
