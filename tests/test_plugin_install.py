"""Explicit runtime installation, separate from server startup."""
import json
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).parents[1]


def test_pdf_import_keeps_mcp_stdout_clean():
    import sys
    result = subprocess.run([sys.executable, '-c', 'import endnote_mcp.pdf_indexer'],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''


def fake_uv(tmp_path, failure=False):
    uv = tmp_path / 'uv executable'
    bins = tmp_path / 'runtime bin'
    bins.mkdir()
    executable = bins / 'chatgpt-endnote-mcp'
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "chatgpt-endnote-mcp, version 1.4.6"\n')
    executable.chmod(0o755)
    log = tmp_path / 'arguments'
    uv.write_text('''#!/bin/sh
if [ "$2" = "dir" ]; then printf '%s\\n' "$TEST_BIN"; exit 0; fi
printf '%s\\n' "$@" > "$TEST_LOG"
exit "${TEST_EXIT:-0}"
''')
    uv.chmod(0o755)
    env = {**os.environ, 'CHATGPT_ENDNOTE_MCP_UV':str(uv), 'TEST_BIN':str(bins),
           'TEST_LOG':str(log), 'TEST_EXIT':'1' if failure else '0'}
    return env, log


@pytest.mark.skipif(os.name == 'nt', reason='Unix installer; native equivalent in test_windows.py')
def test_installer_uses_plugin_source_and_keeps_flags_explicit(tmp_path):
    import shutil
    root = tmp_path / 'plugin with spaces'
    (root / 'scripts').mkdir(parents=True)
    script = root / 'scripts/install-desktop.sh'
    shutil.copy2(ROOT / 'scripts/install-desktop.sh', script)
    env, log = fake_uv(tmp_path)
    result = subprocess.run(['sh', str(script)], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ['tool', 'install', str(root)]
    result = subprocess.run(['sh', str(script), '--semantic', '--replace'], env=env,
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ['tool', 'install', '--force', str(root)+'[semantic]']


@pytest.mark.skipif(os.name == 'nt', reason='Unix installer; native equivalent in test_windows.py')
def test_installer_stops_on_missing_uv_and_install_failure(tmp_path):
    env, log = fake_uv(tmp_path, failure=True)
    result = subprocess.run(['sh', str(ROOT / 'scripts/install-desktop.sh')], env=env,
                            text=True, capture_output=True)
    assert result.returncode == 1
    assert 'Runtime executable:' not in result.stdout
    env['CHATGPT_ENDNOTE_MCP_UV'] = str(tmp_path / 'missing uv')
    result = subprocess.run(['sh', str(ROOT / 'scripts/install-desktop.sh')], env=env,
                            text=True, capture_output=True)
    assert result.returncode == 127
    assert 'uv executable is unavailable' in result.stderr


def test_onboarding_resources_resolve_from_plugin_root():
    manifest = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
    onboarding = manifest['extensions']['com.openai']['onboardingSkill']
    assert (ROOT / onboarding).is_file()
    for key in ['logo', 'composerIcon']:
        assert (ROOT / manifest['interface'][key]).is_file()
    assert (ROOT / 'src/endnote_mcp/desktop_cli.py').is_file()
