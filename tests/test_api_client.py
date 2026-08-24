"""Testes do cliente da API de Carga Verificada.

Nenhum teste toca a rede. Os corpos de resposta sao recortes reais da API, e os defeitos
testados aqui foram todos observados nela antes de virar teste: o JSON malformado, o
corte silencioso de janela, o zero no lugar da medicao que ainda nao aconteceu e o
vocabulario de area diferente do vocabulario do arquivo.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest
import requests

from energy_load_etl import api_client, config, validate
from tests.conftest import (
    CORPO_MALFORMADO,
    VOLTA_DST_2018_API,
    corpo,
    meias_horas_api,
    registro_api,
)


class RespostaFalsa:
    """O minimo de requests.Response que o cliente usa."""

    def __init__(self, texto: str = "[]", status: int = 200):
        self.text = texto
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def responder(monkeypatch, *respostas):
    """Troca o requests.get por uma fila de respostas. Devolve a lista de chamadas."""
    fila = list(respostas)
    chamadas = []

    def falso_get(url, params=None, timeout=None):
        chamadas.append(params)
        item = fila.pop(0) if len(fila) > 1 else fila[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(api_client.requests, "get", falso_get)
    monkeypatch.setattr(api_client.time, "sleep", lambda _: None)
    return chamadas


# --- reparo do JSON -----------------------------------------------------------


def test_json_da_api_e_invalido_antes_do_reparo():
    """O ponto de partida: resposta.json() nao serviria, e e' por isso que ele nao e' usado."""
    with pytest.raises(json.JSONDecodeError):
        json.loads(CORPO_MALFORMADO)


def test_reparo_torna_o_corpo_parseavel():
    texto, reparos = api_client._reparar_json(CORPO_MALFORMADO)
    assert reparos == 2
    registro = json.loads(texto)[0]
    # Nulo e nao zero: o campo nao foi medido, e zero seria afirmar que a geracao
    # distribuida daquela meia-hora foi nenhuma.
    assert registro["val_cargaglobalsmmgd"] is None
    assert registro["val_cargammgd"] is None
    assert registro["val_cargaglobal"] == 30392.07


def test_reparo_nao_toca_em_string_com_dois_pontos_e_virgula():
    """O motivo de o regex exigir aspas antes: corromper dado bom seria pior que o defeito."""
    bom = '[{"obs": "cuidado: , aqui", "val": 1}]'
    texto, reparos = api_client._reparar_json(bom)
    assert reparos == 0
    assert json.loads(texto)[0]["obs"] == "cuidado: , aqui"


# --- vocabulario de area ------------------------------------------------------


def test_se_e_traduzido_para_seco_na_chamada(monkeypatch):
    chamadas = responder(monkeypatch, RespostaFalsa(corpo(meias_horas_api("2026-06-01"))))
    api_client.buscar_area("SE", date(2026, 6, 1), date(2026, 6, 1))
    assert chamadas[0]["cod_areacarga"] == "SECO"


def test_seco_volta_a_ser_se_na_normalizacao(monkeypatch):
    responder(monkeypatch, RespostaFalsa(corpo(meias_horas_api("2026-06-01"))))
    df, _ = api_client.buscar_janela(date(2026, 6, 1), date(2026, 6, 1), ["SE"])
    assert set(df["id_subsistema"]) == {"SE"}


def test_subsistema_fora_do_sin_e_recusado_sem_chamar_a_api(monkeypatch):
    chamadas = responder(monkeypatch, RespostaFalsa())
    registros, resultado = api_client.buscar_area("XX", date(2026, 6, 1), date(2026, 6, 1))
    assert registros == [] and resultado.status == "recusado"
    assert chamadas == []


# --- as recusas locais --------------------------------------------------------
#
# Existem porque a API responde HTTP 200 com lista vazia para qualquer erro de pedido.
# Sem elas, um erro nosso viraria ausencia de dado sem nada apontando a causa.


@pytest.mark.parametrize(
    "inicio,fim,esperado",
    [
        (date(2026, 6, 10), date(2026, 6, 1), "invertido"),
        (date(2014, 1, 1), date(2014, 1, 2), "antes de"),
        (date(2026, 1, 1), date(2026, 6, 1), "fatie"),
    ],
)
def test_pedido_impossivel_nao_sai_da_maquina(monkeypatch, inicio, fim, esperado):
    chamadas = responder(monkeypatch, RespostaFalsa())
    _, resultado = api_client.buscar_area("SE", inicio, fim)
    assert resultado.status == "recusado"
    assert esperado in resultado.detalhe
    assert chamadas == []


def test_resposta_vazia_e_anomalia_e_nao_sucesso(monkeypatch):
    responder(monkeypatch, RespostaFalsa("[]"))
    _, resultado = api_client.buscar_area("SE", date(2026, 6, 1), date(2026, 6, 1))
    assert resultado.status == "vazio"


# --- backoff ------------------------------------------------------------------


def test_repete_e_vence_depois_de_duas_falhas(monkeypatch):
    boa = RespostaFalsa(corpo(meias_horas_api("2026-06-01")))
    chamadas = responder(
        monkeypatch, requests.ConnectionError("caiu"), requests.Timeout("demorou"), boa
    )
    registros, resultado = api_client.buscar_area("SE", date(2026, 6, 1), date(2026, 6, 1))
    assert resultado.status == "ok" and len(registros) == 48
    assert len(chamadas) == 3


def test_desiste_depois_do_limite_sem_levantar_excecao(monkeypatch):
    chamadas = responder(monkeypatch, requests.ConnectionError("caiu"))
    registros, resultado = api_client.buscar_area("SE", date(2026, 6, 1), date(2026, 6, 1))
    assert registros == [] and resultado.status == "erro"
    assert len(chamadas) == config.API_TENTATIVAS


def test_nao_repete_erro_de_pedido(monkeypatch):
    """4xx e' problema nosso. Insistir no mesmo pedido errado nao conserta e so' incomoda."""
    chamadas = responder(monkeypatch, RespostaFalsa("[]", status=404))
    _, resultado = api_client.buscar_area("SE", date(2026, 6, 1), date(2026, 6, 1))
    assert resultado.status == "erro"
    assert len(chamadas) == 1


def test_repete_erro_do_servidor(monkeypatch):
    chamadas = responder(monkeypatch, RespostaFalsa("", status=503))
    _, resultado = api_client.buscar_area("SE", date(2026, 6, 1), date(2026, 6, 1))
    assert resultado.status == "erro"
    assert len(chamadas) == config.API_TENTATIVAS


# --- fatiamento e cobertura ---------------------------------------------------


def test_fatiar_nunca_passa_do_teto_por_chamada():
    pedacos = api_client._fatiar(date(2026, 1, 1), date(2026, 4, 15))
    assert all((f - i).days + 1 <= config.API_MAX_DIAS_POR_CHAMADA for i, f in pedacos)
    # Sem buraco e sem sobreposicao entre os pedacos.
    assert pedacos[0][0] == date(2026, 1, 1) and pedacos[-1][1] == date(2026, 4, 15)
    assert all(b[0] == a[1] + pd.Timedelta(days=1) for a, b in zip(pedacos, pedacos[1:]))


def test_cobertura_acusa_o_corte_silencioso():
    """O unico defeito da API que nao da' sinal nenhum: HTTP 200 com o fim da janela cortado."""
    veio = meias_horas_api("2026-06-01") + meias_horas_api("2026-06-02")
    faltantes = api_client._conferir_cobertura(veio, date(2026, 6, 1), date(2026, 6, 4))
    assert faltantes == ["2026-06-03", "2026-06-04"]


