import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from worker import auth


class LocalPasswordTests(unittest.TestCase):
    def test_first_run_and_private_password_change(self):
        with tempfile.TemporaryDirectory() as root:
            config=Path(root)/'config'
            with patch.object(auth,'CONFIG',config),patch.object(auth,'PASSWORD_FILE',config/'password.json'),patch.dict('os.environ',{'APP_PASSWORD':''}):
                self.assertFalse(auth.configured(root))
                auth.set_password('first-password-123')
                self.assertTrue(auth.configured(root))
                self.assertTrue(auth.verify('first-password-123',root))
                self.assertFalse(auth.verify('wrong-password',root))
                self.assertEqual((config/'password.json').stat().st_mode & 0o777,0o600)
                self.assertNotIn('first-password-123',(config/'password.json').read_text())
                auth.set_password('second-password-456')
                self.assertFalse(auth.verify('first-password-123',root))
                self.assertTrue(auth.verify('second-password-456',root))

    def test_existing_legacy_password_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            config=Path(root)/'config'
            (Path(root)/'.env').write_text('APP_PASSWORD=old-private-password\n')
            with patch.object(auth,'CONFIG',config),patch.object(auth,'PASSWORD_FILE',config/'password.json'),patch.dict('os.environ',{'APP_PASSWORD':''}):
                self.assertTrue(auth.verify('old-private-password',root))
                auth.set_password('new-private-password')
                self.assertFalse(auth.verify('old-private-password',root))
                self.assertTrue(auth.verify('new-private-password',root))
