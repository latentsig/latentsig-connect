#!/usr/bin/env python3
"""Validate deployment archives and omit macOS filesystem metadata."""
from pathlib import PurePosixPath
import sys
import tarfile


def extract_source(filename, destination):
    with tarfile.open(filename) as archive:
        source_members = []
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Archive must contain only regular source files and directories.')
            if any(part in {'.git', '.env'} or part.startswith('.env.') and part != '.env.example' for part in path.parts):
                raise ValueError('Archive contains environment or repository metadata.')
            if any(part.startswith('._') or part == '__MACOSX' for part in path.parts):
                continue
            source_members.append(member)
        archive.extractall(destination, members=source_members, filter='data')


if __name__ == '__main__':
    try:
        extract_source(*sys.argv[1:])
    except ValueError as error:
        raise SystemExit(str(error)) from None
