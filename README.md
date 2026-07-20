# FB Ads Spy

**Inteligência de ads competitivos via Facebook Ad Library com análise automática**

## O que é

Ferramenta que automatiza o processo de "ad spying" descrito por Gustavo Rafaell: monitora anúncios ativos de Direct Response em 10 nichos, captura metadados, transcreve vídeos, e armazena análise em banco de dados.

Não é skill do Claude Code, é um pipeline Python/Node.js com 4 estágios:
1. **Count Agent** — conta ads por keyword
2. **Metadata Agent** — extrai dados individuais de anúncios
3. **Analyze Agent** — baixa media, executa Whisper + Vision, análise Claude
4. **Benchmark Agent** — sintetiza dados em relatório por nicho

## Instalação

1. Clone ou baixe o repositório
2. Configure o `.env` (Supabase URL/key ou SQLite local)
3. Ative o venv: `.venv\Scripts\activate`
4. Instale deps: `pip install -r requirements.txt`
5. Configure credenciais de Facebook/Supabase

## Como usar

```bash
# Setup inicial
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Rodar stages manualmente
python agents/count_agent.py
python agents/metadata_agent.py
python agents/analyze_agent.py
python agents/benchmark_agent.py

# Ou via GitHub Actions (scheduled diariamente)
```

## Saída

- `keyword_snapshots` — count de ads (video/image/total) por keyword
- `ads` table — metadados de cada anúncio
- `analyses` — Claude analysis de copy + Whisper transcription
- `benchmark_reports` — síntese por nicho e data

## Armazenamento

- **SQLite local** (`data/ads.db`) — padrão
- **Supabase** — se `DATABASE_URL` estiver em `.env`

## Tempo + Custo

- Stage 1: ~5 min (count)
- Stage 2: ~10 min (metadata)
- Stage 3: ~30-60 min (download + analysis)
- **Cost:** Whisper + Claude Vision (pago por token)

## Dependências

- Playwright (navegação web)
- Python 3.8+
- OpenAI Whisper
- Supabase (opcional) ou SQLite

## Licença

CC BY 4.0 — Veja LICENSE.md

## Autor

Mikael Lovrin — FEG (Direct Response Marketing)

---

**Baseado em:** Ad spying methodology by Gustavo Rafaell
