import re
from decimal import Decimal, InvalidOperation
from collections import defaultdict

NUM_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d+|-?\d{1,3}(?:\.\d{3})+|-?\d+,\d+|-?\d+')

import unicodedata

def _normalizar_ancora(texto):
    """Normaliza rótulos para localizar âncoras mesmo com acentos/caixa diferentes."""
    texto = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', texto).strip().casefold()


def localizar_ancora(words, rotulos, *, x_min=None, x_max=None, y_min=None, y_max=None):
    """Localiza rótulo no PDF e devolve sua caixa geométrica (x0, top, x1, bottom).
    A busca usa palavras extraídas pelo pdfplumber, não coordenadas absolutas.
    Os limites geométricos são opcionais e servem apenas para desambiguar rótulos
    repetidos (por exemplo, ICMS na tabela de itens e no quadro de tributos).
    """
    if isinstance(rotulos, str):
        rotulos = [rotulos]
    alvos = {_normalizar_ancora(x) for x in rotulos}
    linhas = _agrupar_linhas(words, tolerancia=3.0)
    encontrados = []
    for linha in linhas:
        ws = sorted(linha['words'], key=lambda w: w['x0'])
        texto = _normalizar_ancora(' '.join(w['text'] for w in ws))
        if not any(a in texto for a in alvos):
            continue
        x0 = min(w['x0'] for w in ws); x1 = max(w['x1'] for w in ws)
        top = min(w['top'] for w in ws); bottom = max(w['bottom'] for w in ws)
        if x_min is not None and x1 < x_min: continue
        if x_max is not None and x0 > x_max: continue
        if y_min is not None and bottom < y_min: continue
        if y_max is not None and top > y_max: continue
        encontrados.append({'x0': x0, 'top': top, 'x1': x1, 'bottom': bottom,
                            'texto': ' '.join(w['text'] for w in ws)})
    return min(encontrados, key=lambda a: (a['top'], a['x0'])) if encontrados else None


def janela_relativa(ancora, page, dx0=0, dy0=0, dx1=0, dy1=0):
    """Cria uma janela de recorte relativa à caixa da âncora, limitada à página."""
    if not ancora:
        return None
    return (max(0, ancora['x0'] + dx0), max(0, ancora['top'] + dy0),
            min(page.width, ancora['x1'] + dx1), min(page.height, ancora['bottom'] + dy1))


def _pagina_sem_marca_dagua(page):
    """Remove caracteres da marca d'água SEGUNDA VIA antes de agrupar palavras.
    Nas faturas de 2026.02/03 a marca é um texto cinza, inclinado e muito maior
    que o corpo da fatura (fonte Helvetica-BoldOblique, ~70 pt). Filtrá-la no
    nível de caractere evita que ela seja concatenada a descrições e números.
    """
    def manter(obj):
        if obj.get('object_type') != 'char':
            return True
        fonte = str(obj.get('fontname', '')).lower()
        cor = obj.get('non_stroking_color')
        tamanho = float(obj.get('size') or 0)
        marca = ('boldoblique' in fonte and tamanho >= 20 and
                 isinstance(cor, tuple) and len(cor) >= 3 and
                 all(0.50 <= float(c) <= 0.80 for c in cor[:3]))
        return not marca
    return page.filter(manter)


def _normalizar_texto_curto(valor):
    return _normalizar_ancora(valor).replace('.', ' ').replace(':', ' ')


