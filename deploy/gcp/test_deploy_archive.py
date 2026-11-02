import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from extract_source import extract_source
import runtime


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

    def test_ocr_key_is_installed_privately_and_transfer_file_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            environment.write_text('OCR_ENABLED=false\nOPENROUTER_API_KEY=\nPUBLIC_DOMAIN=example.com\n')
            key_file = Path(directory) / 'one-time-key'
            key_file.write_text('sk-or-test-secret\n')
            with patch.object(runtime, 'SECRETS', secrets_dir), patch('builtins.print') as output:
                runtime.enable_ocr(key_file)
            self.assertFalse(key_file.exists())
            self.assertEqual(environment.read_text(), 'OCR_ENABLED=true\nOPENROUTER_API_KEY=sk-or-test-secret\nPUBLIC_DOMAIN=example.com\n')
            self.assertEqual(environment.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('sk-or-test-secret', str(output.call_args))

    def test_ocr_key_requires_exactly_one_setting_and_removes_transfer_file(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original = 'OCR_ENABLED=false\nOPENROUTER_API_KEY=\nOPENROUTER_API_KEY=\n'
            environment.write_text(original)
            key_file = Path(directory) / 'one-time-key'
            key_file.write_text('sk-or-test-secret')
            with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                runtime.enable_ocr(key_file)
            self.assertFalse(key_file.exists())
            self.assertEqual(environment.read_text(), original)


if __name__ == '__main__':
    unittest.main()
