import sys
import unittest
from pathlib import Path
import pdfplumber

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from extrator import extrair_fatura

class TestExtracaoPDF(unittest.TestCase):
    def test_fatura_referencia(self):
        pdf = RAIZ / 'entrada' / 'EBDR-LEST-2026.01.pdf'
        with pdfplumber.open(pdf) as doc:
            texto = '\n'.join(p.extract_text() or '' for p in doc.pages)
            dados = extrair_fatura(texto, pdf.name, 'hash-teste', paginas=doc.pages)
        self.assertEqual(dados['unidade_consumidora'], '539.120.010-29')
        self.assertEqual(dados['conta_contrato'], '38134691')
        self.assertEqual(dados['competencia'], '01/2026')
        self.assertEqual(dados['valor_total'], 38384.78)
        self.assertEqual(dados['subgrupo'], 'A4')
        self.assertEqual(dados['modalidade_tarifaria'], 'A4_VD')
        self.assertEqual(dados['demandas_contratadas']['demanda_contratada_unica_kw'], 400.0)
        self.assertEqual(dados['demandas_contratadas']['demanda_contratada_fora_ponta_kw'], 400.0)
        self.assertEqual(len(dados['impostos']), 3)
        self.assertGreaterEqual(len(dados['leituras']), 10)
        item = next(x for x in dados['itens'] if x['descricao'] == 'Consumo Ponta TUSD (kWh)')
        self.assertEqual(item['quantidade'], 3156.0)
        self.assertAlmostEqual(item['preco_unitario_com_tributos'], 2.120656)
        self.assertAlmostEqual(item['valor'], 6692.79)

if __name__ == '__main__':
    unittest.main()
