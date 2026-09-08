"""Carga en PostgreSQL.

El ETL tiene que poder relanzarse sin miedo: una temporada en curso se
re-scrapea cada semana y los datos de FBref se corrigen a posteriori (un gol
cambia de autor, un xG se recalcula). Por eso la carga es un UPSERT sobre la
clave natural y no un INSERT: relanzar actualiza, nunca duplica ni obliga a
borrar la tabla antes.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, Table, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from futbol_analytics.db.schema import etl_run

logger = logging.getLogger(__name__)

# Tamano de lote. Suficientemente grande para que la carga sea rapida y
# suficientemente pequeno para no construir sentencias gigantes: las Big 5 son
# del orden de 3.000 jugadores por temporada.
CHUNK_SIZE = 500

# Una ejecucion marcada como "running" mas antigua que esto se da por muerta.
# Sin este limite, un contenedor que se cae a mitad dejaria una fila colgada y
# el ETL no volveria a ejecutarse nunca: el candado se convertiria en un cierre
# permanente, que es peor que no tener candado.
STALE_RUN_HOURS = 3


class EtlAlreadyRunningError(RuntimeError):
    """Ya hay una carga en marcha.

    No es un fallo: para un proceso programado es motivo de saltarse el turno.
    Importa porque FBref limita a una peticion cada 7 segundos y dos ETL
    simultaneos duplican la presion sobre el sin cargar nada nuevo.
    """


def build_upsert(table: Table, rows: Sequence[dict]) -> Insert:
    """Construye el INSERT ... ON CONFLICT DO UPDATE para un lote de filas.

    Separado de `upsert` para poder verificar la sentencia en un test sin
    levantar PostgreSQL.
    """
    key_columns = {column.name for column in table.primary_key.columns}
    # Solo se actualizan las columnas presentes en los datos. Asi una carga
    # parcial no borra columnas que rellena otro proceso: en concreto
    # `detailed_position`, que asignara el clustering de roles de la fase 3.
    present = {name for row in rows for name in row}
    updatable = [
        column.name
        for column in table.columns
        if column.name not in key_columns and column.name in present and column.name != "updated_at"
    ]

    statement = pg_insert(table).values(list(rows))
    return statement.on_conflict_do_update(
        index_elements=sorted(key_columns),
        set_={
            **{name: statement.excluded[name] for name in updatable},
            # Marca cuando se refresco la fila, aunque el resto no cambie.
            "updated_at": func.now(),
        },
    )


def upsert(engine: Engine, table: Table, rows: Sequence[dict], chunk_size: int = CHUNK_SIZE) -> int:
    """Inserta o actualiza filas segun la clave primaria de la tabla.

    Devuelve el numero de filas enviadas.
    """
    if not rows:
        logger.warning("Nada que cargar", extra={"tabla": table.name})
        return 0

    total = 0
    with engine.begin() as connection:
        for start in range(0, len(rows), chunk_size):
            chunk = list(rows[start : start + chunk_size])
            connection.execute(build_upsert(table, chunk))
            total += len(chunk)

    logger.info("Carga completada", extra={"tabla": table.name, "filas": total})
    return total


def start_run(engine: Engine, leagues: Sequence[str], seasons: Sequence[str]) -> int:
    """Registra el inicio de una ejecucion y devuelve su identificador.

    Actua tambien como candado: si ya hay una carga viva, lanza
    `EtlAlreadyRunningError` en lugar de arrancar una segunda.

    Todo ocurre en una transaccion con la tabla bloqueada. Sin el bloqueo, dos
    contenedores que arrancasen a la vez podrian comprobar los dos que no hay
    nadie corriendo y entrar los dos.
    """
    limite = datetime.now(UTC) - timedelta(hours=STALE_RUN_HOURS)

    with engine.begin() as connection:
        # Modo de bloqueo que impide otro START simultaneo pero deja leer la
        # tabla: la API consulta la ultima ejecucion y no debe quedarse esperando.
        connection.execute(text("LOCK TABLE etl_run IN SHARE ROW EXCLUSIVE MODE"))

        viva = connection.execute(
            select(etl_run.c.id, etl_run.c.started_at)
            .where(etl_run.c.status == "running", etl_run.c.started_at > limite)
            .order_by(etl_run.c.started_at.desc())
            .limit(1)
        ).first()
        if viva is not None:
            raise EtlAlreadyRunningError(
                f"Ya hay una carga en marcha (id {viva.id}, iniciada a las {viva.started_at})."
            )

        # Ejecuciones zombis: se marcan para que no bloqueen y para que quede
        # constancia de que se quedaron a medias.
        zombis = connection.execute(
            update(etl_run)
            .where(etl_run.c.status == "running", etl_run.c.started_at <= limite)
            .values(status="stale", error=f"Sin terminar tras {STALE_RUN_HOURS} horas.")
        ).rowcount
        if zombis:
            logger.warning("Ejecuciones abandonadas descartadas", extra={"ejecuciones": zombis})

        result = connection.execute(
            insert(etl_run)
            .values(
                status="running",
                leagues=",".join(leagues),
                seasons=",".join(seasons),
            )
            .returning(etl_run.c.id)
        )
        return int(result.scalar_one())


def finish_run(
    engine: Engine,
    run_id: int,
    *,
    status: str,
    player_rows: int | None = None,
    team_rows: int | None = None,
    error: str | None = None,
) -> None:
    """Cierra el registro de una ejecucion del ETL."""
    with engine.begin() as connection:
        connection.execute(
            update(etl_run)
            .where(etl_run.c.id == run_id)
            .values(
                status=status,
                finished_at=datetime.now(UTC),
                player_rows=player_rows,
                team_rows=team_rows,
                error=error,
            )
        )
