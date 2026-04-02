"""
wind_statistics.py
Конвертация MATLAB wind_statistics.m → Python

Определяет преобладающее направление ветра по компонентам U, V
и возвращает диапазон скорости (центральные 80% данных).
"""

import numpy as np


def wind_statistics(u_wind: np.ndarray, v_wind: np.ndarray) -> tuple[str, float, float]:
    """
    Рассчитывает преобладающее направление и диапазон скорости ветра.

    Parameters
    ----------
    u_wind : np.ndarray  — зональная компонента ветра (м/с)
    v_wind : np.ndarray  — меридиональная компонента ветра (м/с)

    Returns
    -------
    final_dir   : str   — текстовое описание направления ветра
    s_min       : float — нижняя граница скорости (10-й перцентиль)
    s_max       : float — верхняя граница скорости (90-й перцентиль)
    """
    # Модуль скорости
    S = np.sqrt(u_wind**2 + v_wind**2)
    S_vec = S.flatten()

    # Отсекаем крайние 10% с обеих сторон
    v_min_threshold = np.nanquantile(S_vec, 0.10)
    v_max_threshold = np.nanquantile(S_vec, 0.90)

    # Маска центральных 80% данных
    mask = (S >= v_min_threshold) & (S <= v_max_threshold)

    U_typ = u_wind[mask]
    V_typ = v_wind[mask]

    # Перевод в метеорологические румбы (откуда дует ветер, 0–360°, 0 = Север)
    angles = np.mod(180 + np.degrees(np.arctan2(U_typ, V_typ)), 360)

    # Разбивка на 8 румбов по 45°
    r_idx = (np.floor(np.mod(angles + 22.5, 360) / 45)).astype(int)  # 0..7

    # Статистика направлений
    counts = np.bincount(r_idx, minlength=8)
    percents = counts / len(r_idx) * 100
    sorted_r = np.argsort(percents)[::-1]   # индексы по убыванию %
    sorted_p = percents[sorted_r]

    dirs_text = [
        "северный", "северо-восточный", "восточный", "юго-восточный",
        "южный", "юго-западный", "западный", "северо-западный"
    ]

    # Логика определения направления (полностью идентична MATLAB-оригиналу)
    if sorted_p[0] >= 35 and sorted_p[0] >= sorted_p[1] * 1.5:
        final_dir = dirs_text[sorted_r[0]]

    elif (sorted_p[0] + sorted_p[1]) >= 50:
        final_dir = f"{dirs_text[sorted_r[0]]} и {dirs_text[sorted_r[1]]}"

    elif (sorted_p[0] + sorted_p[1] + sorted_p[2]) >= 65:
        final_dir = (
            f"{dirs_text[sorted_r[0]]}, "
            f"{dirs_text[sorted_r[1]]} и "
            f"{dirs_text[sorted_r[2]]}"
        )

    else:
        final_dir = "переменных направлений"

    s_min = round(float(v_min_threshold), 1)
    s_max = round(float(v_max_threshold), 1)

    return final_dir, s_min, s_max
