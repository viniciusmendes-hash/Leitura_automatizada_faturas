import hashlib
import unittest
from pathlib import Path
import pdfplumber
from extrator import extrair_fatura

RAIZ = Path(__file__).resolve().parents[1]

class TestMulticompetencias(unittest.TestCase):
    def test_pdfs_de_varios_meses_e_anos(self):
        arquivos = sorted((RAIZ / 'entrada').glob('EBDR-LEST-*.pdf'))
        self.assertGreaterEqual(len(arquivos), 10)
        for caminho in arquivos:
            with self.subTest(arquivo=caminho.name):
                digest = hashlib.sha256(caminho.read_bytes()).hexdigest()
                with pdfplumber.open(caminho) as pdf:
                    paginas = list(pdf.pages)
                    texto = '\n'.join(p.extract_text() or '' for p in paginas)
                    dados = extrair_fatura(texto, caminho.name, digest, paginas=paginas)
                self.assertTrue(dados.get('competencia'))
                self.assertTrue(dados.get('unidade_consumidora'))
                self.assertGreaterEqual(len(dados.get('leituras', [])), 8)
                self.assertEqual(len(dados.get('impostos', [])), 3)
                self.assertFalse(dados.get('ancoras_ausentes'))
                self.assertTrue(dados.get('zonas_geometricas_ancoradas', {}).get('itens'))

if __name__ == '__main__':
    unittest.main()
