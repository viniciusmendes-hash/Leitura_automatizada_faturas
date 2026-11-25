import json
import re
import sqlite3
import unicodedata
from pathlib import Path
import pandas as pd


def inicializar_banco(caminho):
    """Cria o banco relacional com uma linha-mestre por fatura e tabelas de detalhe."""
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(caminho) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS faturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash_arquivo TEXT NOT NULL UNIQUE,
            arquivo_origem TEXT NOT NULL,
            unidade_consumidora TEXT,
            competencia TEXT,
            valor_total REAL,
            status_validacao TEXT,
            avisos_validacao TEXT,
            dados_json TEXT NOT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS leituras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fatura_id INTEGER NOT NULL,
            grandeza TEXT,
            consumo REAL,
            unidade TEXT,
            FOREIGN KEY (fatura_id) REFERENCES faturas(id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS itens_faturados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fatura_id INTEGER NOT NULL,
            descricao TEXT,
            categoria TEXT,
            quantidade REAL,
            preco_unitario_com_tributos REAL,
            valor REAL,
            pis_cofins REAL,
            base_calculo_icms REAL,
            aliquota_icms REAL,
            valor_icms REAL,
            tarifa_sem_tributos REAL,
            FOREIGN KEY (fatura_id) REFERENCES faturas(id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS impostos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fatura_id INTEGER NOT NULL,
            tributo TEXT,
            base_calculo REAL,
            aliquota_percentual REAL,
            valor REAL,
            FOREIGN KEY (fatura_id) REFERENCES faturas(id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS demandas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fatura_id INTEGER NOT NULL,
            campo TEXT,
            valor_kw REAL,
            FOREIGN KEY (fatura_id) REFERENCES faturas(id)
        )''')
        conn.commit()


def salvar_fatura(caminho, fatura):
    """Insere ou atualiza uma fatura; reprocessamentos substituem seus detalhes."""
    dados_json = json.dumps(fatura, ensure_ascii=False)
    with sqlite3.connect(caminho) as conn:
        existente = conn.execute('SELECT id FROM faturas WHERE hash_arquivo=?',
                                 (fatura['hash_arquivo'],)).fetchone()
        if existente:
            fatura_id = existente[0]
            conn.execute("""UPDATE faturas SET arquivo_origem=?, unidade_consumidora=?,
                competencia=?, valor_total=?, status_validacao=?, avisos_validacao=?, dados_json=?
                WHERE id=?""", (
                fatura.get('arquivo_origem'), fatura.get('unidade_consumidora'),
                fatura.get('competencia'), fatura.get('valor_total'),
                fatura.get('status_validacao'), fatura.get('avisos_validacao'),
                dados_json, fatura_id))
            for tabela in ('leituras', 'itens_faturados', 'impostos', 'demandas'):
                conn.execute(f'DELETE FROM {tabela} WHERE fatura_id=?', (fatura_id,))
        else:
            cur = conn.execute("""INSERT INTO faturas
                (hash_arquivo, arquivo_origem, unidade_consumidora, competencia,
                 valor_total, status_validacao, avisos_validacao, dados_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                fatura['hash_arquivo'], fatura.get('arquivo_origem'),
                fatura.get('unidade_consumidora'), fatura.get('competencia'),
                fatura.get('valor_total'), fatura.get('status_validacao'),
                fatura.get('avisos_validacao'), dados_json))
            fatura_id = cur.lastrowid

        conn.executemany("""INSERT INTO leituras (fatura_id, grandeza, consumo, unidade)
            VALUES (?, ?, ?, ?)""", [
            (fatura_id, x.get('grandeza'), x.get('consumo'), x.get('unidade'))
            for x in fatura.get('leituras', [])])
        conn.executemany("""INSERT INTO itens_faturados
            (fatura_id, descricao, categoria, quantidade, preco_unitario_com_tributos,
             valor, pis_cofins, base_calculo_icms, aliquota_icms, valor_icms, tarifa_sem_tributos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", [
            (fatura_id, x.get('descricao'), x.get('categoria', 'energia'),
             x.get('quantidade'), x.get('preco_unitario_com_tributos'), x.get('valor'),
             x.get('pis_cofins'), x.get('base_calculo_icms'), x.get('aliquota_icms'),
             x.get('valor_icms'), x.get('tarifa_sem_tributos'))
            for x in fatura.get('itens', [])])
        conn.executemany("""INSERT INTO impostos (fatura_id, tributo, base_calculo, aliquota_percentual, valor)
            VALUES (?, ?, ?, ?, ?)""", [
            (fatura_id, x.get('tributo'), x.get('base_calculo'),
             x.get('aliquota_percentual'), x.get('valor'))
            for x in fatura.get('impostos', [])])
        conn.executemany("""INSERT INTO demandas (fatura_id, campo, valor_kw)
            VALUES (?, ?, ?)""", [
            (fatura_id, campo, valor)
            for campo, valor in fatura.get('demandas_contratadas', {}).items()])
        conn.commit()


def _slug(texto):
    texto = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-zA-Z0-9]+', '_', texto).strip('_').lower()


def _chave_competencia(valor):
    try:
        mes, ano = str(valor).split('/')
        return int(ano) * 100 + int(mes)
    except (ValueError, AttributeError):
        return 0


def _achatar(fatura):
    """Achata a fatura e cria campos estáveis para itens com nomenclatura variável."""
    fixos = [
        'arquivo_origem', 'nome_cliente', 'grupo_tensao', 'subgrupo', 'modalidade_tarifaria',
        'unidade_consumidora', 'conta_contrato', 'data_emissao', 'competencia',
        'data_vencimento', 'leitura_anterior', 'leitura_atual', 'valor_total',
        'fator_potencia', 'status_validacao', 'avisos_validacao'
    ]
    linha = {campo: fatura.get(campo) for campo in fixos}
    for campo, valor in fatura.get('demandas_contratadas', {}).items():
        linha[campo] = valor

    # Grandezas consolidadas: os nomes normalizados permitem comparar layouts.
    aliases_leitura = {
        'consumo fora ponta': 'leitura_consumo_fora_ponta_kwh',
        'consumo ponta': 'leitura_consumo_ponta_kwh',
        'demanda fora ponta': 'leitura_demanda_fora_ponta_kw',
        'demanda ponta': 'leitura_demanda_ponta_kw',
        'dem reat exced fp': 'leitura_demanda_reativa_excedente_fp_kvar',
        'dem reat exced pta': 'leitura_demanda_reativa_excedente_ponta_kvar',
        'reat exced f ponta': 'leitura_reat_exced_f_ponta_consumo_kvar',
        'reat exced ponta': 'leitura_reat_exced_ponta_consumo_kvar',
    }
    for leitura in fatura.get('leituras', []):
        nome = re.sub(r'[^a-z0-9]+', ' ', str(leitura.get('grandeza', '')).lower()).strip()
        unidade = _slug(leitura.get('unidade') or '')
        campo = aliases_leitura.get(nome)
        if campo:
            linha[campo] = leitura.get('consumo')
        else:
            chave = _slug(leitura.get('grandeza', 'grandeza'))
            linha[f'leitura_{chave}_{unidade}' if unidade else f'leitura_{chave}'] = leitura.get('consumo')

    # Cada item é mantido pelo nome original e também mapeado para campos
    # canônicos quando a distribuidora altera a descrição entre layouts.
    canonicos = {
        'demanda_ativa_kw': ('faturado_demanda_ativa_kw', ('demanda ativa', 'demanda tusd')),
        'demanda_ultrapassagem_kw': ('faturado_demanda_ultrapassagem_kw', ('demanda ultrapassagem', 'ultrapassagem de demanda', 'demanda por ultrapassagem')),
        'cons_reat_exced_np_kvar': ('faturado_cons_reat_exced_np_kvar', (
            'cons reativo np', 'consumo reat np', 'cons reat exced np',
            'consumo reat pt', 'consumo reativo pt', 'consumo reat ponta')),
        'cons_reat_exced_fp_kvar': ('faturado_cons_reat_exced_fp_kvar', (
            'consumo reat fora ponta', 'consumo reativo excedente fora ponta',
            'reat exced f ponta', 'energia reativa excedente fora ponta', 'cons reat exced fp',
            'consumo reat fp', 'cons reativo fp')),
        'demanda_reativa_kvar': ('faturado_demanda_reativa_kvar', (
            'dem reat exced', 'demanda reativa', 'demanda reat', 'dem reativa')),
    }
    for item in fatura.get('itens', []):
        descricao = str(item.get('descricao', ''))
        chave = _slug(descricao)
        for campo in ('quantidade', 'preco_unitario_com_tributos', 'valor'):
            linha[f'faturado_{chave}_{campo}'] = item.get(campo)
        desc_norm = _slug(descricao).replace('_', ' ')
        for chave_canonico, (prefixo, aliases) in canonicos.items():
            if chave_canonico == 'demanda_ativa_kw' and 'isenta' in desc_norm:
                continue
            if any(alias in desc_norm for alias in aliases):
                for campo in ('quantidade', 'preco_unitario_com_tributos', 'valor'):
                    # Para descrições repetidas (TUSD/TE), preserva a primeira
                    # ocorrência com valor e substitui apenas se a anterior era nula.
                    destino = f'{prefixo}_{campo}'
                    if linha.get(destino) is None and item.get(campo) is not None:
                        linha[destino] = item.get(campo)
                break

    
    ordem_campos = [
        'faturado_demanda_ativa_kw_quantidade',
        'faturado_demanda_ativa_kw_preco_unitario_com_tributos',
        'faturado_demanda_ativa_kw_valor',
        'faturado_demanda_ultrapassagem_kw_quantidade',
        'faturado_demanda_ultrapassagem_kw_preco_unitario_com_tributos',
        'faturado_demanda_ultrapassagem_kw_valor',
    ]
    for campo in ordem_campos:
        linha.setdefault(campo, None)

    # Reativo excedente fora ponta e demanda reativa vêm após o campo NP
    # correspondente, mantendo compatibilidade com a estrutura do relatório.
    for campo in [
        'faturado_cons_reat_exced_np_kvar_quantidade',
        'faturado_cons_reat_exced_np_kvar_preco_unitario_com_tributos',
        'faturado_cons_reat_exced_np_kvar_valor',
        'faturado_cons_reat_exced_fp_kvar_quantidade',
        'faturado_cons_reat_exced_fp_kvar_preco_unitario_com_tributos',
        'faturado_cons_reat_exced_fp_kvar_valor',
        'faturado_demanda_reativa_kvar_quantidade',
        'faturado_demanda_reativa_kvar_preco_unitario_com_tributos',
        'faturado_demanda_reativa_kvar_valor',
    ]:
        linha.setdefault(campo, None)

    for imposto in fatura.get('impostos', []):
        chave = _slug(imposto.get('tributo', 'tributo'))
        linha[f'imposto_{chave}_base_calculo'] = imposto.get('base_calculo')
        linha[f'imposto_{chave}_aliquota_percentual'] = imposto.get('aliquota_percentual')
        linha[f'imposto_{chave}_valor'] = imposto.get('valor')
    return linha


def exportar_excel(caminho_banco, caminho_excel):
    Path(caminho_excel).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(caminho_banco) as conn:
        registros = conn.execute('SELECT dados_json FROM faturas').fetchall()
    faturas = [json.loads(r[0]) for r in registros]
    linhas = [_achatar(f) for f in faturas]
    # Consolida nomes alternativos em uma única coluna canônica, preservando
    # qualquer valor já existente no destino e preenchendo somente células vazias.
    aliases_colunas = {
        'leitura_reat_exced_f_ponta_consumo_kvar': ['leitura_reativo_excedente_fora_ponta_kvarh'],
        'leitura_reat_exced_ponta_consumo_kvar': ['leitura_reativo_excedente_ponta_kvarh'],
        'faturado_consumo_ponta_te_kwh_quantidade': ['faturado_consumo_ponta_te_quantidade'],
        'faturado_consumo_ponta_te_kwh_preco_unitario_com_tributos': ['faturado_consumo_ponta_te_preco_unitario_com_tributos'],
        'faturado_consumo_ponta_te_kwh_valor': ['faturado_consumo_ponta_te_valor'],
        'faturado_consumo_ponta_tu_kwh_quantidade': ['faturado_consumo_ponta_tusd_quantidade'],
        'faturado_consumo_ponta_tu_kwh_preco_unitario_com_tributos': ['faturado_consumo_ponta_tusd_preco_unitario_com_tributos'],
        'faturado_consumo_ponta_tu_kwh_valor': ['faturado_consumo_ponta_tusd_valor'],
        'faturado_consumo_f_ponta_tu_kwh_quantidade': ['faturado_consumo_fora_ponta_tusd_quantidade'],
        'faturado_consumo_f_ponta_tu_kwh_preco_unitario_com_tributos': ['faturado_consumo_fora_ponta_tusd_preco_unitario_com_tributos'],
        'faturado_consumo_f_ponta_tu_kwh_valor': ['faturado_consumo_fora_ponta_tusd_valor'],
        'faturado_consumo_f_ponta_te_kwh_quantidade': ['faturado_consumo_fora_ponta_te_quantidade'],
        'faturado_consumo_f_ponta_te_kwh_preco_unitario_com_tributos': ['faturado_consumo_fora_ponta_te_preco_unitario_com_tributos'],
        'faturado_consumo_f_ponta_te_kwh_valor': ['faturado_consumo_fora_ponta_te_valor'],
        'faturado_cons_reat_exced_np_kvar_quantidade': ['faturado_consumo_reat_ponta_te_quantidade'],
        'faturado_cons_reat_exced_np_kvar_preco_unitario_com_tributos': ['faturado_consumo_reat_ponta_te_preco_unitario_com_tributos'],
        'faturado_cons_reat_exced_np_kvar_valor': ['faturado_consumo_reat_ponta_te_valor'],
        'faturado_cons_reat_exced_fp_kvar_quantidade': ['faturado_consumo_reat_fora_ponta_te_quantidade'],
        'faturado_cons_reat_exced_fp_kvar_preco_unitario_com_tributos': ['faturado_consumo_reat_fora_ponta_te_preco_unitario_com_tributos'],
        'faturado_cons_reat_exced_fp_kvar_valor': ['faturado_consumo_reat_fora_ponta_te_valor'],
        'faturado_dem_ativa_isenta_de_icms_kw_quantidade': ['faturado_demanda_tusd_isenta_icms_quantidade', 'faturado_demanda_isenta_icms_kw_quantidade'],
        'faturado_dem_ativa_isenta_de_icms_kw_preco_unitario_com_tributos': ['faturado_demanda_tusd_isenta_icms_preco_unitario_com_tributos', 'faturado_demanda_isenta_icms_kw_preco_unitario_com_tributos'],
        'faturado_dem_ativa_isenta_de_icms_kw_valor': ['faturado_demanda_tusd_isenta_icms_valor', 'faturado_demanda_isenta_icms_kw_valor'],
    }
    aliases_adicionais = {
        'faturado_consumo_ponta_tu_kwh_quantidade': ['faturado_consumo_ponta_tusd_kwh_quantidade'],
        'faturado_consumo_ponta_tu_kwh_preco_unitario_com_tributos': ['faturado_consumo_ponta_tusd_kwh_preco_unitario_com_tributos'],
        'faturado_consumo_ponta_tu_kwh_valor': ['faturado_consumo_ponta_tusd_kwh_valor'],
        'faturado_consumo_f_ponta_te_kwh_quantidade': ['faturado_consumo_fora_ponta_te_kwh_quantidade'],
        'faturado_consumo_f_ponta_te_kwh_preco_unitario_com_tributos': ['faturado_consumo_fora_ponta_te_kwh_preco_unitario_com_tributos'],
        'faturado_consumo_f_ponta_te_kwh_valor': ['faturado_consumo_fora_ponta_te_kwh_valor'],
        'faturado_consumo_f_ponta_tu_kwh_quantidade': ['faturado_consumo_fora_ponta_tusd_kwh_quantidade'],
        'faturado_consumo_f_ponta_tu_kwh_preco_unitario_com_tributos': ['faturado_consumo_fora_ponta_tusd_kwh_preco_unitario_com_tributos'],
        'faturado_consumo_f_ponta_tu_kwh_valor': ['faturado_consumo_fora_ponta_tusd_kwh_valor'],
        'faturado_demanda_ultrapassagem_kw_quantidade': ['faturado_demanda_ultrapas_kw_quantidade', 'faturado_demanda_ultrap_tusd_kw_quantidade'],
        'faturado_demanda_ultrapassagem_kw_preco_unitario_com_tributos': ['faturado_demanda_ultrapas_kw_preco_unitario_com_tributos', 'faturado_demanda_ultrap_tusd_kw_preco_unitario_com_tributos'],
        'faturado_demanda_ultrapassagem_kw_valor': ['faturado_demanda_ultrapas_kw_valor', 'faturado_demanda_ultrap_tusd_kw_valor'],
        'faturado_cons_reat_exced_np_kvar_quantidade': ['faturado_consumo_reat_pt_te_kwh_quantidade'],
        'faturado_cons_reat_exced_np_kvar_preco_unitario_com_tributos': ['faturado_consumo_reat_pt_te_kwh_preco_unitario_com_tributos'],
        'faturado_cons_reat_exced_np_kvar_valor': ['faturado_consumo_reat_pt_te_kwh_valor'],
        'faturado_demanda_reativa_kvar_quantidade': ['faturado_exc_dem_reativa_tusd_kw_quantidade'],
        'faturado_demanda_reativa_kvar_preco_unitario_com_tributos': ['faturado_exc_dem_reativa_tusd_kw_preco_unitario_com_tributos'],
        'faturado_demanda_reativa_kvar_valor': ['faturado_exc_dem_reativa_tusd_kw_valor'],
        'faturado_adicional_bandeira_valor': ['faturado_adicional_band_amarela_valor'],
        'faturado_credito_dic_fic_dmic_valor': ['faturado_cred_viol_meta_cont_valor']
    }
    # IMPORTANTE: update() sobrescrevia os aliases já definidos para a mesma
    # coluna, deixando variações antigas (sem _kwh) sem consolidação.
    for destino, origens in aliases_adicionais.items():
        existentes = aliases_colunas.setdefault(destino, [])
        for origem in origens:
            if origem not in existentes:
                existentes.append(origem)
    aliases_remover = {alias for aliases in aliases_colunas.values() for alias in aliases}
    for linha in linhas:
        for destino, origens in aliases_colunas.items():
            if linha.get(destino) in (None, '', 0):
                for origem in origens:
                    if linha.get(origem) not in (None, '', 0):
                        linha[destino] = linha[origem]
                        break
            for origem in origens:
                linha.pop(origem, None)
    colunas_descartadas = set(['faturado_demanda_tusd_quantidade', 'faturado_demanda_tusd_preco_unitario_com_tributos', 'faturado_demanda_tusd_valor', 'faturado_demanda_te_quantidade', 'faturado_demanda_te_preco_unitario_com_tributos', 'faturado_demanda_te_valor', 'leitura_demanda_kw_tp_kw', 'leitura_kvarh_i_kvarh_pt_kvarh', 'leitura_dn_kw_pt_kw', 'leitura_dn_kw_fp_kw', 'faturado_cred_viol_meta_cont_quantidade', 'faturado_cred_viol_meta_cont_preco_unitario_com_tributos', 'leitura_consumo_kwh', 'leitura_ener_reativa_indutiva_kvarh', 'leitura_demanda_acumulada_fp_demanda_kw', 'leitura_demanda_acumulada_np_demanda_kw', 'leitura_dmcr_acumulada_fpta_kvarhe', 'leitura_dmcr_acumulada_np_kvarhe', 'faturado_cons_reativo_fp_tusd_quantidade', 'faturado_cons_reativo_fp_tusd_preco_unitario_com_tributos', 'faturado_cons_reativo_fp_tusd_valor', 'faturado_tributo_a_reter_csll_quantidade', 'faturado_tributo_a_reter_csll_preco_unitario_com_tributos', 'faturado_tributo_a_reter_csll_valor', 'faturado_tributo_a_reter_cofins_quantidade', 'faturado_tributo_a_reter_cofins_preco_unitario_com_tributos', 'faturado_tributo_a_reter_cofins_valor', 'faturado_demanda_reat_exced_te_quantidade', 'faturado_demanda_reat_exced_te_preco_unitario_com_tributo', 'faturado_demanda_reat_exced_te_valor', 'faturado_tributo_a_reter_pis_quantidade', 'faturado_tributo_a_reter_pis_preco_unitario_com_tributos', 'faturado_tributo_a_reter_pis_valor', 'faturado_demanda_ultrapassagem_te_quantidade', 'faturado_demanda_ultrapassagem_te_preco_unitario_com_tributos', 'faturado_demanda_ultrapassagem_te_valor'])
    for linha in linhas:
        for campo in colunas_descartadas:
            linha.pop(campo, None)
    # Ordenação global por competência (ano+mês) decrescente; UC é critério secundário.
    linhas.sort(key=lambda x: (-_chave_competencia(x.get('competencia')), str(x.get('unidade_consumidora') or '')))
    df = pd.DataFrame(linhas)
    if not df.empty:
        # Mantém identificação e controle no início; os campos detalhados vêm depois.
        iniciais = [c for c in [
            'unidade_consumidora', 'competencia', 'data_emissao', 'data_vencimento',
            'valor_total', 'grupo_tensao', 'subgrupo', 'modalidade_tarifaria', 'conta_contrato',
            'leitura_anterior', 'leitura_atual', 'fator_potencia', 'status_validacao', 'avisos_validacao',
            'arquivo_origem', 'nome_cliente'
        ] if c in df.columns]
        demais = [c for c in df.columns if c not in iniciais]
        # Demanda de ultrapassagem imediatamente após Demanda Ativa (valor).
        demanda_ativa_valor = 'faturado_demanda_ativa_kw_valor'
        bloco_ultrap = [c for c in [
            'faturado_demanda_ultrapassagem_kw_quantidade',
            'faturado_demanda_ultrapassagem_kw_preco_unitario_com_tributos',
            'faturado_demanda_ultrapassagem_kw_valor'] if c in demais]
        demais = [c for c in demais if c not in bloco_ultrap]
        if demanda_ativa_valor in demais:
            pos = demais.index(demanda_ativa_valor) + 1
            demais[pos:pos] = bloco_ultrap
        else:
            demais = bloco_ultrap + demais
        # Campos reativos FP e demanda reativa logo após o grupo NP.
        bloco_reat = [c for c in [
            'faturado_cons_reat_exced_fp_kvar_quantidade',
            'faturado_cons_reat_exced_fp_kvar_preco_unitario_com_tributos',
            'faturado_cons_reat_exced_fp_kvar_valor',
            'faturado_demanda_reativa_kvar_quantidade',
            'faturado_demanda_reativa_kvar_preco_unitario_com_tributos',
            'faturado_demanda_reativa_kvar_valor'] if c in demais]
        demais = [c for c in demais if c not in bloco_reat]
        np_valor = 'faturado_cons_reat_exced_np_kvar_valor'
        if np_valor in demais:
            pos = demais.index(np_valor) + 1
            demais[pos:pos] = bloco_reat
        else:
            demais.extend(bloco_reat)
        df = df[iniciais + demais]
    with pd.ExcelWriter(caminho_excel, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Base de dados', index=False)
        ws = writer.book['Base de dados']
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            largura = max((len(str(c.value)) if c.value is not None else 0) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(largura + 2, 12), 42)
            # Valores monetários/medidos permanecem numéricos no Excel para permitir cálculos.
