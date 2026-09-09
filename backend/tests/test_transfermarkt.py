"""Tests de la integracion con Transfermarkt.

No tocan la red ni la base de datos: se prueba el cruce de identidades y el
parseo con respuestas iguales a las que devuelve el servicio.
"""

from __future__ import annotations

from datetime import date

import pytest

from futbol_analytics.etl.transfermarkt import loader, matching, parser, run, squads

# Respuestas copiadas de una llamada real al servicio.
BUSQUEDA_PEDRI = [
    {
        "id": "683840",
        "name": "Pedri",
        "position": "CM",
        "club": {"id": "131", "name": "FC Barcelona"},
        "marketValue": 150000000,
    },
    {
        "id": "999999",
        "name": "Pedri Sanchez",
        "position": "CB",
        "club": {"id": "500", "name": "Cadiz CF"},
        "marketValue": 300000,
    },
]

VALOR_DE_MERCADO = {
    "marketValue": 150000000,
    "marketValueHistory": [
        {
            "age": 16,
            "date": "2019-10-09",
            "clubId": "472",
            "clubName": "UD Las Palmas",
            "marketValue": 5000000,
        },
        {
            "age": 18,
            "date": "2021-05-20",
            "clubId": "131",
            "clubName": "FC Barcelona",
            "marketValue": 60000000,
        },
    ],
}

FICHAJES = {
    "transfers": [
        {
            "id": "1",
            "clubFrom": {"name": "UD Las Palmas"},
            "clubTo": {"name": "Barcelona"},
            "date": "2020-07-31",
            "upcoming": False,
            "season": "19/20",
            "marketValue": 7200000,
        },
        {
            "id": "2",
            "clubFrom": {"name": "Barcelona"},
            "clubTo": {"name": "Otro"},
            "date": "2027-07-01",
            "upcoming": True,
            "season": "26/27",
            "marketValue": 100000000,
        },
    ]
}


# --- Normalizacion de nombres -----------------------------------------------


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("Iñaki Peña", "inaki pena"),
        ("A. García-López", "a garcia lopez"),
        ("  Pedri  ", "pedri"),
    ],
)
def test_normalise(crudo: str, esperado: str) -> None:
    assert matching.normalise(crudo) == esperado


def test_el_orden_de_nombre_y_apellido_no_penaliza() -> None:
    # Cada fuente los escribe en un orden. Una comparacion literal daria una
    # puntuacion baja a lo que es el mismo jugador.
    assert matching.score("Pedri Gonzalez", "Gonzalez Pedri") > 95


def test_los_acentos_no_penalizan() -> None:
    assert matching.score("Iñaki Peña", "Inaki Pena") == 100


# --- Eleccion de candidato --------------------------------------------------


def test_el_club_manda_sobre_el_parecido_del_nombre() -> None:
    # Es la unica defensa real contra los homonimos: dos jugadores pueden
    # llamarse igual, pero no jugar los dos en el mismo equipo.
    cruce = matching.best_match("1", "Pedri", "Barcelona", BUSQUEDA_PEDRI, threshold=85.0)

    assert cruce.transfermarkt_id == "683840"


def test_un_nombre_exacto_no_necesita_que_coincida_el_club() -> None:
    # La busqueda devuelve el club ACTUAL y nosotros cargamos temporadas
    # pasadas: un cedido figura en otro equipo. Penalizar eso marcaba como
    # dudosos cruces evidentes como Lewandowski o Rashford.
    cruce = matching.best_match("1", "Pedri", "Getafe", BUSQUEDA_PEDRI, threshold=50.0)

    assert cruce.transfermarkt_id == "683840"
    assert cruce.usable is True


def test_con_homonimos_y_sin_club_se_pide_revision() -> None:
    # Aqui el club si importa: dos candidatos puntuan practicamente igual, asi
    # que sin saber en que equipo juega no hay forma de elegir con seguridad.
    gemelos = [
        {"id": "1", "name": "Sergio Ramos", "club": {"name": "Monterrey"}},
        {"id": "2", "name": "Sergio Ramos", "club": {"name": "Sevilla"}},
    ]

    cruce = matching.best_match("1", "Sergio Ramos", "Real Madrid", gemelos, threshold=50.0)

    assert cruce.usable is False


