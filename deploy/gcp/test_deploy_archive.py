import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
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
            self.assertEqual(sorted(path.relative_to(destination).as_posix() for path in destination.rglob('*') if path.is_file()),
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

    def test_ollama_selection_preserves_hosted_key_and_unrelated_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            environment.write_bytes(
                b'# keep this comment\r\nOCR_ENABLED=false\r\n'
                b'OPENROUTER_API_KEY=existing-secret\r\nPUBLIC_DOMAIN=example.com\r\n'
                b'CONSENT_NOTICE_VERSION=older-v1\r\n')
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('ollama')
            result = environment.read_bytes()
            self.assertIn(b'OPENROUTER_API_KEY=existing-secret\r\n', result)
            self.assertIn(b'PUBLIC_DOMAIN=example.com\r\n', result)
            self.assertIn(b'CONSENT_NOTICE_VERSION=older-v1\r\n', result)
            self.assertIn(b'OCR_PROVIDER=ollama\r\n', result)
            self.assertIn(b'OLLAMA_BASE_URL=http://ollama:11434\r\n', result)
            self.assertIn(b'OLLAMA_MODEL=openbmb/minicpm-ocr1.0\r\n', result)
            self.assertIn(b'OCR_TIMEOUT_SECONDS=85\r\n', result)
            self.assertIn(b'OCR_MAX_RETRIES=0\r\n', result)
            if os.name != 'nt':
                self.assertEqual(environment.stat().st_mode & 0o777, 0o600)

    def test_provider_switches_both_ways_and_repeated_choice_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            environment.write_text(
                'OPENROUTER_API_KEY=private-key\nOCR_ENABLED=false\nOCR_PROVIDER=ollama\n'
                'OLLAMA_BASE_URL=http://custom-ollama:11434\nOLLAMA_MODEL=custom:model\n'
                'OCR_TIMEOUT_SECONDS=91\nOCR_MAX_RETRIES=2\n')
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('openrouter')
                runtime.select_ocr_provider('ollama')
                selected_ollama = environment.read_bytes()
                runtime.select_ocr_provider('ollama')
            self.assertEqual(environment.read_bytes(), selected_ollama)
            self.assertIn(b'OPENROUTER_API_KEY=private-key', selected_ollama.splitlines())
            self.assertIn(b'OCR_PROVIDER=ollama', selected_ollama.splitlines())
            self.assertIn(b'OLLAMA_BASE_URL=http://custom-ollama:11434', selected_ollama.splitlines())
            self.assertIn(b'OLLAMA_MODEL=custom:model', selected_ollama.splitlines())
            self.assertIn(b'OCR_TIMEOUT_SECONDS=91', selected_ollama.splitlines())
            self.assertIn(b'OCR_MAX_RETRIES=2', selected_ollama.splitlines())
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('openrouter')
            lines = environment.read_bytes().splitlines()
            self.assertIn(b'OCR_PROVIDER=openrouter', lines)
            self.assertIn(b'OPENROUTER_API_KEY=private-key', lines)

    def test_vertex_selection_defaults_model_and_preserves_other_provider_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            environment.write_text(
                'OCR_ENABLED=false\nOCR_PROVIDER=ollama\n'
                'GOOGLE_CLOUD_PROJECT=refined-outlet-249712\n'
                'OPENROUTER_API_KEY=private-key\nOLLAMA_MODEL=custom:model\n')
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('vertex')
                selected = environment.read_bytes()
                runtime.select_ocr_provider('vertex')
            self.assertEqual(environment.read_bytes(), selected)
            lines = selected.splitlines()
            self.assertIn(b'OCR_ENABLED=true', lines)
            self.assertIn(b'OCR_PROVIDER=vertex', lines)
            self.assertIn(b'GOOGLE_CLOUD_PROJECT=refined-outlet-249712', lines)
            self.assertIn(b'VERTEX_AI_MODEL=gemini-3.5-flash-lite', lines)
            self.assertIn(b'OPENROUTER_API_KEY=private-key', lines)
            self.assertIn(b'OLLAMA_MODEL=custom:model', lines)

    def test_vertex_selection_rejects_missing_project_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            for original in [
                b'OCR_PROVIDER=ollama\n',
                b'OCR_PROVIDER=ollama\nGOOGLE_CLOUD_PROJECT=\n',
                b'OCR_PROVIDER=ollama\nGOOGLE_CLOUD_PROJECT="" # not configured\n',
                b'OCR_PROVIDER=ollama\nGOOGLE_CLOUD_PROJECT=$MISSING_PROJECT\n',
            ]:
                with self.subTest(original=original):
                    environment.write_bytes(original)
                    with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                        runtime.select_ocr_provider('vertex')
                    self.assertEqual(environment.read_bytes(), original)

    def test_vertex_selection_populates_missing_project_from_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original = b'OCR_PROVIDER=ollama\nOPENROUTER_API_KEY=private-key\n'
            environment.write_bytes(original)
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('vertex', 'refined-outlet-249712')
            result = environment.read_bytes()
            lines = result.splitlines()
            self.assertIn(b'GOOGLE_CLOUD_PROJECT=refined-outlet-249712', lines)
            self.assertIn(b'VERTEX_AI_MODEL=gemini-3.5-flash-lite', lines)
            self.assertIn(b'OPENROUTER_API_KEY=private-key', lines)

    def test_vertex_selection_rejects_conflicting_project_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original = b'GOOGLE_CLOUD_PROJECT=existing-project\nOCR_PROVIDER=ollama\n'
            environment.write_bytes(original)
            with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                runtime.select_ocr_provider('vertex', 'refined-outlet-249712')
            self.assertEqual(environment.read_bytes(), original)

    def test_vertex_selection_rejects_invalid_project_id_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original = b'OCR_PROVIDER=ollama\n'
            environment.write_bytes(original)
            with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                runtime.select_ocr_provider('vertex', 'INVALID_PROJECT')
            self.assertEqual(environment.read_bytes(), original)

    def test_vertex_selection_with_matching_argument_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            project_line = b'GOOGLE_CLOUD_PROJECT="refined-outlet-249712" # existing\n'
            environment.write_bytes(project_line)
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('vertex', 'refined-outlet-249712')
                selected = environment.read_bytes()
                runtime.select_ocr_provider('vertex', 'refined-outlet-249712')
            self.assertEqual(environment.read_bytes(), selected)
            self.assertIn(project_line, selected)

    def test_vertex_selection_rejects_duplicate_project_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original = b'GOOGLE_CLOUD_PROJECT=first\nGOOGLE_CLOUD_PROJECT=second\n'
            environment.write_bytes(original)
            with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                runtime.select_ocr_provider('vertex')
            self.assertEqual(environment.read_bytes(), original)

    def test_vertex_selection_preserves_configured_model(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original_model = b'VERTEX_AI_MODEL=gemini-custom\n'
            environment.write_bytes(
                b'GOOGLE_CLOUD_PROJECT=refined-outlet-249712\n' + original_model)
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('vertex')
            self.assertIn(original_model, environment.read_bytes())
            self.assertNotIn(b'VERTEX_AI_MODEL=gemini-3.5-flash-lite\n', environment.read_bytes())

    def test_new_production_environment_defaults_to_free_self_hosted_ollama(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            with patch.object(runtime, 'SECRETS', secrets_dir), patch.object(
                runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=1)
            ):
                runtime.environment('example.com')
            result = (secrets_dir / 'production.env').read_text()
            self.assertIn('OCR_PROVIDER=ollama\n', result)
            self.assertIn('OLLAMA_MODEL=openbmb/minicpm-ocr1.0\n', result)
            self.assertIn('GOOGLE_CLOUD_PROJECT=refined-outlet-249712\n', result)
            self.assertIn('VERTEX_AI_MODEL=gemini-3.5-flash-lite\n', result)

    def test_ollama_selection_repairs_missing_or_out_of_range_budget_values(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            environment.write_text(
                'OCR_TIMEOUT_SECONDS=121\nOCR_MAX_RETRIES=invalid\n'
                'OLLAMA_BASE_URL=http://custom-ollama:11434\n')
            with patch.object(runtime, 'SECRETS', secrets_dir):
                runtime.select_ocr_provider('ollama')
            result = environment.read_text()
            self.assertIn('OCR_TIMEOUT_SECONDS=85\n', result)
            self.assertIn('OCR_MAX_RETRIES=0\n', result)
            self.assertIn('OLLAMA_BASE_URL=http://custom-ollama:11434\n', result)
            self.assertIn('OLLAMA_MODEL=openbmb/minicpm-ocr1.0\n', result)

    def test_openrouter_without_key_rejects_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            for key_line in [
                b'', b'OPENROUTER_API_KEY=\n', b'OPENROUTER_API_KEY=   \n',
                b'OPENROUTER_API_KEY="" # awaiting setup\n',
                b"OPENROUTER_API_KEY='' # awaiting setup\n",
                b'OPENROUTER_API_KEY=   # awaiting setup\n',
                b'OPENROUTER_API_KEY=${MISSING_KEY}\n',
                b'OPENROUTER_API_KEY="${MISSING_KEY}" # unresolved\n',
                b'OPENROUTER_API_KEY=$MISSING_KEY\n',
                b'OPENROUTER_API_KEY="$MISSING_KEY" # unresolved\n',
                b"OPENROUTER_API_KEY='$MISSING_KEY' # unresolved\n",
            ]:
                original = b'OCR_ENABLED=false\n' + key_line + b'PUBLIC_DOMAIN=example.com\n'
                environment.write_bytes(original)
                with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                    runtime.select_ocr_provider('openrouter')
                self.assertEqual(environment.read_bytes(), original)

    def test_openrouter_accepts_quoted_literal_key_and_preserves_key_line(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            for key_line in [
                b'OPENROUTER_API_KEY="literal-hosted-key" # provisioned\n',
                b"OPENROUTER_API_KEY='literal-hosted-key' # provisioned\n",
            ]:
                with self.subTest(key_line=key_line):
                    original = key_line + b'PUBLIC_DOMAIN=example.com\n'
                    environment.write_bytes(original)
                    with patch.object(runtime, 'SECRETS', secrets_dir):
                        runtime.select_ocr_provider('openrouter')
                    result = environment.read_bytes()
                    self.assertIn(key_line, result)
                    self.assertIn(b'OCR_PROVIDER=openrouter\n', result)

    def test_duplicate_touched_settings_reject_without_changes(self):
        cases = [
            b'OCR_ENABLED=false\nOCR_ENABLED=true\n',
            b'OCR_PROVIDER=ollama\nOCR_PROVIDER=openrouter\n',
            b'OCR_TIMEOUT_SECONDS=85\nOCR_TIMEOUT_SECONDS=90\n',
            b'OLLAMA_MODEL=one\nOLLAMA_MODEL=two\n',
        ]
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            for original in cases:
                with self.subTest(original=original):
                    environment.write_bytes(original)
                    with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                        runtime.select_ocr_provider('ollama')
                    self.assertEqual(environment.read_bytes(), original)

    def test_openrouter_duplicate_key_rejects_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original = b'OPENROUTER_API_KEY=first\nOPENROUTER_API_KEY=second\n'
            environment.write_bytes(original)
            with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                runtime.select_ocr_provider('openrouter')
            self.assertEqual(environment.read_bytes(), original)

    def test_invalid_provider_rejects_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            original = b'PUBLIC_DOMAIN=example.com\n'
            environment.write_bytes(original)
            with patch.object(runtime, 'SECRETS', secrets_dir), self.assertRaises(SystemExit):
                runtime.select_ocr_provider('automatic')
            self.assertEqual(environment.read_bytes(), original)

    def test_provider_selection_protects_file_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / 'secrets'
            secrets_dir.mkdir()
            environment = secrets_dir / 'production.env'
            environment.write_text('OPENROUTER_API_KEY=private-key\n')
            environment.chmod(0o644)
            with patch.object(runtime, 'SECRETS', secrets_dir):
                output = io.StringIO()
                with redirect_stdout(output):
                    runtime.select_ocr_provider('openrouter')
            self.assertIn('openrouter', output.getvalue())
            self.assertNotIn('private-key', output.getvalue())
            if os.name != 'nt':
                self.assertEqual(environment.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
