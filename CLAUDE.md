## Ambiente de execução

- Python venv em `.venv/` — SEMPRE ativar antes de rodar qualquer comando
- Windows: `.venv\Scripts\activate`
- Usar Apify como fonte principal (FB_ACCESS_TOKEN não configurado por ora)

# FB Ad Spy — Projeto de Espionagem de Anúncios Direct Response

## O que este projeto faz

Automatiza o processo de espionagem da Facebook Ad Library para Marketing de Resposta Direta (MRD).
Captura anúncios por palavras-chave de nicho, analisa criativos (imagem/vídeo), transcreve áudios,
classifica por escala e gera relatórios estruturados localmente — sem pagar ferramentas pagas como AdSpy ou Minea.

## Processo humano que este código automatiza

Baseado no processo do Gustavo Rafaell:
1. Pesquisar na FB Ad Library com palavras-chave específicas de MRD (ex: "truque bariátrico", "blood sugar trick")
2. Filtrar por anúncios **ativos** com maior número de criativos rodando (sinal de oferta escalada)
3. Identificar padrões: mesmo domínio, mesma VSL, múltiplos afiliados rodando a mesma oferta
4. Catalogar: hook, copy, tipo de criativo, dias rodando, quantidade de anúncios ativos
5. Classificar se vale swipe (mínimo 6-10k criativos ativos, ou afiliados somando 50-200k/dia)

## Nichos e palavras-chave monitorados

Ver `/core/keywords.py` — lista completa por nicho (emagrecimento, diabetes, ED, dor nas costas, visão, relacionamento)

## Stack técnica

- **Coleta**: Facebook Ad Library API oficial (Graph API) — sem custo
- **Fallback**: Apify actor `curious_coder/facebook-ads-library-scraper` — se a API nativa não cobrir
- **Análise de texto**: Anthropic Claude API (claude-sonnet-4-20250514)
- **Transcrição de vídeo**: OpenAI Whisper (via API) ou Whisper local (faster-whisper)
- **Análise de imagem**: Claude Vision
- **Storage**: SQLite (`data/ads.db`)
- **Dashboard**: Streamlit (`dashboard/app.py`)
- **Agendamento**: Windows Task Scheduler (ver `scheduler/task.xml`)

## Estrutura de pastas

```
fb_ad_spy/
├── CLAUDE.md                  # Este arquivo — lido pelo Claude Code no início de cada sessão
├── .env                       # Credenciais (não committar)
├── requirements.txt
├── main.py                    # Entry point — roda o pipeline completo
├── core/
│   ├── fb_api.py              # FB Graph API — coleta nativa (TENTAR PRIMEIRO)
│   ├── apify_scraper.py       # Fallback Apify (baseado no código original do usuário)
│   ├── keywords.py            # Palavras-chave por nicho
│   └── config.py              # Configurações globais
├── analysis/
│   ├── text_analyzer.py       # Analisa copy com Claude
│   ├── image_analyzer.py      # Analisa imagem com Claude Vision
│   └── video_analyzer.py      # Download + ffmpeg + Whisper + análise
├── storage/
│   ├── database.py            # SQLite — schema e operações
│   └── dedup.py               # Deduplicação por ad_id
├── dashboard/
│   └── app.py                 # Streamlit dashboard
└── utils/
    ├── logger.py
    └── helpers.py
```

## Decisões técnicas tomadas

- **API nativa antes de Apify**: FB Graph API `/ads_archive` é grátis, tem rate limit de ~200 req/hora.
  Apify custa ~$0.50-2.00 por run. Usar Apify apenas quando precisar de campos não disponíveis na API.
- **Claude em vez de GPT-4o**: O código original usava GPT-4o. Migrado para Claude para consistência e custo.
  Se o usuário quiser manter GPT-4o, descomentar em `analysis/text_analyzer.py`.
- **SQLite em vez de CSV**: O código original gerava CSV. SQLite permite query, dedup e histórico.
- **Whisper local opcional**: `faster-whisper` roda localmente sem custo de API. Configurável em `.env`.

## Variáveis de ambiente necessárias

```
FB_ACCESS_TOKEN=       # Token do Facebook Graph API (ver instruções abaixo)
FB_AD_ACCOUNT_ID=      # Opcional — melhora resultados
ANTHROPIC_API_KEY=     # Para análise de copy e imagem
OPENAI_API_KEY=        # Apenas se usar Whisper API (opcional se usar Whisper local)
APIFY_ACTOR_URL=       # Apenas se usar fallback Apify
USE_LOCAL_WHISPER=true # true = faster-whisper local, false = OpenAI Whisper API
```

## Como obter o FB Access Token

1. Acesse https://developers.facebook.com/tools/explorer/
2. Crie um app ou use um existente
3. Gere um token com permissão `ads_read`
4. Para token de longa duração: exchange via `/oauth/access_token`
5. Tokens de usuário expiram em 60 dias — use token de página para produção

## Próximos passos pendentes

- [ ] Testar rate limits da FB Graph API em produção
- [ ] Implementar renovação automática de token
- [ ] Adicionar filtro por número mínimo de criativos ativos
- [ ] Dashboard: filtro por nicho, dias rodando, tipo de criativo
- [ ] Exportar para Notion (opcional)

## Comandos úteis

```bash
# Rodar pipeline completo
python main.py --nicho emagrecimento --count 50

# Só coleta, sem análise
python main.py --collect-only --nicho diabetes

# Só dashboard
streamlit run dashboard/app.py

# Instalar dependências
pip install -r requirements.txt
```