def test_un_parecido_bajo_no_produce_cruce() -> None:
    cruce = matching.best_match(
        "1", "Vinicius Junior", "Real Madrid", BUSQUEDA_PEDRI, threshold=85.0
    )

    assert cruce.transfermarkt_id is None
    assert cruce.usable is False


def test_sin_candidatos_no_se_inventa_nada() -> None:
    cruce = matching.best_match("1", "Nadie", "Equipo", [], threshold=85.0)

    assert cruce.transfermarkt_id is None


def test_un_cruce_fiable_se_usa_sin_revision() -> None:
    cruce = matching.best_match("1", "Pedri", "Barcelona", BUSQUEDA_PEDRI, threshold=85.0)

    assert cruce.is_confident
    assert cruce.usable is True


def test_un_cruce_dudoso_espera_revision() -> None:
    # 91,9 de parecido: por encima del umbral pero por debajo de la confianza.
    candidatos = [{"id": "7", "name": "Alexander Sorloth Jr", "club": {"name": "Atletico Madrid"}}]

    cruce = matching.best_match(
        "1", "Alexander Sorloth", "Atletico Madrid", candidatos, threshold=85.0
    )

    assert cruce.transfermarkt_id == "7"
    assert cruce.match_method == "fuzzy"
    # Se guarda, pero no se carga nada suyo: un valor de mercado de otra persona
    # es peor que ninguno.
    assert cruce.usable is False


def test_un_apodo_no_cruza_y_eso_es_lo_correcto() -> None:
    # Caso real de nuestros datos: Understat escribe "Abderrahmane Rebbach" y
    # otras fuentes "Abde Rebbach". Solo se parecen un 75 %, asi que el cruce no
    # se produce. Bajar el umbral para capturarlo empezaria a confundir
    # jugadores distintos, que es un error mucho peor que no tener el dato.
    candidatos = [{"id": "9", "name": "Abderrahmane Rebbach", "club": {"name": "Alaves"}}]

    cruce = matching.best_match("1", "Abde Rebbach", "Alaves", candidatos, threshold=85.0)

    assert cruce.transfermarkt_id is None


# --- Importes y fechas ------------------------------------------------------


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        (150000000, 150000000.0),
        ("€12.00m", 12000000.0),
        ("€900k", 900000.0),
        ("Free transfer", None),
        ("loan transfer", None),
        ("?", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_amount(crudo: object, esperado: float | None) -> None:
    assert parser.parse_amount(crudo) == esperado


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [("2020-07-31", date(2020, 7, 31)), ("Jul 31, 2020", date(2020, 7, 31)), ("", None)],
)
def test_parse_date(crudo: str, esperado: date | None) -> None:
    assert parser.parse_date(crudo) == esperado


def test_una_cesion_no_se_cuenta_como_traspaso() -> None:
    assert parser.classify_transfer({"fee": "Loan transfer"}) == "cesion"
    assert parser.classify_transfer({"fee": "Free transfer"}) == "libre"
    assert parser.classify_transfer({"fee": "€12.00m"}) == "traspaso"


def test_sin_importe_no_se_supone_el_tipo() -> None:
    # Transfermarkt no siempre publica el importe. Contar una cesion como
    # traspaso falsearia cualquier analisis de gasto.
    assert parser.classify_transfer({}) is None


# --- Conversion a filas -----------------------------------------------------


def test_el_historico_de_valor_se_convierte_en_filas() -> None:
    filas = parser.parse_market_value_history(VALOR_DE_MERCADO, "abc")

    assert len(filas) == 2
    assert filas[0]["understat_id"] == "abc"
    assert filas[0]["valuation_date"] == date(2019, 10, 9)
    assert filas[0]["market_value_eur"] == 5000000.0
    assert filas[0]["club_at_time"] == "UD Las Palmas"


