from pathlib import Path
import json
import logging
import hashlib
import sqlite3
from datetime import datetime
import pdfplumber
import pandas as pd
from extrator import extrair_fatura
from validador import validar_fatura
from banco import inicializar_banco, salvar_fatura, exportar_excel

RAIZ = Path(__file__).resolve().parent
with (RAIZ / "config.json").open("r", encoding="utf-8") as f:
    CONFIG = json.load(f)

PASTA_ENTRADA = RAIZ / CONFIG["pasta_entrada"]
PASTA_SAIDA = RAIZ / CONFIG["pasta_saida"]
BANCO = RAIZ / CONFIG["banco_sqlite"]
EXCEL = RAIZ / CONFIG["arquivo_excel"]
LOGS = RAIZ / "logs"
LOGS.mkdir(exist_ok=True)
PASTA_SAIDA.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOGS / "execucao.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()

def main():
    inicializar_banco(BANCO)
    if not PASTA_ENTRADA.exists():
        PASTA_ENTRADA.mkdir(parents=True)
    pdfs = sorted(PASTA_ENTRADA.rglob("*.pdf") if CONFIG.get("processar_recursivamente")
                  else PASTA_ENTRADA.glob("*.pdf"))
    if not pdfs:
        logging.info("Nenhum PDF encontrado em %s", PASTA_ENTRADA)
        return

    processados = 0
    erros = 0
    VERSAO_EXTRACAO = 5
    with sqlite3.connect(BANCO) as conn:
        hashes_existentes = set()
        for digest_existente, dados_json_existente in conn.execute(
                "SELECT hash_arquivo, dados_json FROM faturas"):
            try:
                if json.loads(dados_json_existente).get('versao_extracao') == VERSAO_EXTRACAO:
                    hashes_existentes.add(digest_existente)
            except (json.JSONDecodeError, TypeError):
                continue
    for pdf in pdfs:
        digest = sha256_arquivo(pdf)
        if digest in hashes_existentes:
            logging.info("Ignorado (arquivo já processado): %s", pdf.name)
            continue
        try:
            logging.info("Processando: %s", pdf.name)
            with pdfplumber.open(pdf) as documento:
                paginas = list(documento.pages)
                texto_paginas = [(p.extract_text() or "") for p in paginas]
            texto = "\n".join(texto_paginas)
            if not texto.strip():
                raise ValueError("PDF sem texto extraível; será necessário OCR.")
            fatura = extrair_fatura(texto, pdf.name, digest, paginas=paginas)
            # Evita duplicar a mesma fatura quando há cópias de PDF com marcações
            # ou dados diferentes (hash distinto, mas mesma UC/competência/nota).
            with sqlite3.connect(BANCO) as conn:
                existentes = conn.execute(
                    "SELECT hash_arquivo, dados_json FROM faturas WHERE unidade_consumidora=? AND competencia=?",
                    (fatura.get("unidade_consumidora"), fatura.get("competencia"))
                ).fetchall()
            duplicada = False
            for (hash_existente, dados_json_existente) in existentes:
                # Mesma hash representa atualização da extração, não duplicidade.
                if hash_existente == digest:
                    continue
                duplicada = True
                break
            if duplicada:
                logging.info("Ignorado (mesma UC, competência e nota fiscal): %s", pdf.name)
                continue
            validacao = validar_fatura(fatura, CONFIG.get("validar_valor_total", True))
            fatura["status_validacao"] = "OK" if not validacao else "REVISAR"
            fatura["avisos_validacao"] = " | ".join(validacao)
            salvar_fatura(BANCO, fatura)
            hashes_existentes.add(digest)
            logging.info("Salvo: %s | competência=%s | valor=%s | itens=%d | avisos=%d",
                         pdf.name, fatura.get("competencia"), fatura.get("valor_total"),
                         len(fatura["itens"]), len(validacao))
            logging.info("Janelas geométricas localizadas por âncoras: %s",
                         fatura.get("zonas_geometricas_ancoradas", {}))
            if validacao:
                for aviso in validacao:
                    logging.warning("%s: %s", pdf.name, aviso)
            processados += 1
        except Exception as exc:
            erros += 1
            logging.exception("Erro ao processar %s: %s", pdf.name, exc)

    exportar_excel(BANCO, EXCEL)
    logging.info("Fim. Novos PDFs processados=%d; erros=%d; Excel=%s", processados, erros, EXCEL)

if __name__ == "__main__":
    main()
