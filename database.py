"""
Módulo de banco de dados SQLite para o app de controle financeiro.
"""
import sqlite3
import os
import sys
import hashlib
from datetime import datetime, date
from contextlib import contextmanager

# No Streamlit Cloud (Linux) usa /tmp para garantir filesystem gravável.
# Localmente (Windows/Mac) usa o diretório do próprio app.
if sys.platform.startswith("linux"):
    DB_PATH = "/tmp/financeiro.db"
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "financeiro.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS fontes_renda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS despesas_planejamento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            detalhes TEXT,
            ativo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS meses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ano INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            observacoes TEXT,
            UNIQUE(ano, mes)
        );

        CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mes_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            data_criacao TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (mes_id) REFERENCES meses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS viagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            data_viagem TEXT,
            mes_id INTEGER,
            FOREIGN KEY (mes_id) REFERENCES meses(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS lancamentos_viagem (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viagem_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            pago_por_nina INTEGER NOT NULL DEFAULT 0,
            data_criacao TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (viagem_id) REFERENCES viagens(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS parcelamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor_parcela REAL NOT NULL,
            num_parcelas INTEGER NOT NULL,
            parcela_atual INTEGER NOT NULL DEFAULT 1,
            mes_inicio_id INTEGER,
            ativo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (mes_inicio_id) REFERENCES meses(id)
        );

        CREATE TABLE IF NOT EXISTS dividas_nino (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor_total REAL NOT NULL,
            quitada INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pagamentos_divida (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            divida_id INTEGER NOT NULL,
            mes_id INTEGER NOT NULL,
            valor REAL NOT NULL,
            data_criacao TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (divida_id) REFERENCES dividas_nino(id) ON DELETE CASCADE,
            FOREIGN KEY (mes_id) REFERENCES meses(id) ON DELETE CASCADE
        );
        """)


# ---- FONTES DE RENDA ----

def listar_fontes_renda():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM fontes_renda WHERE ativo=1 ORDER BY nome").fetchall()


def adicionar_fonte_renda(nome, valor):
    with get_conn() as conn:
        conn.execute("INSERT INTO fontes_renda (nome, valor) VALUES (?, ?)", (nome, valor))


def atualizar_fonte_renda(id_, nome, valor):
    with get_conn() as conn:
        conn.execute("UPDATE fontes_renda SET nome=?, valor=? WHERE id=?", (nome, valor, id_))


def remover_fonte_renda(id_):
    with get_conn() as conn:
        conn.execute("UPDATE fontes_renda SET ativo=0 WHERE id=?", (id_,))


def total_renda():
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(SUM(valor),0) as total FROM fontes_renda WHERE ativo=1").fetchone()
        return row["total"]


# ---- DESPESAS PLANEJAMENTO ----

def listar_despesas_planejamento():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM despesas_planejamento WHERE ativo=1 ORDER BY nome").fetchall()


def adicionar_despesa_planejamento(nome, valor, detalhes=None):
    with get_conn() as conn:
        conn.execute("INSERT INTO despesas_planejamento (nome, valor, detalhes) VALUES (?, ?, ?)",
                     (nome, valor, detalhes))


def atualizar_despesa_planejamento(id_, nome, valor, detalhes=None):
    with get_conn() as conn:
        conn.execute("UPDATE despesas_planejamento SET nome=?, valor=?, detalhes=? WHERE id=?",
                     (nome, valor, detalhes, id_))


def remover_despesa_planejamento(id_):
    with get_conn() as conn:
        conn.execute("UPDATE despesas_planejamento SET ativo=0 WHERE id=?", (id_,))


def total_despesas_planejamento():
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(SUM(valor),0) as total FROM despesas_planejamento WHERE ativo=1").fetchone()
        return row["total"]


# ---- MESES ----

def listar_meses():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM meses ORDER BY ano DESC, mes DESC").fetchall()


def obter_mes(mes_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM meses WHERE id=?", (mes_id,)).fetchone()


def criar_mes(ano, mes):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO meses (ano, mes) VALUES (?, ?)", (ano, mes))
        return conn.execute("SELECT * FROM meses WHERE ano=? AND mes=?", (ano, mes)).fetchone()


def remover_mes(mes_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM meses WHERE id=?", (mes_id,))


def atualizar_observacoes_mes(mes_id, observacoes):
    with get_conn() as conn:
        conn.execute("UPDATE meses SET observacoes=? WHERE id=?", (observacoes or None, mes_id))


def copiar_lancamentos_mes(origem_id, destino_id, categorias):
    """Copia lançamentos das categorias indicadas de um mês para outro."""
    with get_conn() as conn:
        for cat in categorias:
            rows = conn.execute(
                "SELECT categoria, descricao, valor FROM lancamentos WHERE mes_id=? AND categoria=?",
                (origem_id, cat)
            ).fetchall()
            for r in rows:
                conn.execute(
                    "INSERT INTO lancamentos (mes_id, categoria, descricao, valor) VALUES (?, ?, ?, ?)",
                    (destino_id, r["categoria"], r["descricao"], r["valor"])
                )


# ---- LANÇAMENTOS MENSAIS ----

CATEGORIAS_MES = [
    ("conta_fixa", "Contas Fixas"),
    ("parcelada", "Parceladas"),
    ("desp_nina", "Desp. Nina (Devolver)"),
    ("devedor_nina", "Devedor (Nina)"),
    ("extras_nino", "Extras (Nino)"),
]


def listar_lancamentos(mes_id, categoria=None):
    with get_conn() as conn:
        if categoria:
            return conn.execute(
                "SELECT * FROM lancamentos WHERE mes_id=? AND categoria=? ORDER BY id",
                (mes_id, categoria)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM lancamentos WHERE mes_id=? ORDER BY categoria, id",
            (mes_id,)
        ).fetchall()


def adicionar_lancamento(mes_id, categoria, descricao, valor):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO lancamentos (mes_id, categoria, descricao, valor) VALUES (?, ?, ?, ?)",
            (mes_id, categoria, descricao, valor)
        )


def atualizar_lancamento(id_, descricao, valor):
    with get_conn() as conn:
        conn.execute("UPDATE lancamentos SET descricao=?, valor=? WHERE id=?",
                     (descricao, valor, id_))


def remover_lancamento(id_):
    with get_conn() as conn:
        conn.execute("DELETE FROM lancamentos WHERE id=?", (id_,))


def totais_mes(mes_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT categoria, COALESCE(SUM(valor),0) as total
            FROM lancamentos WHERE mes_id=?
            GROUP BY categoria
        """, (mes_id,)).fetchall()
        result = {cat: 0.0 for cat, _ in CATEGORIAS_MES}
        for r in rows:
            result[r["categoria"]] = r["total"]
        return result


def total_geral_mes(mes_id):
    totais = totais_mes(mes_id)
    return sum(totais.values())


# ---- VIAGENS ----

def listar_viagens():
    with get_conn() as conn:
        return conn.execute("""
            SELECT v.*, m.ano, m.mes
            FROM viagens v LEFT JOIN meses m ON v.mes_id = m.id
            ORDER BY v.id DESC
        """).fetchall()


def obter_viagem(viagem_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM viagens WHERE id=?", (viagem_id,)).fetchone()


def criar_viagem(nome, data_viagem=None, mes_id=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO viagens (nome, data_viagem, mes_id) VALUES (?, ?, ?)",
            (nome, data_viagem, mes_id)
        )


def atualizar_viagem(id_, nome, data_viagem=None, mes_id=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE viagens SET nome=?, data_viagem=?, mes_id=? WHERE id=?",
            (nome, data_viagem, mes_id, id_)
        )


def remover_viagem(viagem_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM viagens WHERE id=?", (viagem_id,))


# ---- LANÇAMENTOS VIAGEM ----

CATEGORIAS_VIAGEM = [
    ("pedagio", "Pedágio"),
    ("combustivel", "Combustível"),
    ("despesa_viagem", "Despesas da Viagem"),
    ("desp_nina_viagem", "Desp. Nina (Devolver)"),
]


def listar_lancamentos_viagem(viagem_id, categoria=None):
    with get_conn() as conn:
        if categoria:
            return conn.execute(
                "SELECT * FROM lancamentos_viagem WHERE viagem_id=? AND categoria=? ORDER BY id",
                (viagem_id, categoria)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM lancamentos_viagem WHERE viagem_id=? ORDER BY categoria, id",
            (viagem_id,)
        ).fetchall()


def adicionar_lancamento_viagem(viagem_id, categoria, descricao, valor, pago_por_nina=False):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO lancamentos_viagem (viagem_id, categoria, descricao, valor, pago_por_nina) VALUES (?, ?, ?, ?, ?)",
            (viagem_id, categoria, descricao, valor, 1 if pago_por_nina else 0)
        )


def atualizar_lancamento_viagem(id_, descricao, valor, pago_por_nina=False):
    with get_conn() as conn:
        conn.execute(
            "UPDATE lancamentos_viagem SET descricao=?, valor=?, pago_por_nina=? WHERE id=?",
            (descricao, valor, 1 if pago_por_nina else 0, id_)
        )


def remover_lancamento_viagem(id_):
    with get_conn() as conn:
        conn.execute("DELETE FROM lancamentos_viagem WHERE id=?", (id_,))


def totais_viagem(viagem_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT categoria, COALESCE(SUM(valor),0) as total
            FROM lancamentos_viagem WHERE viagem_id=?
            GROUP BY categoria
        """, (viagem_id,)).fetchall()
        result = {cat: 0.0 for cat, _ in CATEGORIAS_VIAGEM}
        for r in rows:
            result[r["categoria"]] = r["total"]
        return result


def total_viagem(viagem_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(valor),0) as total FROM lancamentos_viagem WHERE viagem_id=?",
            (viagem_id,)
        ).fetchone()
        return row["total"]


def total_nina_viagem(viagem_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(valor),0) as total FROM lancamentos_viagem WHERE viagem_id=? AND pago_por_nina=1",
            (viagem_id,)
        ).fetchone()
        return row["total"]


# ---- PARCELAMENTOS ----

def listar_parcelamentos(ativos=True):
    with get_conn() as conn:
        if ativos:
            return conn.execute(
                "SELECT * FROM parcelamentos WHERE ativo=1 ORDER BY descricao"
            ).fetchall()
        return conn.execute("SELECT * FROM parcelamentos ORDER BY descricao").fetchall()


def adicionar_parcelamento(descricao, valor_parcela, num_parcelas, parcela_atual=1, mes_inicio_id=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO parcelamentos (descricao, valor_parcela, num_parcelas, parcela_atual, mes_inicio_id) VALUES (?, ?, ?, ?, ?)",
            (descricao, valor_parcela, num_parcelas, parcela_atual, mes_inicio_id)
        )


def atualizar_parcelamento(id_, descricao, valor_parcela, num_parcelas, parcela_atual):
    with get_conn() as conn:
        conn.execute(
            "UPDATE parcelamentos SET descricao=?, valor_parcela=?, num_parcelas=?, parcela_atual=? WHERE id=?",
            (descricao, valor_parcela, num_parcelas, parcela_atual, id_)
        )


def finalizar_parcelamento(id_):
    with get_conn() as conn:
        conn.execute("UPDATE parcelamentos SET ativo=0 WHERE id=?", (id_,))


def reativar_parcelamento(id_):
    with get_conn() as conn:
        conn.execute("UPDATE parcelamentos SET ativo=1 WHERE id=?", (id_,))


def remover_parcelamento(id_):
    with get_conn() as conn:
        conn.execute("DELETE FROM parcelamentos WHERE id=?", (id_,))


# ---- DÍVIDAS NINO ----

def listar_dividas(apenas_abertas=True):
    with get_conn() as conn:
        if apenas_abertas:
            return conn.execute("SELECT * FROM dividas_nino WHERE quitada=0 ORDER BY descricao").fetchall()
        return conn.execute("SELECT * FROM dividas_nino ORDER BY descricao").fetchall()


def obter_divida(divida_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM dividas_nino WHERE id=?", (divida_id,)).fetchone()


def adicionar_divida(descricao, valor_total):
    with get_conn() as conn:
        conn.execute("INSERT INTO dividas_nino (descricao, valor_total) VALUES (?, ?)",
                     (descricao, valor_total))


def atualizar_divida(id_, descricao, valor_total):
    with get_conn() as conn:
        conn.execute("UPDATE dividas_nino SET descricao=?, valor_total=? WHERE id=?",
                     (descricao, valor_total, id_))


def remover_divida(id_):
    with get_conn() as conn:
        conn.execute("DELETE FROM dividas_nino WHERE id=?", (id_,))


def quitar_divida(id_):
    with get_conn() as conn:
        conn.execute("UPDATE dividas_nino SET quitada=1 WHERE id=?", (id_,))


def saldo_divida(divida_id) -> float:
    """Retorna o saldo restante da dívida (valor_total - soma dos pagamentos)."""
    with get_conn() as conn:
        div = conn.execute("SELECT valor_total FROM dividas_nino WHERE id=?", (divida_id,)).fetchone()
        if not div:
            return 0.0
        pago = conn.execute(
            "SELECT COALESCE(SUM(valor),0) as total FROM pagamentos_divida WHERE divida_id=?",
            (divida_id,)
        ).fetchone()
        return div["valor_total"] - pago["total"]


def listar_pagamentos_divida(divida_id=None, mes_id=None):
    with get_conn() as conn:
        if divida_id and mes_id:
            return conn.execute(
                "SELECT p.*, d.descricao as divida_desc FROM pagamentos_divida p "
                "JOIN dividas_nino d ON p.divida_id=d.id "
                "WHERE p.divida_id=? AND p.mes_id=? ORDER BY p.id",
                (divida_id, mes_id)
            ).fetchall()
        if mes_id:
            return conn.execute(
                "SELECT p.*, d.descricao as divida_desc FROM pagamentos_divida p "
                "JOIN dividas_nino d ON p.divida_id=d.id "
                "WHERE p.mes_id=? ORDER BY p.id",
                (mes_id,)
            ).fetchall()
        if divida_id:
            return conn.execute(
                "SELECT p.*, d.descricao as divida_desc FROM pagamentos_divida p "
                "JOIN dividas_nino d ON p.divida_id=d.id "
                "WHERE p.divida_id=? ORDER BY p.id",
                (divida_id,)
            ).fetchall()
        return conn.execute(
            "SELECT p.*, d.descricao as divida_desc FROM pagamentos_divida p "
            "JOIN dividas_nino d ON p.divida_id=d.id ORDER BY p.id"
        ).fetchall()


def adicionar_pagamento_divida(divida_id, mes_id, valor):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pagamentos_divida (divida_id, mes_id, valor) VALUES (?, ?, ?)",
            (divida_id, mes_id, valor)
        )
        # verifica se quitou
        div = conn.execute("SELECT valor_total FROM dividas_nino WHERE id=?", (divida_id,)).fetchone()
        pago = conn.execute(
            "SELECT COALESCE(SUM(valor),0) as total FROM pagamentos_divida WHERE divida_id=?",
            (divida_id,)
        ).fetchone()
        if pago["total"] >= div["valor_total"]:
            conn.execute("UPDATE dividas_nino SET quitada=1 WHERE id=?", (divida_id,))


def remover_pagamento_divida(id_):
    with get_conn() as conn:
        # pegar divida_id antes de remover
        pag = conn.execute("SELECT divida_id FROM pagamentos_divida WHERE id=?", (id_,)).fetchone()
        conn.execute("DELETE FROM pagamentos_divida WHERE id=?", (id_,))
        if pag:
            # reabrir dívida se ficou com saldo
            div = conn.execute("SELECT valor_total FROM dividas_nino WHERE id=?", (pag["divida_id"],)).fetchone()
            total_pago = conn.execute(
                "SELECT COALESCE(SUM(valor),0) as total FROM pagamentos_divida WHERE divida_id=?",
                (pag["divida_id"],)
            ).fetchone()
            if div and total_pago["total"] < div["valor_total"]:
                conn.execute("UPDATE dividas_nino SET quitada=0 WHERE id=?", (pag["divida_id"],))


def total_pagamentos_mes(mes_id) -> float:
    """Total dos pagamentos de dívidas num mês (para somar ao extras_nino)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(valor),0) as total FROM pagamentos_divida WHERE mes_id=?",
            (mes_id,)
        ).fetchone()
        return row["total"]


# ---- HISTÓRICO ----

def limpar_banco():
    """Apaga todos os dados das tabelas (mantém a estrutura)."""
    with get_conn() as conn:
        conn.executescript("""
            DELETE FROM pagamentos_divida;
            DELETE FROM dividas_nino;
            DELETE FROM lancamentos_viagem;
            DELETE FROM viagens;
            DELETE FROM lancamentos;
            DELETE FROM meses;
            DELETE FROM parcelamentos;
            DELETE FROM despesas_planejamento;
            DELETE FROM fontes_renda;
        """)


def db_hash() -> str:
    """Retorna um hash MD5 de todo o conteúdo do banco (para detectar alterações)."""
    h = hashlib.md5()
    with get_conn() as conn:
        for table in ["fontes_renda", "despesas_planejamento", "meses",
                      "lancamentos", "viagens", "lancamentos_viagem", "parcelamentos",
                      "dividas_nino", "pagamentos_divida"]:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()  # noqa: S608
            for row in rows:
                h.update(str(tuple(row)).encode())
    return h.hexdigest()


def banco_vazio() -> bool:
    """Retorna True se não há nenhum dado em nenhuma tabela."""
    with get_conn() as conn:
        for table in ["fontes_renda", "despesas_planejamento", "meses",
                      "lancamentos", "viagens", "lancamentos_viagem", "parcelamentos",
                      "dividas_nino", "pagamentos_divida"]:
            row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()  # noqa: S608
            if row["c"] > 0:
                return False
    return True


def historico_mensal():
    with get_conn() as conn:
        return conn.execute("""
            SELECT m.id, m.ano, m.mes,
                   COALESCE((SELECT SUM(l.valor) FROM lancamentos l WHERE l.mes_id=m.id),0)
                   + COALESCE((SELECT SUM(p.valor) FROM pagamentos_divida p WHERE p.mes_id=m.id),0)
                   as total
            FROM meses m
            ORDER BY m.ano, m.mes
        """).fetchall()


def historico_por_categoria():
    with get_conn() as conn:
        return conn.execute("""
            SELECT m.ano, m.mes, l.categoria,
                   COALESCE(SUM(l.valor),0) as total
            FROM meses m
            LEFT JOIN lancamentos l ON l.mes_id = m.id
            GROUP BY m.ano, m.mes, l.categoria
            ORDER BY m.ano, m.mes
        """).fetchall()