def test_los_fichajes_anunciados_y_no_efectivos_se_descartan() -> None:
    # Un fichaje que aun no ha ocurrido no pertenece al historial, y ademas
    # puede caerse.
    filas = parser.parse_transfers(FICHAJES, "abc")

    assert len(filas) == 1
    assert filas[0]["club_from"] == "UD Las Palmas"
    assert filas[0]["transfer_date"] == date(2020, 7, 31)


def test_un_fichaje_sin_clave_completa_se_descarta() -> None:
    # Sin fecha o sin clubes la fila no se puede insertar ni identificar luego.
    incompleto = {"transfers": [{"clubFrom": {"name": "A"}, "date": None}]}

    assert parser.parse_transfers(incompleto, "abc") == []


def test_un_historico_vacio_no_revienta() -> None:
    assert parser.parse_market_value_history({}, "abc") == []
    assert parser.parse_transfers({}, "abc") == []


# --- Desempate por la carrera del jugador -----------------------------------

LEWANDOWSKIS = [
    {"id": "38253", "name": "Robert Lewandowski", "club": {"name": "Chicago Fire FC"}},
    {"id": "259054", "name": "Robert Lewandowski", "club": {"name": "Retired"}},
]


def _carreras(historiales: dict[str, list[str]]):
    return lambda tm_id: historiales.get(tm_id, [])


def test_dos_homonimos_se_separan_por_donde_han_jugado() -> None:
    # Caso real: en septiembre de 2026 la busqueda situa a Lewandowski en el
    # Chicago Fire, asi que al cargar su temporada en el Barcelona no coincide
    # el club, y ademas hay otro Robert Lewandowski retirado. Solo uno de los
    # dos ha pasado por el Barcelona.
    cruce = matching.best_match("1", "Robert Lewandowski", "Barcelona", LEWANDOWSKIS, 85.0)
    assert cruce.usable is False

    confirmado = matching.confirm_by_history(
        cruce,
        "Barcelona",
        LEWANDOWSKIS,
        _carreras({"38253": ["Bayern Munich", "FC Barcelona"], "259054": ["Znicz Pruszkow"]}),
    )

    assert confirmado.transfermarkt_id == "38253"
    assert confirmado.match_method == "history"
    assert confirmado.usable is True


def test_si_ninguno_ha_jugado_ahi_el_cruce_sigue_en_revision() -> None:
    # Los homonimos de un canterano suelen ser todos jugadores distintos. Sin
    # confirmacion no se resuelve: el dato de otra persona es peor que ninguno.
    cruce = matching.best_match("1", "Robert Lewandowski", "Barcelona", LEWANDOWSKIS, 85.0)

    confirmado = matching.confirm_by_history(
        cruce, "Barcelona", LEWANDOWSKIS, _carreras({"38253": ["Bayern Munich"]})
    )

    assert confirmado.usable is False


def test_si_varios_han_jugado_ahi_tampoco_se_resuelve() -> None:
    # Un padre y un hijo en el mismo club, o un canterano y un veterano. El
    # historico no basta y decide una persona.
    cruce = matching.best_match("1", "Robert Lewandowski", "Barcelona", LEWANDOWSKIS, 85.0)

    confirmado = matching.confirm_by_history(
        cruce,
        "Barcelona",
        LEWANDOWSKIS,
        _carreras({"38253": ["FC Barcelona"], "259054": ["FC Barcelona"]}),
    )

    assert confirmado.usable is False


def test_los_clubes_de_la_carrera_salen_del_historico() -> None:
    assert parser.clubs_in_history(VALOR_DE_MERCADO) == ["UD Las Palmas", "FC Barcelona"]
    assert parser.clubs_in_history({}) == []


# --- Valor de plantilla -----------------------------------------------------


def test_la_cobertura_minima_es_una_mayoria_de_la_plantilla() -> None:
    # Un equipo del que solo conocemos a un jugador no vale lo que ese jugador.
    # Al cargar solo el Barcelona aparecia el PSG valorado en 10 M porque uno de
    # sus futbolistas habia jugado antes alli.
    assert 0.5 < loader.MIN_COVERAGE < 1.0


# --- Cruce por plantilla ----------------------------------------------------

