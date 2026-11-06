import unittest

from backend.phone_numbers import mask_brazilian_phone, normalize_brazilian_mobile, normalize_brazilian_phone


class BrazilianPhoneTests(unittest.TestCase):
    def test_normalizes_common_mobile_formats(self):
        for value in ("(11) 91234-5678", "11912345678", "+55 11 91234-5678", "5511912345678"):
            with self.subTest(value=value):
                self.assertEqual(normalize_brazilian_phone(value), "+5511912345678")

    def test_accepts_business_landline(self):
        self.assertEqual(normalize_brazilian_phone("(21) 3456-7890"), "+552134567890")

    def test_rejects_invalid_numbers(self):
        for value in ("", "+1 202 555 0123", "0011912345678", "0012345678",
                      "(11) 12345-6789", "(11) 1234-5678", "1191234567x", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_brazilian_phone(value)

    def test_mask_does_not_expose_subscriber_number(self):
        self.assertEqual(mask_brazilian_phone("(11) 91234-5678"), "+55 (11) *****5678")

    def test_sms_mobile_normalizer_rejects_landlines(self):
        self.assertEqual(normalize_brazilian_mobile("(11) 91234-5678"), "+5511912345678")
        with self.assertRaises(ValueError):
            normalize_brazilian_mobile("(21) 3456-7890")


if __name__ == "__main__":
    unittest.main()
