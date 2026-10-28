import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from extract_source import extract_source


class DeploymentArchiveTests(unittest.TestCase):
    def archive(self, directory, names):
        filename = Path(directory) / 'source.tar.gz'
        with tarfile.open(filename, 'w:gz') as archive:
            for name in names:
                content = b'revision = "real_revision"\n'
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        return filename

    def test_metadata_is_omitted_and_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'extracted'
            source = self.archive(directory, [
                './._.', 'backend/alembic/versions/._0001.py',
                '__MACOSX/backend/alembic/versions/0001.py',
                'backend/alembic/versions/0001.py', 'backend/.env.example',
            ])
            extract_source(source, destination)
            self.assertEqual(sorted(str(path.relative_to(destination)) for path in destination.rglob('*') if path.is_file()),
                             ['backend/.env.example', 'backend/alembic/versions/0001.py'])
            self.assertEqual((destination / 'backend/alembic/versions/0001.py').read_text(), 'revision = "real_revision"\n')

    def test_unsafe_paths_are_rejected_before_extraction(self):
        for name in ['../escaped.py', '/absolute.py', '__MACOSX/../escaped.py', 'backend/.env']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / 'extracted'
                source = self.archive(directory, ['safe.py', name])
                with self.assertRaises(ValueError):
                    extract_source(source, destination)
                self.assertFalse(destination.exists())

    def test_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'source.tar'
            with tarfile.open(filename, 'w') as archive:
                link = tarfile.TarInfo('backend/link')
                link.type = tarfile.SYMTYPE
                link.linkname = '/etc/passwd'
                archive.addfile(link)
            with self.assertRaises(ValueError):
                extract_source(filename, Path(directory) / 'extracted')


if __name__ == '__main__':
    unittest.main()
