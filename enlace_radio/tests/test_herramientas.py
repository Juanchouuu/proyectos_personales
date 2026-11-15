import math

import pytest

from enlace.herramientas import geo, itur, propagacion as prop
from enlace.herramientas.interferencia import ganancia_fuera_eje_dBi


@pytest.mark.parametrize("f,kh,ah,kv,av", [(10, 0.01217, 1.2571, 0.01129, 1.2156), (20, 0.09164, 1.0568, 0.09611, 0.9847),
                                           (30, 0.2403, 0.9485, 0.2291, 0.9129)])
def test_p838_tabla(f, kh, ah, kv, av):
    k, a = itur.coeficientes_lluvia(f, "H")
    assert k == pytest.approx(kh, rel=0.01) and a == pytest.approx(ah, abs=0.005)
    k, a = itur.coeficientes_lluvia(f, "V")
    assert k == pytest.approx(kv, rel=0.01) and a == pytest.approx(av, abs=0.005)


def test_lluvia_escalado_y_inversion():
    A001 = 20.0
    assert itur.atenuacion_lluvia_p(A001, 0.01, 15) == pytest.approx(A001, rel=0.02)
    assert itur.atenuacion_lluvia_p(A001, 0.001, 15) > A001 > itur.atenuacion_lluvia_p(A001, 0.1, 15)
    p = itur.porcentaje_excedido_lluvia(A001, 25.0, 15)
    assert itur.atenuacion_lluvia_p(A001, p, 15) == pytest.approx(25.0, abs=0.01)


def test_factor_r_limitado():
    assert itur.factor_distancia_r(1, 7, 95, 1.3) <= 2.5


def test_fspl_y_friis():
    d, f = 28.0, 7.4
    lam = prop.longitud_onda_m(f)
    assert prop.perdida_espacio_libre_dB(d, f) == pytest.approx(20 * math.log10(4 * math.pi * d * 1000 / lam), abs=0.02)


def test_fresnel_y_curvatura():
    # F1 en el centro de 28 km a 7,4 GHz: sqrt(lambda * 14000 * 14000 / 28000)
    lam = prop.longitud_onda_m(7.4)
    assert float(prop.radio_fresnel_m(14, 14, 7.4)) == pytest.approx(math.sqrt(lam * 7000), rel=0.005)
    assert float(prop.abultamiento_tierra_m(14, 14, 4 / 3)) == pytest.approx(14 * 14 / (12.74 * 4 / 3))


def test_geo():
    d = geo.distancia_km(4.686, -74.048, 4.9378, -74.048)
    assert d == pytest.approx(0.2518 * math.pi / 180 * geo.R_TIERRA_KM, rel=1e-6)
    assert geo.azimut_deg(4.686, -74.048, 4.9378, -74.048) == pytest.approx(0.0, abs=1e-6)
    la, lo = geo.destino(4.686, -74.048, 0, d)
    assert la == pytest.approx(4.9378, abs=1e-6)


def test_diagrama_f699_monotono():
    G = prop.ganancia_parabolica_dBi(1.2, 7.4)
    vals = [ganancia_fuera_eje_dBi(G, 1.2, 7.4, a) for a in (0, 1, 5, 20, 60)]
    assert vals[0] == pytest.approx(G) and all(x >= y for x, y in zip(vals, vals[1:]))
