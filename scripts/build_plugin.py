"""Convert the built source distribution into a reproducible local-plugin ZIP."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile


def build(sdist, output, platform='unix'):
    if platform not in ('unix', 'windows'):
        raise ValueError('platform must be unix or windows')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(sdist) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for member in sorted(source.getmembers(), key=lambda item: item.name):
            if not member.isfile():
                continue
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or len(path.parts) < 2:
                raise ValueError(f'Unsafe source path: {member.name}')
            relative = PurePosixPath(*path.parts[1:])
            if relative.name == 'PKG-INFO':
                continue
            entry = zipfile.ZipInfo(str(relative), date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (member.mode & 0o777) << 16
            content = source.extractfile(member).read()
            # A Windows checkout may contain CRLF even when Git stores LF.
            # Unix shells interpret those CR bytes as part of commands/options.
            if relative.suffix == '.sh':
                content = content.replace(b'\r\n', b'\n')
            if platform == 'windows' and str(relative) == '.mcp.json':
                common = json.loads(content)['mcpServers']['endnote']
                content = json.dumps({'mcpServers': {'endnote': {
                    'command': 'cmd.exe',
                    'args': ['/d', '/c', '.\\scripts\\launch-desktop.cmd'],
                    'startup_timeout_sec': 60,
                    'env_vars': common.get('env_vars', []),
                    'cwd': '.'}}}, indent=2).encode('utf-8')
            target.writestr(entry, content)
    return output


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    version = re.search(r'^version = "([^"]+)"', (root / 'pyproject.toml').read_text(), re.M).group(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdist', type=Path, default=root / 'dist' / f'chatgpt_endnote_mcp-{version}.tar.gz')
    parser.add_argument('--platform', choices=('unix', 'windows'), default='unix')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    suffix = '-windows' if args.platform == 'windows' else ''
    output = args.output or root / 'dist' / f'endnote-research-{version}{suffix}.zip'
    print(build(args.sdist, output, args.platform))