def test_cobertura_completa_nao_acusa_nada():
    veio = meias_horas_api("2026-06-01")
    assert api_client._conferir_cobertura(veio, date(2026, 6, 1), date(2026, 6, 1)) == []


def test_janela_cortada_nao_passa_por_ok(monkeypatch):
    responder(monkeypatch, RespostaFalsa(corpo(meias_horas_api("2026-06-01"))))
    _, resultados = api_client.buscar_janela(date(2026, 6, 1), date(2026, 6, 3), ["SE"])
    assert resultados[0].status == "incompleto"
    assert "2 dias sem retorno" in resultados[0].detalhe


# --- normalizacao e horario de verao ------------------------------------------


def test_utc_vira_hora_local(monkeypatch):
    responder(monkeypatch, RespostaFalsa(corpo(meias_horas_api("2026-06-01"))))
    df, _ = api_client.buscar_janela(date(2026, 6, 1), date(2026, 6, 1), ["SE"])
    primeiro = df["din_instante_local"].iloc[0]
    assert (primeiro.hour, primeiro.minute) == (0, 30)
    assert primeiro.utcoffset().total_seconds() / 3600 == -3


def test_as_duas_ocorrencias_das_23h_sobrevivem(monkeypatch):
    """A API guarda a medicao que o formato do arquivo anual descartou na origem."""
    registros = [
        registro_api(r["din_referenciautc"], r["val_cargaglobalcons"], dia="2018-02-17")
        for r in VOLTA_DST_2018_API
    ]
    responder(monkeypatch, RespostaFalsa(corpo(registros)))
    df, _ = api_client.buscar_janela(date(2018, 2, 17), date(2018, 2, 17), ["SE"])

    as_23 = df[df["din_instante_local"].dt.hour == 23]
    assert len(as_23) == 4  # 23:00 e 23:30, duas vezes cada
    assert set(as_23["din_instante_local"].dt.tz_localize(None).astype(str)) == {
        "2018-02-17 23:00:00",
        "2018-02-17 23:30:00",
    }
    # Mesmo rotulo de parede, instantes diferentes, cargas diferentes.
    assert as_23["din_instante"].nunique() == 4
    assert as_23["hora_ambigua"].all()


