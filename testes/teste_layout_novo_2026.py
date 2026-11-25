import hashlib
import unittest
from pathlib import Path
import pdfplumber
from extrator import extrair_fatura
from banco import _achatar

RAIZ = Path(__file__).resolve().parents[1]

class TestLayoutNovo2026(unittest.TestCase):
    def _ler(self, nome):
        caminho = RAIZ / 'entrada' / nome
        digest = hashlib.sha256(caminho.read_bytes()).hexdigest()
        with pdfplumber.open(caminho) as pdf:
            return extrair_fatura('', caminho.name, digest, list(pdf.pages))

    def test_fevereiro_2026(self):
        f = self._ler('EBDR-LEST-2026.02.pdf')
        self.assertEqual(f['competencia'], '02/2026')
        self.assertEqual(f['unidade_consumidora'], '38134691')
        self.assertEqual(f['modalidade_tarifaria'], 'A4_H.VERDE')
        self.assertEqual(f['grupo_tensao'], 'A')
        self.assertEqual(f['leitura_anterior'], '31/12/2025')
        self.assertEqual(f['leitura_atual'], '31/01/2026')
        self.assertEqual(f['demandas_contratadas']['demanda_contratada_unica_kw'], 400.0)
        self.assertEqual(len(f['impostos']), 3)
        self.assertGreaterEqual(len(f['leituras']), 10)
        self.assertTrue(any(x['descricao'] == 'CONSUMO FORA PONTA TUSD' and x['quantidade'] == 19620.0 for x in f['itens']))

    def test_marco_2026(self):
        f = self._ler('EBDR-LEST-2026.03.pdf')
        self.assertEqual(f['competencia'], '03/2026')
        self.assertEqual(f['leitura_anterior'], '31/01/2026')
        self.assertEqual(f['leitura_atual'], '28/02/2026')
        self.assertTrue(any(x['grandeza'] == 'Dem. Reat. Exced. FP' for x in f['leituras']))


    def test_julho_2026_competencia_total_e_modalidade(self):
        f = self._ler('EBDR-LEST-2026.07.pdf')
        self.assertEqual(f['competencia'], '07/2026')
        self.assertEqual(f['valor_total'], 33065.95)
        self.assertEqual(f['modalidade_tarifaria'], 'A4_VD')

    def test_colunas_canonicas(self):
        f = {'itens': [
            {'descricao': 'Demanda Ativa (kW)', 'quantidade': 10, 'preco_unitario_com_tributos': 2, 'valor': 20},
            {'descricao': 'Demanda Ultrapassagem (kW)', 'quantidade': 3, 'preco_unitario_com_tributos': 4, 'valor': 12},
            {'descricao': 'Cons. Reativo FP TUSD', 'quantidade': 5, 'preco_unitario_com_tributos': 6, 'valor': 30},
            {'descricao': 'Cons. Reativo NP TUSD', 'quantidade': 2, 'preco_unitario_com_tributos': 3, 'valor': 6},
            {'descricao': 'Exc.Dem.Reativa TUSD (kW)', 'quantidade': 7, 'preco_unitario_com_tributos': 8, 'valor': 56},
        ]}
        linha = _achatar(f)
        self.assertEqual(linha['faturado_demanda_ativa_kw_valor'], 20)
        self.assertEqual(linha['faturado_demanda_ultrapassagem_kw_valor'], 12)
        self.assertEqual(linha['faturado_cons_reat_exced_fp_kvar_valor'], 30)
        self.assertEqual(linha['faturado_cons_reat_exced_np_kvar_valor'], 6)
        self.assertEqual(linha['faturado_demanda_reativa_kvar_valor'], 56)

if __name__ == '__main__':
    unittest.main()
