import unittest
from banco import _chave_competencia

class TestOrdenacaoCompetencia(unittest.TestCase):
    def test_competencia_considera_mes_e_ano(self):
        competencias = ['12/2025', '01/2026', '03/2025', '11/2025']
        ordenadas = sorted(competencias, key=_chave_competencia, reverse=True)
        self.assertEqual(ordenadas, ['01/2026', '12/2025', '11/2025', '03/2025'])

if __name__ == '__main__':
    unittest.main()