def test_v3_nao_rejeita_a_hora_repetida(monkeypatch):
    """Se din_instante_local fosse naive, a V3 mataria a medicao recem-recuperada."""
    registros = [
        registro_api(r["din_referenciautc"], r["val_cargaglobalcons"], dia="2018-02-17")
        for r in VOLTA_DST_2018_API
    ]
    responder(monkeypatch, RespostaFalsa(corpo(registros)))
    df, _ = api_client.buscar_janela(date(2018, 2, 17), date(2018, 2, 17), ["SE"])
    ok, rejeitados = validate.v3_unicidade(df)
    assert len(rejeitados) == 0 and len(ok) == len(df)


def test_instante_inexistente_nunca_dispara_nesta_fonte(monkeypatch):
    """Chaveada em UTC, a API nao tem como carimbar uma hora que o relogio pulou."""
    responder(monkeypatch, RespostaFalsa(corpo(meias_horas_api("2018-11-04"))))
    df, _ = api_client.buscar_janela(date(2018, 11, 4), date(2018, 11, 4), ["SE"])
    _, rejeitados = validate.instante_inexistente(df)
    assert len(rejeitados) == 0


def test_meia_hora_futura_vem_com_zero_e_a_v5_barra(monkeypatch):
    """A API pre-cria as 48 fatias do dia e enche com zero as que ainda nao aconteceram.

    Sem a faixa fisica, a media do dia corrente sairia baixa todo dia, sem sintoma.
    """
    registros = meias_horas_api("2026-06-01")
    for r in registros[-4:]:
        r["val_cargaglobal"] = r["val_cargaglobalcons"] = 0.0
    responder(monkeypatch, RespostaFalsa(corpo(registros)))

    df, _ = api_client.buscar_janela(date(2026, 6, 1), date(2026, 6, 1), ["SE"])
    ok, rejeitados = validate.v5_faixa_fisica(df)
    assert len(rejeitados) == 4
    assert set(rejeitados["motivo"]) == {"fora_de_faixa"}
    assert len(ok) == 44


# --- semi-horario para horario ------------------------------------------------


def test_duas_meias_horas_viram_uma_hora(monkeypatch):
    """A convencao de fim de intervalo: 00:30 e 01:00 cobrem a hora que comeca em 00:00."""
    responder(monkeypatch, RespostaFalsa(corpo(meias_horas_api("2026-06-01", valor=1000.0))))
    df, _ = api_client.buscar_janela(date(2026, 6, 1), date(2026, 6, 1), ["SE"])
    horario = api_client.para_horario(df)

    primeira = horario.iloc[0]
    assert (primeira["din_instante_local"].hour, primeira["din_instante_local"].minute) == (0, 0)
    # meias_horas_api gera 1000, 1010, 1020...: as duas primeiras fazem 1005.
    assert primeira["val_cargaenergiahomwmed"] == pytest.approx(1005.0)
    assert primeira["meias_horas"] == 2 and primeira["completo"]


def test_hora_sem_o_par_sai_declarada_incompleta(monkeypatch):
    registros = meias_horas_api("2026-06-01")[:3]  # 00:30, 01:00, 01:30
    responder(monkeypatch, RespostaFalsa(corpo(registros)))
    df, _ = api_client.buscar_janela(date(2026, 6, 1), date(2026, 6, 1), ["SE"])
    horario = api_client.para_horario(df)

    assert list(horario["meias_horas"]) == [2, 1]
    assert list(horario["completo"]) == [True, False]


def test_agregacao_nao_estoura_na_volta_do_horario_de_verao(monkeypatch):
    """floor("h") no horario local levantaria AmbiguousTimeError. Por isso arredonda em UTC."""
    registros = [
        registro_api(r["din_referenciautc"], r["val_cargaglobalcons"], dia="2018-02-17")
        for r in VOLTA_DST_2018_API
    ]
    responder(monkeypatch, RespostaFalsa(corpo(registros)))
    df, _ = api_client.buscar_janela(date(2018, 2, 17), date(2018, 2, 17), ["SE"])

    with pytest.raises(ValueError, match="Cannot infer dst time"):
        df["din_instante_local"].dt.floor("h")

    horario = api_client.para_horario(df)
    as_23 = horario[horario["din_instante_local"].dt.hour == 23]
    assert len(as_23) == 2
    horas_de_offset = sorted(
        t.utcoffset().total_seconds() / 3600 for t in as_23["din_instante_local"]
    )
    assert horas_de_offset == [-3.0, -2.0]  # a do horario de verao e a do padrao
    # Cada hora sai das duas meias-horas que TERMINAM dentro dela, e nao das que levam o
    # rotulo dela. Parear pelo rotulo e' o erro natural, e da' outro numero:
    #   23:00 -0200 <- 01:30 e 02:00 UTC -> media(39329.48, 38590.98) = 38960.230
    #   23:00 -0300 <- 02:30 e 03:00 UTC -> media(38078.402, 37516.54) = 37797.471
    assert sorted(as_23["val_cargaenergiahomwmed"].round(3)) == [37797.471, 38960.230]


def test_tabela_vazia_mantem_os_tipos():
    """Precisa valer no dia em que a API estiver fora, que e' o pior dia para descobrir."""
    vazio = api_client.vazio_verificada()
    assert list(vazio["din_instante_local"].dt.year) == []
    assert api_client.para_horario(vazio).empty