PLANTILLA_BARCELONA = [
    {
        "id": "561613",
        "name": "Joan García",
        "position": "Goalkeeper",
        "dateOfBirth": "2001-04-05",
        "age": 25,
        "nationality": ["Spain"],
        "height": 193,
        "foot": "right",
        "joinedOn": "2025-01-07",
        "signedFrom": "RCD Espanyol Barcelona",
        "contract": "2031-06-30",
        "marketValue": 45000000,
    },
    {"id": "683840", "name": "Pedri", "position": "Central Midfield", "age": 23},
    {"id": "480267", "name": "Ronald Araújo", "position": "Centre-Back", "age": 27},
]

CLUBES_LALIGA = [
    {"id": "418", "name": "Real Madrid"},
    {"id": "131", "name": "FC Barcelona"},
    {"id": "13", "name": "Atlético de Madrid"},
]


def test_el_nombre_del_club_se_cruza_con_tolerancia() -> None:
    # Understat escribe "Barcelona" y Transfermarkt "FC Barcelona".
    club = squads.match_club("Barcelona", CLUBES_LALIGA)

    assert club is not None
    assert club["id"] == "131"


def test_dos_clubes_de_la_misma_ciudad_no_se_confunden() -> None:
    club = squads.match_club("Atletico Madrid", CLUBES_LALIGA)

    assert club is not None
    assert club["id"] == "13"


def test_un_equipo_que_no_esta_en_la_liga_no_se_fuerza() -> None:
    # Inventar un club daria toda una plantilla equivocada, no un jugador.
    assert squads.match_club("Deportivo La Coruna", CLUBES_LALIGA) is None


def test_estar_en_la_plantilla_basta_para_dar_el_cruce_por_fiable() -> None:
    # La coincidencia de club es una prueba de identidad mucho mas fuerte que el
    # parecido del nombre: en una plantilla de veintitantos no hay a quien
    # confundir.
    cruce = squads.match_in_squad("1", "Ronald Araujo", PLANTILLA_BARCELONA, threshold=85.0)

    assert cruce.transfermarkt_id == "480267"
    assert cruce.match_method == "squad"
    assert cruce.usable is True


def test_dos_companeros_con_el_mismo_nombre_esperan_revision() -> None:
    # Aqui el club no desempata: los dos juegan en el mismo equipo.
    gemelos = [
        {"id": "1", "name": "Rodrigo Fernández"},
        {"id": "2", "name": "Rodrigo Fernandez"},
    ]

    cruce = squads.match_in_squad("1", "Rodrigo Fernandez", gemelos, threshold=85.0)

    assert cruce.usable is False


def test_quien_no_esta_en_la_plantilla_no_se_cruza() -> None:
    # Un jugador que ya se ha ido del club. Devolver a un companero cualquiera
    # seria mucho peor que no devolver nada.
    cruce = squads.match_in_squad("1", "Kylian Mbappe", PLANTILLA_BARCELONA, threshold=85.0)

    assert cruce.transfermarkt_id is None


def test_la_ficha_de_la_plantilla_se_convierte_en_fila() -> None:
    # Es contexto, no rendimiento: un percentil 95 no significa lo mismo a los
    # 19 anos que a los 33.
    fila = parser.parse_squad_player(PLANTILLA_BARCELONA[0], "abc")

    assert fila["understat_id"] == "abc"
    assert fila["date_of_birth"] == date(2001, 4, 5)
    assert fila["age"] == 25
    assert fila["position"] == "Goalkeeper"
    assert fila["nationality"] == "Spain"
    assert fila["foot"] == "right"
    assert fila["contract_until"] == date(2031, 6, 30)
    assert fila["signed_from"] == "RCD Espanyol Barcelona"


def test_una_ficha_incompleta_no_revienta() -> None:
    fila = parser.parse_squad_player({"id": "9", "name": "X"}, "abc")

    assert fila["date_of_birth"] is None
    assert fila["nationality"] is None


# --- Nombres de club --------------------------------------------------------

