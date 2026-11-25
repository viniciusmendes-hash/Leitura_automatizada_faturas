import re
import unicodedata


def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', texto).strip().casefold()


def validar_fatura(fatura, validar_valor_total=True):
    """Valida presença e coerência básica sem corrigir silenciosamente os dados."""
    avisos = []
    obrigatorios = ['arquivo_origem', 'competencia', 'unidade_consumidora', 'valor_total']
    for campo in obrigatorios:
        if fatura.get(campo) in (None, ''):
            avisos.append(f'Campo obrigatório ausente ou não identificado: {campo}')

    comp = fatura.get('competencia')
    if comp and not re.fullmatch(r'(0[1-9]|1[0-2])/20\d{2}', str(comp)):
        avisos.append(f'Competência em formato inesperado: {comp}')
    if validar_valor_total and fatura.get('valor_total') is not None and fatura['valor_total'] <= 0:
        avisos.append('Valor total menor ou igual a zero.')

    fp = fatura.get('fator_potencia')
    if fp is not None and not 0 <= fp <= 1.1:
        avisos.append(f'Fator de potência fora do intervalo esperado: {fp}')

    leituras = fatura.get('leituras') or []
    itens = fatura.get('itens') or []
    impostos = fatura.get('impostos') or []
    if not itens:
        avisos.append('Nenhum item faturado foi identificado; revisar extração do layout.')
    if not leituras:
        avisos.append('Nenhuma grandeza da tabela de valores lidos foi identificada.')
    if not impostos:
        avisos.append('Nenhum imposto foi identificado na tabela de tributos.')

    # Confere se os tributos essenciais foram reconhecidos, sem presumir alíquotas.
    tributos = {_normalizar(x.get('tributo')) for x in impostos}
    for nome in ('icms', 'pis', 'cofins'):
        if nome not in tributos:
            avisos.append(f'Tributo {nome.upper()} não identificado na extração.')
    for imposto in impostos:
        if imposto.get('base_calculo') is None or imposto.get('valor') is None:
            avisos.append(f"Dados incompletos no quadro de {imposto.get('tributo', 'tributo')}.")

    # Verificação cruzada do consumo total com as parcelas ponta e fora ponta.
    por_nome = {_normalizar(x.get('grandeza')): x.get('consumo') for x in leituras}
    ponta = next((v for k, v in por_nome.items() if 'consumo ponta' in k and 'fora' not in k), None)
    fora = next((v for k, v in por_nome.items() if 'consumo fora ponta' in k), None)
    total = next((v for k, v in por_nome.items() if k == 'consumo'), None)
    if ponta is not None and fora is not None and total is not None:
        diferenca = abs((ponta + fora) - total)
        if diferenca > 1.0:
            avisos.append(
                f'Inconsistência no consumo: ponta ({ponta}) + fora ponta ({fora}) '
                f'não coincide com consumo total ({total}); diferença={diferenca}.'
            )

    ancoras_ausentes = fatura.get('ancoras_ausentes') or []
    if ancoras_ausentes:
        avisos.append('Âncoras geométricas não localizadas: ' + ', '.join(ancoras_ausentes) + '. Conferir o layout do PDF.')
    zonas = fatura.get('zonas_geometricas_ancoradas') or {}
    if not zonas.get('pagina_tabelas'):
        avisos.append('Não foi possível registrar a página de origem das tabelas.')

    return avisos
