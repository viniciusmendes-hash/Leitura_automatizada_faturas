# Automação de leitura de faturas PDF

Primeira versão: processamento em lote, extração de texto, validação básica, SQLite e Excel.

## 1. Requisitos
- Windows 10/11
- Python 3.11 ou 3.12 recomendado
- VS Code (opcional)

## 2. Instalação
Abra o terminal na pasta do projeto e execute:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```
## 3. Preparar os PDFs
Copie as faturas para `entrada\`. 

## 4. Executar manualmente
```bat
python main.py
```
Ou dê duplo clique em `executar.bat`.

Resultados:
- `faturas.db`: banco SQLite
- `saida\relatorio_faturas.xlsx`: abas Faturas e Itens faturados
- `logs\execucao.log`: histórico de execução

O programa usa SHA-256 para ignorar o mesmo arquivo quando ele já foi processado. Se uma fatura for corrigida e o conteúdo mudar, o hash muda e ela será importada como um novo registro; o controle por unidade consumidora + competência deverá ser refinado conforme a política de negócio.

# Automação de leitura de faturas CEEE-Equatorial — versão 2

Esta versão usa o PDF marcado `EBDR-LEST-2026.01.pdf` como referência inicial de layout. O Excel de referência ainda não foi incorporado; os nomes e a ordem das colunas poderão ser ajustados quando ele estiver disponível.

## O que faz
- Processa PDFs da pasta `entrada`.
- Extrai dados de identificação: grupo/subgrupo, modalidade, UC, conta/contrato, emissão, competência, vencimento, leituras anterior/atual e total.
- Localiza âncoras textuais no PDF (por exemplo, “Consumo Ponta”, “Demanda Contratada”, “ICMS” e o código do medidor `RG...`) e calcula janelas geométricas relativas a essas âncoras.
- Extrai as tabelas de valores faturados, impostos, demandas contratadas e valores lidos dentro das janelas calculadas; registra as coordenadas encontradas para auditoria.
- Armazena os registros no SQLite (`faturas.db`), com tabelas de faturas, leituras, itens faturados, impostos e demandas.
- Exporta uma única planilha `saida/relatorio_faturas.xlsx`, com uma linha por fatura, agrupada por UC e ordenada por competência decrescente dentro de cada UC.
- Ignora PDFs já processados com base no hash SHA-256.
- Registra erros e avisos em `logs/execucao.log`.

## Regra de demanda única
Quando a fatura informa demanda contratada única e deixa vazios os campos de demanda contratada ponta e fora ponta, o valor único também é lançado em `demanda_contratada_fora_ponta_kw`, conforme a premissa definida para o modelo de planilha. O valor original permanece em `demanda_contratada_unica_kw`.

## Extração geométrica por âncoras dinâmicas
A extração não depende mais de faixas verticais absolutas fixas para localizar as tabelas. O módulo `extrator.py` normaliza os rótulos (acentos e caixa), procura as âncoras no texto posicionado do `pdfplumber` e calcula as janelas verticais a partir das coordenadas encontradas. As janelas e as âncoras ausentes são gravadas no JSON da fatura no SQLite e as primeiras aparecem no log de execução.

As âncoras atuais são: primeira rubrica “Consumo Ponta” (fallback quando o título da tabela de itens não é extraído), “Demanda Contratada”, “ICMS” no setor direito da página e primeira linha que contém o código de medidor `RG...`. A seleção da região usa âncoras; as faixas horizontais das colunas ainda seguem a geometria do formulário CEEE-Equatorial de referência. Portanto, a solução tolera deslocamentos verticais e pequenas variações de texto, mas uma mudança estrutural das colunas ou um novo modelo de fatura exige calibração e teste.
# Automação de leitura de faturas CEEE-Equatorial — versão 3

Esta versão usa o PDF marcado `EBDR-LEST-2026.01.pdf` como referência inicial de layout.

## Melhorias — versão 3
- A página com maior número de âncoras das tabelas é selecionada automaticamente, em vez de assumir sempre a primeira página.
- As faixas horizontais de leitura foram convertidas para proporções da largura da página, reduzindo a dependência do tamanho físico do PDF.
- As coordenadas e a página selecionada ficam registradas para auditoria.
- A validação verifica competência, presença de ICMS/PIS/COFINS e consistência entre consumo ponta + fora ponta e consumo total. Diferenças superiores a 1 unidade são sinalizadas, sem alterar valores automaticamente.
- O relatório Excel é reordenado em todas as execuções por competência decrescente, considerando ano e mês (por exemplo, 01/2026 antes de 12/2025), independentemente da ordem de processamento.

# Automação de leitura de faturas CEEE-Equatorial — versão 4

Esta versão amplia a compatibilidade com os diferentes layouts de faturas CEEE-Equatorial presentes na pasta `entrada`, incluindo o modelo de 2026.02/2026.03 e os modelos posteriores.

## O que faz
- Processa PDFs da pasta `entrada` e extrai identificação, competência, vencimento, total, datas de leitura, demanda contratada, leituras, itens faturados e tributos.
- Reconhece as variações `MODALIDADE TARIFÁRIA` e `Tipo de Tarifa`; quando o grupo de tensão não aparece, utiliza a primeira letra da modalidade.
- Reconhece `Demanda Contratada Única` e `Demanda Todos os Períodos` como demanda contratada única.
- Localiza a UC no formato antigo ou no campo `Número da UC` do DANFE novo.
- Remove a marca d'água `SEGUNDA VIA` no nível de caractere antes de extrair texto e tabelas, evitando que a marca se misture às descrições e aos números dos itens faturados.
- Interpreta a tabela de leituras nos dois formatos: linhas com identificador `RG...` e tabela `Grandezas / Posto horário`, combinando grandeza e posto (PT/FP).
- Mantém o armazenamento relacional no SQLite e exporta uma planilha horizontal com uma linha por fatura, em ordem decrescente de competência.
- Não extrai nem exporta o número da nota fiscal.

## Novos campos consolidados no Excel
Os campos canônicos são criados mesmo quando o item não aparece na fatura, permanecendo vazios:
- Após `faturado_demanda_ativa_kw_valor`: quantidade, preço unitário e valor de `faturado_demanda_ultrapassagem_kw`.
- Após `faturado_cons_reat_exced_np_kvar_valor`: quantidade, preço unitário e valor de `faturado_cons_reat_exced_fp_kvar`.
- Em seguida: quantidade, preço unitário e valor de `faturado_demanda_reativa_kvar`.

As descrições originais dos itens também são preservadas em colunas próprias. O SQLite continua armazenando cada item em linha própria na tabela `itens_faturados`, com quantidade, preço unitário, valor e dados tributários auxiliares.

## Atualização de banco existente
Cada fatura recebe `versao_extracao = 5`. Ao executar esta versão, os PDFs já existentes no banco com versão anterior são reprocessados e atualizados pela mesma hash, substituindo seus registros de detalhe sem criar uma segunda fatura. O restante do histórico do banco é preservado. Faça uma cópia de segurança de `faturas.db` antes da primeira execução da versão 4.

