import unittest
from extrator import numero_br

class TestNumeroBR(unittest.TestCase):
    def test_valores_brasileiros(self):
        self.assertAlmostEqual(numero_br('38.384,78'), 38384.78)
        self.assertAlmostEqual(numero_br('3.156,00'), 3156.0)
        self.assertAlmostEqual(numero_br('0,85021805'), 0.85021805)
        self.assertIsNone(numero_br(None))

if __name__ == '__main__':
    unittest.main()
