"""提供完整前端构建目录，区分页面导航与静态资源请求。"""
import mimetypes
from pathlib import PurePosixPath

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

# 浏览器对 ES module 与样式表做强制 MIME 检查，类型不对就直接拒绝执行，前端整片白屏。
# Windows 上 Python 的 mimetypes 会读注册表的文件关联（而且直接覆盖标准表），
# 系统里 .js 被关联成 text/plain 的机器就会白屏，所以这里写死正确的映射。
WEB_MIME_TYPES = {
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.css': 'text/css',
}


def ensure_static_mime_types() -> None:
    """把静态资源的 MIME 写进标准映射，覆盖系统注册表里的错误关联。"""
    for ext, media_type in WEB_MIME_TYPES.items():
        mimetypes.add_type(media_type, ext)


ensure_static_mime_types()


class FrontendFiles(StaticFiles):
    """保留 SPA 页面回退，同时让缺失资源返回真实的 404。"""

    async def get_response(self, path, scope):
        # 构建指纹等内部文件不属于公开资源；路径越界仍由 StaticFiles 拦截。
        if any(part.startswith('.') and part not in ('.', '..') for part in PurePosixPath(path).parts):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or PurePosixPath(path).suffix:
                raise
            response = await super().get_response('index.html', scope)
        # public 资源名称不带内容哈希，更新后必须向服务端重新验证缓存。
        response.headers['Cache-Control'] = 'no-cache'
        return response
