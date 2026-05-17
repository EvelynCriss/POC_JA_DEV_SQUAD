Coleta e Tratamento de Dados — JA EletroFrio
Script Python responsável por consumir os endpoints da empresa, tratar os dados e armazená-los no Banco de dados.________________________________________
Pré-requisitos
- PostgreSQL instalado
- O meu esta rodando na porta 5433, mas o de vcs provavelmente ta na porta 5432
- Criar no pgadmin do PostgreSQL uma database chamada refrigeracao
- Acessei pelo DBeaver e criei uma conexão com o banco e por lá consegui ver:
_______________________________________
Instalação
Clone o repositório e instale as dependências:
pip install requests psycopg2-binary
________________________________________
Configuração
Abra o arquivo dados.py e edite as configurações no topo:
DB_CONFIG = {
    "host":     "localhost",
    "port":     5433,
    "database": "refrigeracao",
    "user":     "postgres",
    "password": "SUA_SENHA_AQUI"
}

URL_ALARMES    = "https://URL_DA_EMPRESA/alarmes"
URL_UNIDADES   = "https://URL_DA_EMPRESA/unidades"
URL_TELEMETRIA = "https://URL_DA_EMPRESA/telemetria"

-- como por enquanto o repositório ta privado, já deixei as urls. 
________________________________________
Como executar
python coletar_dados.py
O que o script faz:
1.	Conecta ao PostgreSQL
2.	Cria as tabelas automaticamente se não existirem
3.	Coleta e salva as unidades (lojas)
4.	Coleta e salva os alarmes ativos
5.	Acumula os dispositivos encontrados nos alarmes
6.	Coleta e salva a telemetria de todos os dispositivos conhecidos
________________________________________
Tabelas criadas no banco:

unidades = Cadastro das lojas monitoradas
alarmes	= Alarmes ativos coletados do endpoint
dispositivos = Dispositivos acumulados ao longo do tempo
telemetria = Leituras dos sensores de cada dispositivo
________________________________________
Tratamento de dados:

Nulos no final da telemetria = Removidos — leituras não processadas ainda
Nulos no meio da telemetria	= Preenchidos com o valor anterior (forward fill)
Strings vazias	= Convertidas para NULL
Alarmes duplicados na resposta = Deduplicados por alarme_id antes de inserir
Dispositivos duplicados	= Deduplicados por dispositivo_id antes de inserir
________________________________________
Estrutura das tabelas relevantes para o N8N:

alarmes:

SELECT
    alarme_id,
    loja_nm,
    dispositivo_id,
    dispositivo_nm,
    alarme_desc,
    criticidade,       -- 'A' = Alto, 'M' = Médio
    pp_abertura,       -- 'C' = aberto
    evento_dh_cad,     -- NULL = sem resposta do analista
    tempo,             -- ex: '1h', '30m'
    alarme_dh_cad

FROM alarmes
WHERE evento_dh_cad IS NULL  -- alarmes sem resposta
ORDER BY alarme_dh_cad DESC;

telemetria:

SELECT
    dispositivo_id,
    label,             -- ex: 'Temperatura Ambiente', 'Setpoint Ambiente'
    timestamp,
    valor
FROM telemetria
WHERE dispositivo_id = SEU_DISPOSITIVO_ID
ORDER BY timestamp DESC
LIMIT 288;             -- últimas 24h (288 leituras de 5 em 5 min)

dispositivos:

SELECT
    dispositivo_id,
    dispositivo_nm,
    loja_nm,
    conta_nm,
    grupo_nm,
    subgrupo_nm
FROM dispositivos;
________________________________________
N8N:
- O script deve ser executado a cada 5 minutos para manter o banco atualizado.
Opção 1 — N8N (recomendado)
Configure um fluxo no N8N com trigger de tempo (a cada 5 minutos) que executa o script Python.


