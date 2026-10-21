import unittest

from app.core.passwords import hash_password, verify_password


class PasswordHashingTests(unittest.TestCase):
    def test_hash_is_salted_and_verifies_password(self):
        password = "a sufficiently long password"
        first = hash_password(password)
        second = hash_password(password)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(password, first))
        self.assertFalse(verify_password("another password", first))

    def test_rejects_short_or_oversized_passwords_and_bad_hashes(self):
        with self.assertRaises(ValueError):
            hash_password("too-short")
        with self.assertRaises(ValueError):
            hash_password("x" * 1025)
        self.assertFalse(verify_password("password", "not-a-password-hash"))


if __name__ == "__main__":
    unittest.main()
