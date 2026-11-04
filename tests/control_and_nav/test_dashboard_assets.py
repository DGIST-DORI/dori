"""Serve colcon-installed dashboard files without permitting path escapes."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import httpx

PACKAGE = Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_dashboard/dori_dashboard'
sys.path.insert(0, str(PACKAGE))


class DashboardAssetTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'web/dist'
        self.installed = self.root / 'install/dori_dashboard/share/dori_dashboard/web'
        for folder in (self.source / 'assets', self.installed / 'assets'):
            folder.mkdir(parents=True)
        self.files = {
            'index.html': '<html><script src="/assets/app.js"></script></html>',
            'assets/app.js': 'document.body.textContent = "DORI Dashboard";',
            'assets/app.css': 'body { color: blue; }',
        }
        for name, content in self.files.items():
            (self.source / name).write_text(content)
            (self.installed / name).symlink_to(self.source / name)
        spec = importlib.util.spec_from_file_location('dashboard_assets_under_test', PACKAGE / 'backend_api.py')
        self.backend = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {spec.name: self.backend}), patch.object(sys, 'argv', [
            'backend_api.py', '--repo-root', str(self.root), '--web-dir', str(self.installed),
        ]):
            spec.loader.exec_module(self.backend)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.backend.app), base_url='https://dash.test')
        self.addAsyncCleanup(self.client.aclose)

    async def test_symlink_installed_html_assets_and_spa_routes(self):
        for path, name in [('/', 'index.html'), ('/settings', 'index.html'),
                           ('/index.html', 'index.html'), ('/assets/app.js', 'assets/app.js'),
                           ('/assets/app.css', 'assets/app.css')]:
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.text, self.files[name])
        self.assertIn('javascript', (await self.client.get('/assets/app.js')).headers['content-type'])
        self.assertIn('text/css', (await self.client.get('/assets/app.css')).headers['content-type'])
        self.assertIn('no-store', (await self.client.get('/')).headers['cache-control'])
        self.assertEqual((await self.client.get('/assets/missing.js')).status_code, 404)
        self.assertEqual((await self.client.get('/api/missing')).status_code, 404)

    async def test_traversal_and_symlinks_outside_corresponding_build_file_are_rejected(self):
        secret = self.root / 'private.js'
        secret.write_text('private')
        (self.installed / 'assets/private.js').symlink_to(secret)
        # Even an allowed-looking build path must not resolve outside web/dist.
        (self.source / 'assets/leak.js').symlink_to(secret)
        (self.installed / 'assets/leak.js').symlink_to(self.source / 'assets/leak.js')
        (self.installed / 'assets/alias.js').symlink_to(self.source / 'assets/app.js')
        for path in ('/assets/private.js', '/assets/leak.js', '/assets/alias.js',
                     '/assets/%2e%2e/private.js', '/%2e%2e/private.js'):
            self.assertEqual((await self.client.get(path)).status_code, 404, path)
        (self.installed / 'index.html').unlink()
        (self.installed / 'index.html').symlink_to(secret)
        for path in ('/', '/settings', '/index.html'):
            self.assertEqual((await self.client.get(path)).status_code, 404, path)
