import requests
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timedelta

# CONFIGURAÇÕES

DB_CONFIG = {
    "host":     "localhost",
    "port":     5433,
    "database": "refrigeracao",
    "user":     "postgres",
    "password": "postgre"
}

URL_ALARMES    = "https://credenciamento.eletrofrio.com.br:5900/galileo/api/api_hackathon?route=alarmes"
URL_UNIDADES   = "https://credenciamento.eletrofrio.com.br:5900/galileo/api/api_hackathon?route=unidades"
URL_TELEMETRIA = "https://credenciamento.eletrofrio.com.br:5900/galileo/api/api_hackathon?route=telemetria&dispositivoId={dispositivo_id}"


# CONEXÃO COM POSTGRESQL
def conectar():
    conn = psycopg2.connect(**DB_CONFIG)
    print("Conectado ao PostgreSQL com sucesso.")
    return conn


# CRIAR TABELAS
def criar_tabelas(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS unidades (
                loja_id         INTEGER PRIMARY KEY,
                loja_nm         TEXT,
                loja_apelido    TEXT,
                conta_id        INTEGER,
                conta_nm        TEXT,
                tp_contrato_nm  TEXT,
                dt_val_contrato TIMESTAMP,
                nr_pedido       TEXT,
                telefone        TEXT,
                endereco        TEXT,
                dh_sinal_vida   TIMESTAMP,
                ativo           BOOLEAN,
                atualizado_em   TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS alarmes (
                alarme_id       INTEGER PRIMARY KEY,
                conta_id        INTEGER,
                conta_nm        TEXT,
                loja_id         INTEGER,
                loja_nm         TEXT,
                nr_pedido       TEXT,
                dispositivo_id  INTEGER,
                dispositivo_nm  TEXT,
                grupo_nm        TEXT,
                subgrupo_nm     TEXT,
                alarme_dh_cad   TIMESTAMP,
                alarme_desc     TEXT,
                silenciar_ate   TIMESTAMP,
                criticidade     TEXT,
                pp_abertura     TEXT,
                evento_dh_cad   TIMESTAMP,
                evento_desc     TEXT,
                evento_usu      TEXT,
                tempo           TEXT,
                inserido_em     TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS dispositivos (
                dispositivo_id  INTEGER PRIMARY KEY,
                dispositivo_nm  TEXT,
                loja_id         INTEGER,
                loja_nm         TEXT,
                conta_id        INTEGER,
                conta_nm        TEXT,
                grupo_nm        TEXT,
                subgrupo_nm     TEXT,
                primeira_vez    TIMESTAMP DEFAULT NOW(),
                atualizado_em   TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS telemetria (
                id              SERIAL PRIMARY KEY,
                dispositivo_id  INTEGER,
                label           TEXT,
                timestamp       TIMESTAMP,
                valor           NUMERIC(10, 4),
                inserido_em     TIMESTAMP DEFAULT NOW(),
                UNIQUE (dispositivo_id, label, timestamp)
            );
        """)
        conn.commit()
    print("Tabelas criadas/verificadas com sucesso.")


# FUNÇÕES DE TRATAMENTO
def texto_ou_nulo(valor):
    if valor is None:
        return None
    valor = str(valor).strip()
    return None if valor == "" else valor

def data_ou_nulo(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except Exception:
        return None

def remover_nulos_finais(lista):
    while lista and lista[-1] is None:
        lista.pop()
    return lista

def forward_fill(lista):
    for i in range(1, len(lista)):
        if lista[i] is None and lista[i - 1] is not None:
            lista[i] = lista[i - 1]
    return lista

def tratar_nulos_telemetria(valores):
    valores = list(valores)
    valores = remover_nulos_finais(valores)
    valores = forward_fill(valores)
    return valores

def reconstruir_timestamps(qtd_valores):
    agora = datetime.now().replace(second=0, microsecond=0)
    inicio = agora - timedelta(hours=24)
    return [inicio + timedelta(minutes=5 * i) for i in range(qtd_valores)]

def timestamps_dos_labels(labels, qtd_valores):
    timestamps = []
    hoje = datetime.now().date()
    hora_ref = None
    for i, t in enumerate(labels[:qtd_valores]):
        try:
            hora = datetime.strptime(t, "%H:%M").time()
            if hora_ref and hora < hora_ref:
                hoje = hoje + timedelta(days=1)
            hora_ref = hora
            timestamps.append(datetime.combine(hoje, hora))
        except Exception:
            timestamps.append(
                datetime.now() - timedelta(hours=24) + timedelta(minutes=5 * i)
            )
    return timestamps


# PROCESSAR UNIDADES
def processar_unidades(conn):
    print("\nColetando unidades...")
    resp = requests.get(URL_UNIDADES, timeout=30)
    resp.raise_for_status()
    dados = resp.json()

    # deduplica por loja_id
    unidades_dict = {}
    for u in dados:
        loja_id = u.get("lojaId")
        unidades_dict[loja_id] = (
            loja_id,
            texto_ou_nulo(u.get("lojaNm")),
            texto_ou_nulo(u.get("lojaApelido")),
            u.get("contaId"),
            texto_ou_nulo(u.get("contaNm")),
            texto_ou_nulo(u.get("tpContratoNm")),
            data_ou_nulo(u.get("dtValContrato")),
            texto_ou_nulo(u.get("nrPedido")),
            texto_ou_nulo(u.get("telefone")),
            texto_ou_nulo(u.get("endereco")),
            data_ou_nulo(u.get("dhSinalVida")),
            u.get("ativo", False),
        )

    registros = list(unidades_dict.values())

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO unidades (
                loja_id, loja_nm, loja_apelido, conta_id, conta_nm,
                tp_contrato_nm, dt_val_contrato, nr_pedido, telefone,
                endereco, dh_sinal_vida, ativo
            ) VALUES %s
            ON CONFLICT (loja_id) DO UPDATE SET
                loja_nm         = EXCLUDED.loja_nm,
                loja_apelido    = EXCLUDED.loja_apelido,
                tp_contrato_nm  = EXCLUDED.tp_contrato_nm,
                dt_val_contrato = EXCLUDED.dt_val_contrato,
                dh_sinal_vida   = EXCLUDED.dh_sinal_vida,
                ativo           = EXCLUDED.ativo,
                atualizado_em   = NOW();
        """, registros)
        conn.commit()
    print(f"{len(registros)} unidades salvas no banco.")


# PROCESSAR ALARMES + ACUMULAR DISPOSITIVOS
def processar_alarmes(conn):
    print("\nColetando alarmes...")
    resp = requests.get(URL_ALARMES, timeout=30)
    resp.raise_for_status()
    dados = resp.json()

    # deduplica alarmes e dispositivos por ID
    alarmes_dict = {}
    dispositivos_dict = {}

    for a in dados:
        alarme_id      = a.get("alarmeId")
        dispositivo_id = a.get("dispositivoId")

        alarmes_dict[alarme_id] = (
            alarme_id,
            a.get("contaId"),
            texto_ou_nulo(a.get("contaNm")),
            a.get("lojaId"),
            texto_ou_nulo(a.get("lojaNm")),
            texto_ou_nulo(a.get("nrPedido")),
            dispositivo_id,
            texto_ou_nulo(a.get("dispositivoNm")),
            texto_ou_nulo(a.get("grupoNm")),
            texto_ou_nulo(a.get("subgrupoNm")),
            data_ou_nulo(a.get("alarmeDhCad")),
            texto_ou_nulo(a.get("alarmeDesc")),
            data_ou_nulo(a.get("silenciarAte")),
            texto_ou_nulo(a.get("criticidade")),
            texto_ou_nulo(a.get("ppAbertura")),
            data_ou_nulo(a.get("eventoDhCad")),
            texto_ou_nulo(a.get("eventoDesc")),
            texto_ou_nulo(a.get("eventoUsu")),
            texto_ou_nulo(a.get("tempo")),
        )

        dispositivos_dict[dispositivo_id] = (
            dispositivo_id,
            texto_ou_nulo(a.get("dispositivoNm")),
            a.get("lojaId"),
            texto_ou_nulo(a.get("lojaNm")),
            a.get("contaId"),
            texto_ou_nulo(a.get("contaNm")),
            texto_ou_nulo(a.get("grupoNm")),
            texto_ou_nulo(a.get("subgrupoNm")),
        )

    registros_alarmes      = list(alarmes_dict.values())
    registros_dispositivos = list(dispositivos_dict.values())

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO alarmes (
                alarme_id, conta_id, conta_nm, loja_id, loja_nm,
                nr_pedido, dispositivo_id, dispositivo_nm, grupo_nm,
                subgrupo_nm, alarme_dh_cad, alarme_desc, silenciar_ate,
                criticidade, pp_abertura, evento_dh_cad, evento_desc,
                evento_usu, tempo
            ) VALUES %s
            ON CONFLICT (alarme_id) DO UPDATE SET
                silenciar_ate = EXCLUDED.silenciar_ate,
                evento_dh_cad = EXCLUDED.evento_dh_cad,
                evento_desc   = EXCLUDED.evento_desc,
                evento_usu    = EXCLUDED.evento_usu,
                tempo         = EXCLUDED.tempo;
        """, registros_alarmes)

        execute_values(cur, """
            INSERT INTO dispositivos (
                dispositivo_id, dispositivo_nm, loja_id, loja_nm,
                conta_id, conta_nm, grupo_nm, subgrupo_nm
            ) VALUES %s
            ON CONFLICT (dispositivo_id) DO UPDATE SET
                dispositivo_nm = EXCLUDED.dispositivo_nm,
                grupo_nm       = EXCLUDED.grupo_nm,
                subgrupo_nm    = EXCLUDED.subgrupo_nm,
                atualizado_em  = NOW();
        """, registros_dispositivos)

        conn.commit()

    print(f"{len(registros_alarmes)} alarmes salvos.")
    print(f"{len(registros_dispositivos)} dispositivos únicos acumulados.")


# BUSCAR IDs ACUMULADOS DE DISPOSITIVOS
def buscar_dispositivos(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT dispositivo_id FROM dispositivos ORDER BY dispositivo_id;")
        ids = [row[0] for row in cur.fetchall()]
    print(f"\n{len(ids)} dispositivos conhecidos para coletar telemetria.")
    return ids


# PROCESSAR TELEMETRIA
def processar_telemetria(conn):
    dispositivos_ids = buscar_dispositivos(conn)

    if not dispositivos_ids:
        print("Nenhum dispositivo encontrado. Rode novamente após coletar alarmes.")
        return

    print("Coletando telemetria...")
    total_salvo = 0

    for dispositivo_id in dispositivos_ids:
        print(f"  -> Dispositivo {dispositivo_id}...")
        try:
            resp = requests.get(
                URL_TELEMETRIA,
                params={"dispositivoId": dispositivo_id},
                timeout=30
            )
            resp.raise_for_status()
            dados = resp.json()

            datasets = dados.get("datasets", [])
            labels   = dados.get("labels", [])

            registros = []
            for dataset in datasets:
                label   = dataset.get("label", "")
                valores = list(dataset.get("values", []))

                valores = tratar_nulos_telemetria(valores)

                if labels and len(labels) >= len(valores):
                    timestamps = timestamps_dos_labels(labels, len(valores))
                else:
                    timestamps = reconstruir_timestamps(len(valores))

                for ts, valor in zip(timestamps, valores):
                    if valor is not None:
                        registros.append((dispositivo_id, label, ts, valor))

            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO telemetria (dispositivo_id, label, timestamp, valor)
                    VALUES %s
                    ON CONFLICT (dispositivo_id, label, timestamp) DO NOTHING;
                """, registros)
                conn.commit()

            total_salvo += len(registros)
            print(f"    {len(registros)} leituras salvas.")

        except Exception as e:
            print(f"    Erro no dispositivo {dispositivo_id}: {e}")

    print(f"\nTotal de leituras salvas: {total_salvo}")


# MAIN
if __name__ == "__main__":
    conn = conectar()
    try:
        criar_tabelas(conn)
        processar_unidades(conn)
        processar_alarmes(conn)
        processar_telemetria(conn)
        print("\nProcessamento concluido com sucesso.")
    except Exception as e:
        print(f"\nErro geral: {e}")
    finally:
        conn.close()