def _limites_verticais_por_ancora(words, page):
    """#Calcula zonas de leitura usando âncoras encontradas no próprio documento.
    As janelas são relativas às âncoras; não dependem de uma coordenada Y fixa.
    Quando um rótulo obrigatório não aparece, a zona fica indisponível e gera aviso.
    """
    ancora_itens = localizar_ancora(words, ['ITENS DA FATURA', 'ITENS FATURA', 'ITENS DE FATURA'])
    if not ancora_itens:
        ancora_itens = localizar_ancora(words, ['Consumo Ponta'], x_max=page.width * .30)
    ancora_demanda = localizar_ancora(words, ['Demanda Contratada', 'Demanda Todos os Períodos'], x_min=page.width * .60)
    ancora_icms = localizar_ancora(words, ['ICMS'], x_min=page.width * .68)
    # A primeira linha de medição é identificada pelo código do medidor (RG...) e
    # não por uma faixa vertical fixa. A região termina antes do rodapé/histórico.
    linhas_rg = [g for g in _agrupar_linhas(words, 3.0)
                 if re.search(r'\bRG\w+', ' '.join(w['text'] for w in g['words']), re.I)]
    ancora_leituras = None
    if linhas_rg:
        g = linhas_rg[0]
        ancora_leituras = {'x0': min(w['x0'] for w in g['words']),
                           'top': min(w['top'] for w in g['words']),
                           'x1': max(w['x1'] for w in g['words']),
                           'bottom': max(w['bottom'] for w in g['words']),
                           'texto': ' '.join(w['text'] for w in g['words'])}
    else:
        # Layout novo: a tabela começa pelo cabeçalho "Grandezas" e não
        # apresenta o código RG do medidor no início de cada linha.
        ancora_leituras = localizar_ancora(words, ['Grandezas'], x_max=page.width * .28,
                                            y_min=page.height * .35)
        if not ancora_leituras:
            ancora_leituras = localizar_ancora(words, ['CONSUMO'], x_max=page.width * .22,
                                                y_min=page.height * .40)
    # A região de itens começa logo abaixo do título e termina antes da primeira
    # linha de leituras; limites são calculados a partir das âncoras encontradas.
    zonas = {
        'demandas': (max(0, ancora_demanda['top'] - 85), min(page.height, ancora_demanda['bottom'] + 105)) if ancora_demanda else None,
        'itens': (max(0, ancora_itens['top'] - 4), min(page.height, ancora_itens['bottom'] + 90)) if ancora_itens else None,
        'leituras': (max(0, ancora_leituras['top'] - 4), min(page.height, ancora_leituras['top'] + (190 if 'Grandezas' in ancora_leituras.get('texto','') else 155))) if ancora_leituras else None,
        'impostos': (max(0, ancora_icms['top'] - 4), min(page.height, ancora_icms['top'] + 85)) if ancora_icms else None,
    }
    diagnostico = {k: (round(v[0], 2), round(v[1], 2)) if v else None for k, v in zonas.items()}
    faltantes = [k for k, a in [('itens', ancora_itens), ('leituras', ancora_leituras),
                                ('impostos', ancora_icms), ('demandas', ancora_demanda)] if not a]
    return zonas, diagnostico, faltantes


def numero_br(valor):
    """Converte números no formato brasileiro para float, preservando None."""
    if valor is None:
        return None
    s = str(valor).strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def primeiro(padrao, texto, flags=re.I | re.M):
    m = re.search(padrao, texto, flags)
    return m.group(1).strip() if m else None


def _num_no_grupo(words):
    """Retorna o primeiro token numérico de um grupo de palavras."""
    for w in sorted(words, key=lambda a: a['x0']):
        if NUM_RE.fullmatch(w['text']):
            return w['text']
    return None


def _agrupar_linhas(words, tolerancia=2.3):
    linhas = []
    for w in sorted(words, key=lambda a: (a['top'], a['x0'])):
        grupo = next((g for g in linhas if abs(g['top'] - w['top']) <= tolerancia), None)
        if grupo is None:
            grupo = {'top': w['top'], 'words': []}
            linhas.append(grupo)
        grupo['words'].append(w)
    return sorted(linhas, key=lambda g: g['top'])