CLUBES_REALES = [
    {"id": "131", "name": "FC Barcelona"},
    {"id": "714", "name": "RCD Espanyol Barcelona"},
    {"id": "1108", "name": "Deportivo Alavés"},
    {"id": "150", "name": "Real Betis Balompié"},
    {"id": "418", "name": "Real Madrid"},
    {"id": "13", "name": "Atlético de Madrid"},
]


@pytest.mark.parametrize(
    ("nuestro", "esperado"),
    [
        # Transfermarkt antepone y anade palabras que Understat no escribe.
        ("Alaves", "1108"),
        ("Espanyol", "714"),
        ("Real Betis", "150"),
        # Y dos equipos de la misma ciudad no pueden confundirse.
        ("Real Madrid", "418"),
        ("Atletico Madrid", "13"),
    ],
)
def test_los_nombres_de_club_se_cruzan_pese_a_las_palabras_de_mas(
    nuestro: str, esperado: str
) -> None:
    club = squads.match_club(nuestro, CLUBES_REALES)

    assert club is not None
    assert club["id"] == esperado


def test_barcelona_no_se_lleva_la_plantilla_del_espanyol() -> None:
    # El error mas caro posible de esta integracion. "Barcelona" esta contenido
    # tanto en "FC Barcelona" como en "RCD Espanyol Barcelona", asi que
    # ignorando las palabras de mas los dos puntuan 100. Un cruce de jugador mal
    # hecho estropea a un jugador; uno de club, a un equipo entero.
    club = squads.match_club("Barcelona", CLUBES_REALES)

    assert club is not None
    assert club["id"] == "131"


def test_un_empate_de_club_no_se_resuelve_a_ciegas() -> None:
    gemelos = [{"id": "1", "name": "Racing"}, {"id": "2", "name": "Racing"}]

    assert squads.match_club("Racing", gemelos) is None


# --- Que se gasta una peticion y que no -------------------------------------


class ClienteEspia:
    """Cuenta las busquedas, que son la parte cara de la carga."""

    def __init__(self) -> None:
        self.busquedas: list[str] = []

    def search_player(self, name: str) -> list[dict]:
        self.busquedas.append(name)
        return []


class _Ajustes:
    fuzzy_match_threshold = 85.0


def test_un_cruce_ya_guardado_no_se_vuelve_a_buscar() -> None:
    # Repetir una busqueda resuelta gasta una peticion en una fuente ajena para
    # llegar al mismo sitio.
    espia = ClienteEspia()
    conocido = {
        "player_name": "Pedri",
        "transfermarkt_id": "683840",
        "match_method": "squad",
        "match_confidence": 95.0,
        "reviewed": False,
    }

    cruce = run._cruce_de(conocido, "1", "Pedri", "Barcelona", [], espia, _Ajustes())

    assert cruce.transfermarkt_id == "683840"
    assert espia.busquedas == []


def test_si_esta_en_la_plantilla_tampoco_se_busca() -> None:
    # La plantilla ya esta descargada: cruzar dentro de ella sale gratis.
    espia = ClienteEspia()

    cruce = run._cruce_de(None, "1", "Pedri", "Barcelona", PLANTILLA_BARCELONA, espia, _Ajustes())

    assert cruce.transfermarkt_id == "683840"
    assert espia.busquedas == []


def test_quien_no_esta_en_su_plantilla_se_busca_por_nombre() -> None:
    # Un jugador que ya se ha ido del club, o un canterano que Transfermarkt
    # tiene en el filial.
    espia = ClienteEspia()

    run._cruce_de(None, "1", "Kylian Mbappe", "Barcelona", PLANTILLA_BARCELONA, espia, _Ajustes())

    assert espia.busquedas == ["Kylian Mbappe"]


def test_sin_cliente_no_se_gasta_ninguna_peticion() -> None:
    # Es como se separa lo barato de lo caro: a un jugador cuyo historico sigue
    # fresco se le saca la ficha de la plantilla, pero no se le busca.
    cruce = run._cruce_de(
        None, "1", "Kylian Mbappe", "Barcelona", PLANTILLA_BARCELONA, None, _Ajustes()
    )

    assert cruce is None
