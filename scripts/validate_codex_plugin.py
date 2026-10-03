"""Verify native Codex installation and MCP discovery in an isolated profile.

Does not create a chat, run a model, or alter the user's existing Codex profile.
GUI onboarding remains a separate release gate.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading


def validate(args):
    profile = args.output_dir.resolve()
    if profile.exists():
        raise RuntimeError('Choose a new isolated acceptance profile directory.')
    profile.mkdir(parents=True)
    executable = args.codex or shutil.which('codex')
    if not executable:
        raise RuntimeError('Codex CLI with plugin support is required.')
    env = {**os.environ, 'CODEX_HOME': str(profile),
           'CHATGPT_ENDNOTE_MCP_COMMAND': str(args.runtime.resolve()),
           'CHATGPT_ENDNOTE_MCP_CONFIG': str(args.config.resolve())}
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    for arguments in (['plugin', 'marketplace', 'add', str(args.plugin.resolve())],
                      ['plugin', 'add', 'endnote-research@endnote-local', '--json']):
        subprocess.run([executable, *arguments], env=env, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    with (profile / 'app-server.log').open('w', encoding='utf-8') as error:
        process = subprocess.Popen([executable, 'app-server'], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error,
            text=True, encoding='utf-8', creationflags=flags)
        responses = queue.Queue()
        def read():
            for line in process.stdout:
                responses.put(line)
            responses.put(None)
        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        def call(identifier, method, params):
            process.stdin.write(json.dumps({'id': identifier, 'method': method, 'params': params}) + '\n')
            process.stdin.flush()
            while True:
                line = responses.get(timeout=90)
                if line is None:
                    raise RuntimeError('Codex app-server closed before responding.')
                result = json.loads(line)
                if result.get('id') == identifier:
                    if 'error' in result:
                        raise RuntimeError(result['error'])
                    return result['result']
        try:
            initialized = call(1, 'initialize', {'clientInfo': {'name': 'endnote-validation', 'version': '1.0'}, 'capabilities': {'experimentalApi': True}})
            process.stdin.write('{"method":"initialized"}\n')
            process.stdin.flush()
            result = call(2, 'mcpServerStatus/list', {})
            servers = [s for s in result['data'] if s['name'] == 'endnote']
            if len(servers) != 1 or servers[0].get('toolsError'):
                raise RuntimeError('EndNote MCP discovery failed: ' + str(servers))
            tools = sorted(servers[0]['tools'])
            from endnote_mcp.desktop_runtime import TOOLS
            if set(tools) != TOOLS:
                raise RuntimeError('Codex did not discover the expected 11 EndNote tools.')
            report = {'codex': initialized['userAgent'], 'plugin_installed': True,
                      'tools': tools, 'gui_onboarding_verified': False}
            (profile / 'codex-summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2))
        finally:
            process.terminate()
            process.wait(timeout=10)
            worker.join(timeout=10)
            process.stdin.close()
            process.stdout.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--codex')
    validate(parser.parse_args())