def _extrair_tabelas_pdf(paginas):
    """Extrai tabelas por posição no layout conhecido da fatura CEEE-Equatorial."""
    leituras, itens, impostos = [], [], []
    demandas = {}
    if not paginas:
        return leituras, itens, impostos, demandas, {}, ['itens', 'leituras', 'impostos', 'demandas']
    # As âncoras são localizadas em cada página, permitindo deslocamentos verticais
    # entre competências/versões do PDF sem depender de Y absoluto.
    # Seleciona a página que efetivamente contém mais âncoras das tabelas.
    # Algumas competências possuem páginas adicionais ou pequenas mudanças de diagramação.
    candidatos = []
    paginas_limpas = [_pagina_sem_marca_dagua(pg) for pg in paginas]
    for indice_pg, pg in enumerate(paginas_limpas):
        ws_pg = pg.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
        zonas_pg, diag_pg, falt_pg = _limites_verticais_por_ancora(ws_pg, pg)
        score = sum(zonas_pg.get(k) is not None for k in ('demandas', 'itens', 'leituras', 'impostos'))
        candidatos.append((score, indice_pg, pg, ws_pg, zonas_pg, diag_pg, falt_pg))
    _, indice_pagina, page, words, zonas, diagnostico, faltantes = max(candidatos, key=lambda x: x[0])

    # campos de demanda contratada e demandas de distribuição/reserva.
    mapa_demandas = {
        'Demanda Contratada Única': 'demanda_contratada_unica_kw',
        'Demanda Todos os Períodos': 'demanda_contratada_unica_kw',
        'Demanda Contratada Ponta': 'demanda_contratada_ponta_kw',
        'Demanda Contratada Fora Ponta': 'demanda_contratada_fora_ponta_kw',
        'Dem. Reserva Cap. Única': 'demanda_reserva_capacidade_unica_kw',
        'Dem. Reserva Cap. Fora Ponta': 'demanda_reserva_capacidade_fora_ponta_kw',
        'Dem. Reserva Cap. Ponta': 'demanda_reserva_capacidade_ponta_kw',
        'Dem. de Geração': 'demanda_geracao_kw',
        'Dem. de Dist. Única': 'demanda_distribuicao_unica_kw',
        'Dem. de Dist. De Ponta': 'demanda_distribuicao_ponta_kw',
        'Dem. de Dist. Fora Ponta': 'demanda_distribuicao_fora_ponta_kw',
    }
    zona = zonas.get('demandas')
    for linha in _agrupar_linhas([w for w in words if zona and zona[0] <= w['top'] <= zona[1] and page.width * .70 <= w['x0'] <= page.width * .995]):
        ws = sorted(linha['words'], key=lambda w: w['x0'])
        texto = ' '.join(w['text'] for w in ws)
        m = re.search(r'^(Demanda Contratada Única|Demanda Todos os Períodos|Demanda Contratada Ponta|Demanda Contratada Fora Ponta|Dem\. Reserva Cap\. Única|Dem\. Reserva Cap\. Fora Ponta|Dem\. Reserva Cap\. Ponta|Dem\. de Geração|Dem\. de Dist\. Única|Dem\. de Dist\. De Ponta|Dem\. de Dist\. Fora Ponta)\s*\(kW\):?\s*(.*)$', texto, re.I)
        if m:
            chave = mapa_demandas.get(m.group(1), re.sub(r'[^a-z0-9]+', '_', m.group(1).lower()).strip('_'))
            valor = numero_br(primeiro(r'(-?\d[\d.]*,\d+|-?\d+)', m.group(2)))
            demandas[chave] = valor

    # itens de faturamento. As coordenadas separam as colunas,
    # evitando deslocar valores quando uma coluna estiver vazia.
    zona = zonas.get('itens')
    for linha in _agrupar_linhas([w for w in words if zona and zona[0] <= w['top'] <= zona[1] and 0 <= w['x0'] <= page.width * .73]):
        ws = linha['words']
        descricao_ws = [w for w in ws if w['x0'] < page.width * 0.202 and re.search(r'[A-Za-zÀ-ÿ]', w['text'])]
        descricao = ' '.join(w['text'] for w in sorted(descricao_ws, key=lambda w: w['x0'])).strip()
        if not descricao or descricao.upper() in {'ITENS DA FATURA', 'QUANT.', 'VALOR'}:
            continue
        def colnum(xmin, xmax):
            return numero_br(_num_no_grupo([w for w in ws if xmin <= (w['x0'] + w['x1'])/2 < xmax]))
        # Ignora palavras que pertencem a cabeçalhos e não a linhas faturadas.
        if descricao.lower().startswith(('itens da fatura', 'itens de fatura', 'quant', 'preço unitário')):
            continue
        itens.append({
            'descricao': descricao,
            'quantidade': colnum(page.width * 0.198, page.width * 0.276),
            'preco_unitario_com_tributos': colnum(page.width * 0.276, page.width * 0.363),
            'valor': colnum(page.width * 0.363, page.width * 0.445),
            'pis_cofins': colnum(page.width * 0.445, page.width * 0.504),
            'base_calculo_icms': colnum(page.width * 0.504, page.width * 0.571),
            'aliquota_icms': colnum(page.width * 0.571, page.width * 0.613),
            'valor_icms': colnum(page.width * 0.613, page.width * 0.672),
            'tarifa_sem_tributos': colnum(page.width * 0.672, page.width * 0.728),
        })

    # Itens financeiros (retenções) que aparecem na parte inferior da tabela amarela.
    texto_pdf = '\n'.join(p.extract_text() or '' for p in paginas_limpas)
    for linha_txt in texto_pdf.splitlines():
        m_fin = re.search(r'^\s*(Tributo A Reter (?:Csll|Irpj|Pis|Cofins))\s+(-?[\d.]+,\d{2})\s*$', linha_txt, re.I)
        if m_fin:
            itens.append({'descricao': m_fin.group(1).strip(), 'quantidade': None,
                          'preco_unitario_com_tributos': None, 'valor': numero_br(m_fin.group(2)),
                          'pis_cofins': None, 'base_calculo_icms': None, 'aliquota_icms': None,
                          'valor_icms': None, 'tarifa_sem_tributos': None, 'categoria': 'financeiro'})

    # Impostos: base de cálculo, alíquota e valor.
    zona = zonas.get('impostos')
    for linha in _agrupar_linhas([w for w in words if zona and zona[0] <= w['top'] <= zona[1] and w['x0'] >= page.width * .68]):
        ws = linha['words']
        texto = ' '.join(w['text'] for w in sorted(ws, key=lambda w: w['x0']))
        nome = next((n for n in ('ICMS', 'PIS', 'COFINS') if re.match(r'^' + n + r'\b', texto, re.I)), None)
        if not nome:
            continue
        # A nova fatura deslocou ligeiramente as colunas do quadro de tributos.
        # A sequência da linha é estável: base, alíquota e valor; não dependemos
        # mais de três limites X absolutos/proporcionais.
        tokens = []
        for w in sorted(ws, key=lambda a: a['x0']):
            token = w['text'].replace('%', '')
            if NUM_RE.fullmatch(token):
                tokens.append(token)
        base, aliquota, valor = (None, None, None)
        if len(tokens) >= 3:
            base, aliquota, valor = [numero_br(x) for x in tokens[-3:]]
        impostos.append({'tributo': nome, 'base_calculo': base,
                         'aliquota_percentual': aliquota, 'valor': valor})

    # Área verde: suporta o layout antigo (linhas iniciadas por RG) e a nova
    # fatura (Grandeza + Posto horário, sem código RG no início da linha).
    zona = zonas.get('leituras')
    linhas_leitura = _agrupar_linhas([w for w in words if zona and zona[0] <= w['top'] <= zona[1] and 0 <= w['x0'] <= page.width * .62])
    mapa_novo = {
        'consumo kwh fp': 'Consumo Fora Ponta',
        'consumo kwh pt': 'Consumo Ponta',
        'demanda kw fp': 'Demanda Fora Ponta',
        'demanda kw pt': 'Demanda Ponta',
        'dm corr kvar fp': 'Dem. Reat. Exced. FP',
        'dm corr kvar pf': 'Dem. Reat. Exced. FP',
        'dm corr kvar pt': 'Dem. Reat. Exced. Pta',
        'en exce kvarh fp': 'Reat. Exced. F. Ponta',
        'en exce kvarh pt': 'Reat. Exced. Ponta',
    }
    for linha in linhas_leitura:
        ws = sorted(linha['words'], key=lambda w: w['x0'])
        texto_linha = ' '.join(w['text'] for w in ws)
        # Layout antigo com identificador de medidor RG.
        if re.search(r'RG\w+', texto_linha, re.I):
            nums = [w for w in ws if NUM_RE.fullmatch(w['text'])]
            if not nums:
                continue
            consumo_word = next((w for w in reversed(nums) if w['x0'] >= page.width * 0.479), nums[-1])
            descr_words = [w['text'] for w in ws if page.width * 0.109 <= w['x0'] < page.width * 0.235 and not NUM_RE.fullmatch(w['text'])]
            descricao = ' '.join(descr_words).strip()
            unidade = next((w['text'] for w in ws if w['text'].lower() in {'kwh', 'kvarh', 'kvarhe', 'kvar', 'kw'}), None)
            if descricao:
                leituras.append({'grandeza': descricao, 'consumo': numero_br(consumo_word['text']), 'unidade': unidade})
            continue

        # Layout novo: rótulo à esquerda, posto PT/FP na coluna seguinte e
        # valor medido na coluna Consumo (x aproximadamente 45-49% da página).
        label = ' '.join(w['text'] for w in ws if w['x0'] < page.width * .205 and not NUM_RE.fullmatch(w['text']))
        posto = next((w['text'].upper() for w in ws
                      if page.width * .205 <= w['x0'] <= page.width * .245
                      and w['text'].upper() in {'PT', 'FP', 'PF', 'TP'}), None)
        if not label or not posto:
            continue
        chave_base = _normalizar_texto_curto(label)
        chave_base = re.sub(r'\s+', ' ', chave_base).strip()
        chave = f'{chave_base} {posto.lower()}'
        canon = mapa_novo.get(chave)
        if not canon:
            # Preserva grandezas novas não previstas sem atribuir nomenclatura errada.
            canon = f'{label.strip()} {posto}'
        candidatos_num = [w for w in ws if page.width * .42 <= (w['x0'] + w['x1']) / 2 <= page.width * .50
                          and NUM_RE.fullmatch(w['text'])]
        if not candidatos_num:
            continue
        valor_lido = numero_br(candidatos_num[-1]['text'])
        unidade = next((w['text'] for w in ws if w['text'].lower() in {'kwh', 'kvarh', 'kvarhe', 'kvar', 'kw'}), None)
        leituras.append({'grandeza': canon, 'consumo': valor_lido, 'unidade': unidade})

    diagnostico['pagina_tabelas'] = indice_pagina + 1
    diagnostico['total_paginas'] = len(paginas)
    return leituras, itens, impostos, demandas, diagnostico, faltantes


def extrair_fatura(texto, nome_arquivo, hash_arquivo, paginas=None):
    # Remove a marca d'água em nível de caractere antes da extração textual e tabular.
    paginas_limpas = [_pagina_sem_marca_dagua(pg) for pg in (paginas or [])]
    if paginas_limpas:
        texto = '\n'.join(pg.extract_text() or '' for pg in paginas_limpas)

    # Prioriza o campo identificado e impede que mês dentro de data dd/mm/aaaa
    # seja confundido com competência.
    m_comp = re.search(r'(?<![/\d])(0[1-9]|1[0-2])/(20\d{2})\s+(\d{2}/\d{2}/\d{4})\s+(?:R\$\s*)?([\d.]+,\d{2})', texto)
    competencia_rotulada = primeiro(r'(?:Conta\s+Mês|Competência|Referência)\s*:?[\s\n]+((?:0[1-9]|1[0-2])/20\d{2})', texto)
    competencia = competencia_rotulada or (f'{m_comp.group(1)}/{m_comp.group(2)}' if m_comp else primeiro(r'(?<![/\d])((?:0[1-9]|1[0-2])/20\d{2})\b', texto))
    vencimento = m_comp.group(3) if m_comp else primeiro(r'(?:VENCIMENTO|Vencimento)\s*\n?\s*(\d{2}[./]\d{2}[./]\d{4})', texto)
    valor_total = numero_br(m_comp.group(4)) if m_comp else None
    if valor_total is None:
        valor_boleto = primeiro(r'VALOR DOCUMENTO\s*\n[^\n]*?R\$\s*([\d.]+,\d{2})', texto)
        if not valor_boleto:
            valor_boleto = primeiro(r'(?:TOTAL A PAGAR|VALOR COBRADO|TOTAL)\s*:?\s*(?:R\$\s*)?([\d.]+,\d{2})', texto)
        valor_total = numero_br(valor_boleto)

    # UC: primeiro procura o número antigo formatado; depois o rótulo explícito
    # da fatura nova; por último usa o número de oito dígitos no bloco da UC.
    uc = primeiro(r'\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b', texto)
    if not uc:
        uc = primeiro(r'Número\s+da\s+UC\s*:?\s*(\d{6,12})', texto)
    if not uc and paginas_limpas:
        # Na fatura nova, o rótulo e o número da UC podem não ser extraídos como
        # texto; o valor fica no bloco laranja, à direita do endereço (x ~ 230 pt).
        ws_uc = paginas_limpas[0].extract_words(x_tolerance=1.5, y_tolerance=2)
        candidatos_uc = [w for w in ws_uc if re.fullmatch(r'\d{8}', w['text'])
                         and paginas_limpas[0].width * .34 <= w['x0'] <= paginas_limpas[0].width * .55
                         and 115 <= w['top'] <= 155]
        if candidatos_uc:
            uc = candidatos_uc[-1]['text']
    if not uc:
        # Fallback textual restrito: escolhe o último identificador de oito
        # dígitos antes do quadro de itens, evitando o CNPJ mascarado.
        candidatos_uc = re.findall(r'(?<!\d)(\d{8})(?!\d)', texto[:texto.find('Itens de fatura') if 'Itens de fatura' in texto else 2500])
        if candidatos_uc:
            uc = candidatos_uc[-1]

    cc = primeiro(r'Nome do Cliente:.*?C\.C\.?\s*:?[^^\n]*\n\s*SANEP[^\n]*?\s(\d{6,})\s+[A-Z0-9]+\s+\d{2}/\d{4}', texto, re.I | re.S)
    if not cc:
        cc = primeiro(r'\bC\.C\.?\s*:?\s*(\d{6,})\b', texto)
    emissao = primeiro(r'DATA DE EMISSÃO:\s*(\d{2}/\d{2}/\d{4})', texto)
    subgrupo = primeiro(r'SUBGRUPO:\s*([A-Z0-9]+)', texto)
    modalidade = primeiro(r'(?:MODALIDADE TARIFÁRIA|TIPO DE TARIFA):\s*([A-Z0-9_.-]+)', texto)
    if not modalidade:
        modalidade = primeiro(r'TARIFÁRIA:\s*([A-Z0-9_.-]+)', texto)
    grupo_tensao = primeiro(r'GRUPO DE TENSÃO:\s*([A-Z0-9]+)', texto)
    if not grupo_tensao and modalidade:
        grupo_tensao = modalidade[0]
    nome_cliente = primeiro(r'^\s*(SANEP[^\n]*)', texto)
    fp = numero_br(primeiro(r'FATOR DE POTÊNCIA:\s*([0-9]+,[0-9]+)', texto))

    # Leitura anterior/atual: tenta o cabeçalho tradicional e, na fatura nova,
    # lê as duas primeiras datas do quadro "Data das Leituras".
    leitura_anterior = primeiro(r'Leitura Anterior\s+Leitura Atual\s+Nº de Dias\s+Próxima Leitura\s*\n.*?\s(\d{2}/\d{2}/\d{4})\s+\d{2}/\d{2}/\d{4}', texto)
    leitura_atual = primeiro(r'Leitura Anterior\s+Leitura Atual\s+Nº de Dias\s+Próxima Leitura\s*\n.*?\s\d{2}/\d{2}/\d{4}\s+(\d{2}/\d{2}/\d{4})', texto)
    if not leitura_anterior or not leitura_atual:
        for linha in texto.splitlines()[:12]:
            datas = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', linha)
            if len(datas) >= 3:
                leitura_anterior, leitura_atual = datas[0], datas[1]
                break

    leituras, itens, impostos, demandas, zonas_ancoradas, ancoras_ausentes = _extrair_tabelas_pdf(paginas or [])
    # Fallback textual para o novo rótulo de demanda contratada, inclusive quando
    # a camada de texto posiciona a unidade kW na mesma linha sem parênteses.
    if demandas.get('demanda_contratada_unica_kw') is None:
        valor_demanda = primeiro(r'Demanda\s+(?:Contratada\s+Única|Todos\s+os\s+Períodos)\s*:?\s*([\d.,]+)\s*kW', texto)
        if valor_demanda:
            demandas['demanda_contratada_unica_kw'] = numero_br(valor_demanda)
    if demandas.get('demanda_contratada_unica_kw') is not None and demandas.get('demanda_contratada_fora_ponta_kw') is None:
        demandas['demanda_contratada_fora_ponta_kw'] = demandas['demanda_contratada_unica_kw']
    valores_leitura = {}
    for item in leituras:
        chave = re.sub(r'[^a-z0-9]+', '_', item['grandeza'].lower()).strip('_')
        valores_leitura[chave] = item['consumo']

    return {
        'arquivo_origem': nome_arquivo,
        'hash_arquivo': hash_arquivo,
        'versao_extracao': 5,
        'nome_cliente': nome_cliente,
        'grupo_tensao': grupo_tensao,
        'subgrupo': subgrupo,
        'modalidade_tarifaria': modalidade,
        'unidade_consumidora': uc,
        'conta_contrato': cc,
        'data_emissao': emissao,
        'competencia': competencia,
        'data_vencimento': vencimento,
        'leitura_anterior': leitura_anterior,
        'leitura_atual': leitura_atual,
        'valor_total': valor_total,
        'fator_potencia': fp,
        'demandas_contratadas': demandas,
        'zonas_geometricas_ancoradas': zonas_ancoradas,
        'ancoras_ausentes': ancoras_ausentes,
        'leituras': leituras,
        'valores_lidos': valores_leitura,
        'itens': itens,
        'impostos': impostos,
        'status_validacao': None,
        'avisos_validacao': None,
    }

